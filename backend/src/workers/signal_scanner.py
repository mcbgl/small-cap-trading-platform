"""
Background worker for periodic signal scanning.

Runs full signal sweeps on schedule during market hours.
Quick scan every 5 min, full scan every 30 min.
"""

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.db import QuestDBClient, get_db_pool
from src.services.signals.engine import SignalEngine

logger = logging.getLogger(__name__)

# Market hours (US Eastern)
_ET = ZoneInfo("America/New_York")
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MINUTE = 30
_MARKET_CLOSE_HOUR = 16
_MARKET_CLOSE_MINUTE = 0

# Scan intervals (seconds)
_QUICK_SCAN_INTERVAL = 5 * 60     # 5 minutes
_FULL_SCAN_INTERVAL = 30 * 60     # 30 minutes
_HEALTH_CHECK_INTERVAL = 60       # 1 minute


def _is_market_hours() -> bool:
    """Return ``True`` if the current time falls within US equity market hours."""
    now_et = datetime.now(_ET)

    # Weekends
    if now_et.weekday() >= 5:
        return False

    market_open = now_et.replace(
        hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0
    )
    market_close = now_et.replace(
        hour=_MARKET_CLOSE_HOUR, minute=_MARKET_CLOSE_MINUTE, second=0, microsecond=0
    )
    return market_open <= now_et <= market_close


async def _get_watchlist_symbols() -> list[str]:
    """
    Load the active symbol universe from the database.

    Returns symbols from the default watchlist plus any tickers flagged
    as actively tracked.
    """
    pool = get_db_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT t.symbol
        FROM tickers t
        WHERE t.is_active = true
        ORDER BY t.symbol
        LIMIT 500
        """
    )
    return [row["symbol"] for row in rows]


class SignalScanner:
    """
    Background worker that runs periodic signal scans during market hours.

    - Quick scan (volume + squeeze) every 5 minutes
    - Full scan (all signal types) every 30 minutes
    - Health check every 60 seconds
    """

    def __init__(self) -> None:
        self._engine: SignalEngine | None = None
        self._questdb: QuestDBClient | None = None
        self._running: bool = False
        self._last_quick_scan: float = 0.0
        self._last_full_scan: float = 0.0
        self._scan_count: int = 0
        self._error_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise connections and start the scan loop."""
        self._questdb = QuestDBClient()
        await self._questdb.init()

        self._engine = SignalEngine(self._questdb)
        await self._engine.init()

        self._running = True
        logger.info("SignalScanner started")

        try:
            await self._run_loop()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully shut down."""
        self._running = False
        if self._engine:
            await self._engine.close()
            self._engine = None
        if self._questdb:
            await self._questdb.close()
            self._questdb = None
        logger.info("SignalScanner stopped (scans=%d, errors=%d)", self._scan_count, self._error_count)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Core loop — check market hours, run scans on schedule."""
        while self._running:
            try:
                if not _is_market_hours():
                    logger.debug("Outside market hours — sleeping 60s")
                    await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
                    continue

                now = asyncio.get_event_loop().time()

                # Full scan (every 30 min)
                if now - self._last_full_scan >= _FULL_SCAN_INTERVAL:
                    await self._do_full_scan()
                    self._last_full_scan = now
                    # Full scan subsumes quick scan
                    self._last_quick_scan = now

                # Quick scan (every 5 min)
                elif now - self._last_quick_scan >= _QUICK_SCAN_INTERVAL:
                    await self._do_quick_scan()
                    self._last_quick_scan = now

                # Sleep until next check
                await asyncio.sleep(min(_QUICK_SCAN_INTERVAL, 30))

            except asyncio.CancelledError:
                logger.info("SignalScanner cancelled")
                break
            except Exception:
                self._error_count += 1
                logger.exception("SignalScanner loop error (#%d)", self._error_count)
                await asyncio.sleep(30)  # back off on error

    # ------------------------------------------------------------------
    # Scan implementations
    # ------------------------------------------------------------------

    async def _do_full_scan(self) -> None:
        """Run all signal modules across the entire watchlist."""
        if not self._engine:
            return

        symbols = await _get_watchlist_symbols()
        if not symbols:
            logger.warning("No active symbols for full scan")
            return

        logger.info("Starting full scan (%d symbols)", len(symbols))
        results = await self._engine.run_scan(symbols)
        self._scan_count += 1

        total_signals = sum(len(v) for v in results.values())
        logger.info(
            "Full scan #%d complete: %d signals across %d symbols",
            self._scan_count,
            total_signals,
            len(results),
        )

    async def _do_quick_scan(self) -> None:
        """Run volume + squeeze modules only for fast intraday detection."""
        if not self._engine:
            return

        symbols = await _get_watchlist_symbols()
        if not symbols:
            logger.warning("No active symbols for quick scan")
            return

        logger.info("Starting quick scan (%d symbols)", len(symbols))
        results = await self._engine.run_quick_scan(symbols)
        self._scan_count += 1

        total_signals = sum(len(v) for v in results.values())
        logger.info(
            "Quick scan #%d complete: %d signals across %d symbols",
            self._scan_count,
            total_signals,
            len(results),
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """Return a health-check summary of the scanner state."""
        return {
            "running": self._running,
            "market_hours": _is_market_hours(),
            "scan_count": self._scan_count,
            "error_count": self._error_count,
            "last_quick_scan": self._last_quick_scan,
            "last_full_scan": self._last_full_scan,
        }


async def start_signal_scanner() -> None:
    """
    Entry point for launching the signal scanner as a background task.

    Intended to be called from the application startup (e.g., FastAPI lifespan)
    via ``asyncio.create_task(start_signal_scanner())``.
    """
    scanner = SignalScanner()
    await scanner.start()
