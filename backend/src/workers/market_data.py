"""
Background worker for continuous market data ingestion.

Runs as a long-lived task in the FastAPI lifespan, managing the MarketDataService
with awareness of market hours, dynamic watchlist refresh, and health reporting.
"""

import asyncio
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg

from src.config import settings
from src.db import QuestDBClient, get_db_pool, get_redis
from src.services.data.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")

MARKET_OPEN = dtime(9, 30)   # 9:30 AM ET
MARKET_CLOSE = dtime(16, 0)  # 4:00 PM ET
PRE_MARKET_BUFFER = timedelta(minutes=15)  # connect 15 min before open
POST_MARKET_BUFFER = timedelta(minutes=5)   # disconnect 5 min after close

WATCHLIST_REFRESH_INTERVAL = 60  # seconds
HEALTH_LOG_INTERVAL = 300  # log health every 5 minutes

# US market holidays 2025-2026 (NYSE observed holidays)
# This is a simplified list; production should use a holiday calendar API
US_MARKET_HOLIDAYS: set[str] = {
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18",
    "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01",
    "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_service: MarketDataService | None = None
_worker_task: asyncio.Task | None = None
_should_run = False


# ---------------------------------------------------------------------------
# Market hours helpers
# ---------------------------------------------------------------------------

def _now_et() -> datetime:
    """Current time in US Eastern."""
    return datetime.now(ET)


def _is_trading_day(dt: datetime | None = None) -> bool:
    """Check if the given date is a trading day (weekday, not a holiday)."""
    if dt is None:
        dt = _now_et()
    # Weekend check
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    # Holiday check
    date_str = dt.strftime("%Y-%m-%d")
    if date_str in US_MARKET_HOLIDAYS:
        return False
    return True


def _is_market_hours(dt: datetime | None = None) -> bool:
    """
    Check if the market is currently open (including pre/post buffer).

    Returns True if within the buffered market hours on a trading day.
    """
    if dt is None:
        dt = _now_et()
    if not _is_trading_day(dt):
        return False
    current_time = dt.time()
    buffered_open = (
        datetime.combine(dt.date(), MARKET_OPEN, tzinfo=ET) - PRE_MARKET_BUFFER
    ).time()
    buffered_close = (
        datetime.combine(dt.date(), MARKET_CLOSE, tzinfo=ET) + POST_MARKET_BUFFER
    ).time()
    return buffered_open <= current_time <= buffered_close


def _seconds_until_market_open() -> float:
    """
    Calculate seconds until the next market open (with pre-market buffer).

    Accounts for weekends and holidays.
    """
    now = _now_et()

    # Find next trading day
    target = now
    for _ in range(10):  # max 10 days ahead (long weekends / holidays)
        if _is_trading_day(target):
            open_dt = datetime.combine(target.date(), MARKET_OPEN, tzinfo=ET)
            buffered_open_dt = open_dt - PRE_MARKET_BUFFER
            if target.date() == now.date() and now < buffered_open_dt:
                # Today is a trading day and market hasn't opened yet
                return (buffered_open_dt - now).total_seconds()
            elif target.date() > now.date():
                # Future trading day
                return (buffered_open_dt - now).total_seconds()
        target += timedelta(days=1)

    # Fallback: wait 1 hour and re-check
    return 3600.0


# ---------------------------------------------------------------------------
# Watchlist loading from PostgreSQL
# ---------------------------------------------------------------------------

async def _load_watchlist_symbols(pool: asyncpg.Pool) -> list[str]:
    """
    Load all active watchlist symbols from PostgreSQL.

    Queries the watchlist_items table joined with tickers to get distinct
    symbols that are currently on any active watchlist.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT t.symbol
                FROM watchlist_items wi
                JOIN tickers t ON t.id = wi.ticker_id
                WHERE t.is_active = true
                ORDER BY t.symbol
                """
            )
            symbols = [row["symbol"] for row in rows]
            logger.info("Loaded %d watchlist symbols from database", len(symbols))
            return symbols
    except asyncpg.UndefinedTableError:
        logger.warning(
            "Watchlist tables not found — database may not be migrated. "
            "Starting with empty watchlist."
        )
        return []
    except Exception as exc:
        logger.error("Error loading watchlist symbols: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def _worker_loop() -> None:
    """
    Main worker loop.

    - Waits for market hours before connecting.
    - Connects and subscribes to watchlist symbols.
    - Periodically refreshes subscriptions.
    - Disconnects outside market hours.
    - Repeats daily.
    """
    global _service, _should_run

    pool = get_db_pool()
    redis = get_redis()
    questdb = QuestDBClient()
    await questdb.init()

    _service = MarketDataService(
        questdb=questdb,
        redis=redis,
        api_key=settings.polygon_api_key,
    )

    last_health_log = 0.0
    last_watchlist_refresh = 0.0

    logger.info("Market data worker started, entering main loop")

    try:
        while _should_run:
            # ---- Wait for market hours ----
            if not _is_market_hours():
                if _service.is_running:
                    logger.info("Market closed, stopping data service")
                    await _service.stop()

                wait_seconds = _seconds_until_market_open()
                # Cap the wait so we re-check periodically
                actual_wait = min(wait_seconds, 300.0)
                logger.info(
                    "Outside market hours. Next open in %.0f minutes. "
                    "Sleeping %.0fs before re-check.",
                    wait_seconds / 60,
                    actual_wait,
                )
                await asyncio.sleep(actual_wait)
                continue

            # ---- Start service if not running ----
            if not _service.is_running:
                symbols = await _load_watchlist_symbols(pool)
                if not symbols:
                    logger.warning(
                        "No watchlist symbols found. Will retry in %ds.",
                        WATCHLIST_REFRESH_INTERVAL,
                    )
                    await asyncio.sleep(WATCHLIST_REFRESH_INTERVAL)
                    continue

                logger.info("Market open, starting data service with %d symbols", len(symbols))
                await _service.start(symbols=symbols)
                last_watchlist_refresh = asyncio.get_event_loop().time()

            # ---- Periodic watchlist refresh ----
            now_mono = asyncio.get_event_loop().time()
            if now_mono - last_watchlist_refresh >= WATCHLIST_REFRESH_INTERVAL:
                try:
                    current_symbols = await _load_watchlist_symbols(pool)
                    subscribed = await _service.get_subscribed_symbols()

                    new_set = set(current_symbols)
                    to_add = list(new_set - subscribed)
                    to_remove = list(subscribed - new_set)

                    if to_add:
                        await _service.add_symbols(to_add)
                        logger.info("Added %d new symbols: %s", len(to_add), to_add[:10])
                    if to_remove:
                        await _service.remove_symbols(to_remove)
                        logger.info("Removed %d symbols: %s", len(to_remove), to_remove[:10])
                except Exception as exc:
                    logger.error("Error refreshing watchlist: %s", exc)

                last_watchlist_refresh = now_mono

            # ---- Periodic health logging ----
            if now_mono - last_health_log >= HEALTH_LOG_INTERVAL:
                health = _service.health()
                logger.info("Market data health: %s", health)
                last_health_log = now_mono

            # ---- Sleep before next iteration ----
            await asyncio.sleep(5.0)

    except asyncio.CancelledError:
        logger.info("Market data worker cancelled")
    except Exception as exc:
        logger.error("Market data worker fatal error: %s", exc, exc_info=True)
    finally:
        if _service and _service.is_running:
            await _service.stop()
        await questdb.close()
        logger.info("Market data worker stopped")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def start_market_data_worker() -> None:
    """
    Start the background market data worker.

    Call this during FastAPI lifespan startup. The worker will manage its own
    connection lifecycle based on market hours.
    """
    global _worker_task, _should_run

    if not settings.polygon_api_key:
        logger.warning(
            "Polygon API key not configured — market data worker will not start. "
            "Set POLYGON_API_KEY in environment."
        )
        return

    _should_run = True
    _worker_task = asyncio.create_task(_worker_loop(), name="market-data-worker")
    logger.info("Market data worker task created")


async def stop_market_data_worker() -> None:
    """
    Gracefully stop the background market data worker.

    Call this during FastAPI lifespan shutdown.
    """
    global _worker_task, _should_run, _service

    logger.info("Stopping market data worker")
    _should_run = False

    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None

    _service = None
    logger.info("Market data worker stopped")


def get_market_data_service() -> MarketDataService | None:
    """
    Return the active MarketDataService instance.

    Returns None if the worker is not running or the service is inactive.
    Useful for API routes that need to query prices or bars.
    """
    return _service


def health_check() -> dict:
    """
    Return health information for the market data worker.

    Suitable for inclusion in a /health endpoint response.
    """
    now = _now_et()
    return {
        "worker_running": _should_run and _worker_task is not None and not _worker_task.done(),
        "service_active": _service.is_running if _service else False,
        "market_open": _is_market_hours(),
        "is_trading_day": _is_trading_day(),
        "current_time_et": now.isoformat(),
        "service_health": _service.health() if _service else None,
    }
