"""
Background worker for SEC EDGAR filing and insider monitoring.

Polls EDGAR for new filings and insider transactions on a schedule:
- Every 60 seconds during market hours (9:30 AM - 4:00 PM ET, weekdays)
- Every 5 minutes outside market hours
- Insider activity scanned every 5 minutes regardless of market hours
"""

import asyncio
import logging
from datetime import datetime, time, timezone, timedelta

from src.db import get_db_pool, get_redis
from src.services.data.edgar_monitor import EdgarMonitor
from src.services.data.insider_tracker import InsiderTracker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market hours (US Eastern)
# ---------------------------------------------------------------------------
ET_OFFSET = timedelta(hours=-5)  # EST (naive; DST not handled for simplicity)
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Filing form types to monitor
MONITORED_FORM_TYPES = ["8-K", "10-K", "10-Q", "SC 13D", "SC 13G"]


def _is_market_hours() -> bool:
    """Check if current time is during US market hours (weekdays 9:30-16:00 ET)."""
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc + ET_OFFSET
    weekday = now_et.weekday()  # 0 = Monday, 6 = Sunday
    if weekday >= 5:
        return False
    current_time = now_et.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


async def _get_watchlist_symbols() -> list[dict]:
    """
    Fetch all active watchlist symbols with their CIKs and ticker IDs.

    Returns list of dicts: [{symbol, ticker_id, cik}, ...]
    CIK comes from system_config if stored, otherwise symbol is used for search.
    """
    pool = get_db_pool()

    rows = await pool.fetch(
        """
        SELECT DISTINCT t.id AS ticker_id, t.symbol
        FROM tickers t
        JOIN watchlist_items wi ON wi.ticker_id = t.id
        WHERE t.is_active = true
        ORDER BY t.symbol
        """
    )

    symbols: list[dict] = []
    for row in rows:
        symbols.append(
            {
                "symbol": row["symbol"],
                "ticker_id": row["ticker_id"],
                "cik": "",  # CIK resolved during filing scan if needed
            }
        )

    return symbols


async def _resolve_cik(monitor: EdgarMonitor, symbol: str) -> str:
    """
    Attempt to resolve a CIK for a ticker symbol by searching EDGAR.

    Returns the CIK string if found, empty string otherwise.
    The result can be cached in DB for future lookups.
    """
    try:
        # Search EDGAR for the symbol — first result often has the CIK
        results = await monitor.poll_filings([symbol], form_types=["10-K"], lookback_hours=8760)
        if results and results[0].cik:
            return results[0].cik
    except Exception:
        logger.debug("Could not resolve CIK for %s", symbol)
    return ""


class EdgarWorker:
    """
    Background worker that orchestrates EDGAR filing and insider monitoring.

    Lifecycle:
        worker = EdgarWorker()
        await worker.start()
        ...
        await worker.stop()
    """

    def __init__(self) -> None:
        self._monitor: EdgarMonitor | None = None
        self._tracker: InsiderTracker | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_filing_poll: datetime | None = None
        self._last_insider_scan: datetime | None = None
        # Track health for external monitoring
        self._healthy = False
        self._last_error: str | None = None
        self._polls_completed: int = 0

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Initialise monitor + tracker and start the polling loop."""
        self._monitor = EdgarMonitor()
        self._tracker = InsiderTracker()
        await self._monitor.start()
        await self._tracker.start()
        self._running = True
        self._healthy = True
        self._task = asyncio.create_task(self._run_loop(), name="edgar-worker")
        logger.info("EdgarWorker started")

    async def stop(self) -> None:
        """Stop the polling loop and clean up resources."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._monitor:
            await self._monitor.close()
        if self._tracker:
            await self._tracker.close()
        self._healthy = False
        logger.info("EdgarWorker stopped")

    # -- health check --------------------------------------------------------

    def health(self) -> dict:
        """Return health status for monitoring dashboards."""
        return {
            "running": self._running,
            "healthy": self._healthy,
            "polls_completed": self._polls_completed,
            "last_filing_poll": (
                self._last_filing_poll.isoformat() if self._last_filing_poll else None
            ),
            "last_insider_scan": (
                self._last_insider_scan.isoformat() if self._last_insider_scan else None
            ),
            "last_error": self._last_error,
        }

    # -- polling loop --------------------------------------------------------

    async def _run_loop(self) -> None:
        """Main polling loop — adjusts interval based on market hours."""
        logger.info("EDGAR polling loop started")
        filing_interval_market = 60  # seconds during market hours
        filing_interval_off = 300  # 5 minutes outside market hours
        insider_interval = 300  # always 5 minutes

        while self._running:
            try:
                interval = (
                    filing_interval_market if _is_market_hours() else filing_interval_off
                )

                # -- Filing poll --
                await self._poll_filings()
                self._last_filing_poll = datetime.now(timezone.utc)

                # -- Insider scan (every 5 minutes) --
                should_scan_insiders = (
                    self._last_insider_scan is None
                    or (datetime.now(timezone.utc) - self._last_insider_scan).total_seconds()
                    >= insider_interval
                )
                if should_scan_insiders:
                    await self._scan_insiders()
                    self._last_insider_scan = datetime.now(timezone.utc)

                self._polls_completed += 1
                self._healthy = True
                self._last_error = None

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                logger.info("EDGAR polling loop cancelled")
                raise
            except Exception as exc:
                self._last_error = str(exc)
                self._healthy = False
                logger.exception("Error in EDGAR polling loop")
                # Back off on error to avoid hammering EDGAR
                await asyncio.sleep(60)

    async def _poll_filings(self) -> None:
        """Poll EDGAR for new filings across all watchlist symbols."""
        if not self._monitor:
            return

        watchlist = await _get_watchlist_symbols()
        if not watchlist:
            logger.debug("No watchlist symbols — skipping filing poll")
            return

        symbols = [item["symbol"] for item in watchlist]
        symbol_to_ticker_id = {item["symbol"]: item["ticker_id"] for item in watchlist}

        logger.debug("Polling EDGAR for %d symbols", len(symbols))

        filings = await self._monitor.poll_filings(
            symbols=symbols,
            form_types=MONITORED_FORM_TYPES,
            lookback_hours=24,
        )

        for filing in filings:
            try:
                # Try to match filing to a watchlist symbol
                matched_symbol = self._match_filing_to_symbol(filing, symbols)
                if not matched_symbol:
                    continue

                ticker_id = symbol_to_ticker_id.get(matched_symbol)
                if not ticker_id:
                    continue

                # Download and scan filing text for keywords
                if filing.url:
                    try:
                        text = await self._monitor.get_filing_text(filing.url)
                        filing.keywords_found = self._monitor.search_keywords(text)

                        # Parse 8-K items if applicable
                        if filing.form_type.startswith("8-K"):
                            filing.items_8k = self._monitor.parse_8k_items(text)
                    except Exception:
                        logger.warning(
                            "Could not fetch/parse filing text: %s", filing.url
                        )

                # Store filing in DB
                filing_id = await self._monitor.store_filing(filing, ticker_id)

                # Publish alert if new filing with distress keywords
                if filing_id and filing.keywords_found:
                    await self._monitor.publish_filing_alert(filing, matched_symbol)
                    logger.info(
                        "Filing alert: %s %s — %d distress keywords found",
                        matched_symbol,
                        filing.form_type,
                        len(filing.keywords_found),
                    )

            except Exception:
                logger.exception(
                    "Error processing filing %s", filing.accession_number
                )

    def _match_filing_to_symbol(
        self,
        filing: "EdgarMonitor.FilingResult | object",
        symbols: list[str],
    ) -> str | None:
        """
        Try to match a filing to one of our watchlist symbols.

        Checks entity_name and title against known symbols.
        """
        # Import here to avoid circular issues with type annotation
        from src.services.data.edgar_monitor import FilingResult

        if not isinstance(filing, FilingResult):
            return None

        entity_upper = (filing.entity_name or "").upper()
        title_upper = (filing.title or "").upper()

        for sym in symbols:
            sym_upper = sym.upper()
            if sym_upper in entity_upper or sym_upper in title_upper:
                return sym

        return None

    async def _scan_insiders(self) -> None:
        """Scan for insider cluster buying across all watchlist symbols."""
        if not self._tracker:
            return

        watchlist = await _get_watchlist_symbols()
        if not watchlist:
            return

        symbols = [item["symbol"] for item in watchlist]
        logger.debug("Scanning insider activity for %d symbols", len(symbols))

        clusters = await self._tracker.scan_insider_activity(symbols, lookback_days=10)

        for cluster in clusters:
            try:
                # Store as a signal
                signal_id = await self._tracker.store_cluster_signal(cluster)
                if signal_id:
                    await self._tracker.publish_insider_alert(cluster)
                    logger.info(
                        "Insider cluster signal for %s: %d insiders, score=%.1f",
                        cluster.symbol,
                        cluster.cluster_count,
                        cluster.score,
                    )
            except Exception:
                logger.exception(
                    "Error storing insider cluster for %s", cluster.symbol
                )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

_worker: EdgarWorker | None = None


async def start_edgar_worker() -> EdgarWorker:
    """
    Create and start the global EDGAR worker.

    Typically called from the FastAPI lifespan or a management command.
    """
    global _worker
    if _worker and _worker._running:
        logger.warning("EDGAR worker already running")
        return _worker

    _worker = EdgarWorker()
    await _worker.start()
    return _worker


async def stop_edgar_worker() -> None:
    """Stop the global EDGAR worker."""
    global _worker
    if _worker:
        await _worker.stop()
        _worker = None


def get_edgar_worker() -> EdgarWorker | None:
    """Return the current EDGAR worker instance (or None if not started)."""
    return _worker
