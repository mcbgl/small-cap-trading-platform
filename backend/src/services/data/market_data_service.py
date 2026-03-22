"""
Market data service -- coordinates Polygon WS, bar storage, and price distribution.

Central service layer that manages:
- Real-time price streaming via Polygon WebSocket
- Historical bar storage in QuestDB
- Price distribution to consumers via Redis pub/sub
- Dynamic symbol subscription management
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis

from src.db import QuestDBClient
from src.services.data.polygon_ws import PolygonRESTClient, PolygonWebSocket

logger = logging.getLogger(__name__)


class MarketDataService:
    """
    Coordinates Polygon WebSocket streaming, QuestDB bar storage, and
    Redis-based price distribution for real-time and historical market data.
    """

    def __init__(
        self,
        questdb: QuestDBClient,
        redis: aioredis.Redis,
        api_key: str,
    ) -> None:
        self._questdb = questdb
        self._redis = redis
        self._api_key = api_key

        self._ws_client: PolygonWebSocket | None = None
        self._rest_client: PolygonRESTClient | None = None
        self._running = False

    # -- Lifecycle -----------------------------------------------------------

    async def start(self, symbols: list[str] | None = None) -> None:
        """
        Initialize Polygon clients, connect WebSocket, and subscribe to symbols.

        Args:
            symbols: Initial list of symbols to subscribe to. If None, starts
                     with no subscriptions (add later via add_symbols).
        """
        if self._running:
            logger.warning("MarketDataService is already running")
            return

        logger.info("Starting MarketDataService")

        # Initialize REST client for backfill operations
        self._rest_client = PolygonRESTClient(api_key=self._api_key)
        await self._rest_client.init()

        # Initialize and connect WebSocket
        self._ws_client = PolygonWebSocket(
            api_key=self._api_key,
            questdb=self._questdb,
            redis=self._redis,
        )
        await self._ws_client.connect()

        # Subscribe to initial symbols if provided
        if symbols:
            await self._ws_client.subscribe(symbols)
            logger.info("Subscribed to %d initial symbols", len(symbols))

        self._running = True
        logger.info("MarketDataService started")

    async def stop(self) -> None:
        """Disconnect WebSocket, flush pending bars, close REST client."""
        if not self._running:
            return

        logger.info("Stopping MarketDataService")
        self._running = False

        if self._ws_client:
            await self._ws_client.disconnect()
            self._ws_client = None

        if self._rest_client:
            await self._rest_client.close()
            self._rest_client = None

        logger.info("MarketDataService stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # -- Symbol management ---------------------------------------------------

    async def add_symbols(self, symbols: list[str]) -> None:
        """
        Subscribe to additional symbols for real-time data.

        Args:
            symbols: List of ticker symbols to add (e.g. ["AAPL", "MSFT"]).
        """
        if not self._ws_client:
            raise RuntimeError("MarketDataService not started")

        await self._ws_client.subscribe(symbols)
        logger.info("Added %d symbols to market data feed", len(symbols))

    async def remove_symbols(self, symbols: list[str]) -> None:
        """
        Unsubscribe from symbols and flush their pending bars.

        Args:
            symbols: List of ticker symbols to remove.
        """
        if not self._ws_client:
            raise RuntimeError("MarketDataService not started")

        await self._ws_client.unsubscribe(symbols)
        logger.info("Removed %d symbols from market data feed", len(symbols))

    async def get_subscribed_symbols(self) -> set[str]:
        """Return the set of currently subscribed symbols."""
        if not self._ws_client:
            return set()
        return self._ws_client.subscribed_symbols

    # -- Price access --------------------------------------------------------

    async def get_latest_price(self, symbol: str) -> dict | None:
        """
        Read the latest cached price for a symbol from Redis.

        Returns:
            Dict with keys: symbol, price, volume, timestamp.
            None if no price is cached.
        """
        raw = await self._redis.get(f"price:{symbol.upper()}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def get_latest_quote(self, symbol: str) -> dict | None:
        """
        Read the latest cached quote for a symbol from Redis.

        Returns:
            Dict with keys: symbol, bid, bid_size, ask, ask_size, mid, timestamp.
            None if no quote is cached.
        """
        raw = await self._redis.get(f"quote:{symbol.upper()}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def get_latest_prices_bulk(self, symbols: list[str]) -> dict[str, dict | None]:
        """
        Read latest cached prices for multiple symbols.

        Returns:
            Dict mapping symbol -> price data dict (or None if not cached).
        """
        result: dict[str, dict | None] = {}
        if not symbols:
            return result

        keys = [f"price:{s.upper()}" for s in symbols]
        values = await self._redis.mget(keys)
        for sym, raw in zip(symbols, values):
            if raw is not None:
                try:
                    result[sym.upper()] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    result[sym.upper()] = None
            else:
                result[sym.upper()] = None
        return result

    # -- Historical bars (QuestDB) -------------------------------------------

    async def get_bars(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        timespan: str = "minute",
    ) -> list[dict]:
        """
        Query OHLCV bars from QuestDB.

        Args:
            symbol: Ticker symbol.
            start: Start datetime (inclusive). Defaults to 24h ago.
            end: End datetime (inclusive). Defaults to now.
            timespan: Currently only "minute" is stored; parameter reserved for
                      future SAMPLE BY aggregation support.

        Returns:
            List of bar dicts with keys: timestamp, open, high, low, close,
            volume, vwap.
        """
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(hours=24)
        if end is None:
            end = datetime.now(timezone.utc)

        start_str = start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # Use SAMPLE BY for different timespans
        sample_clause = ""
        if timespan == "5minute":
            sample_clause = "SAMPLE BY 5m"
        elif timespan == "15minute":
            sample_clause = "SAMPLE BY 15m"
        elif timespan == "hour":
            sample_clause = "SAMPLE BY 1h"
        elif timespan == "day":
            sample_clause = "SAMPLE BY 1d"

        if sample_clause:
            sql = (
                f"SELECT timestamp, first(open) as open, max(high) as high, "
                f"min(low) as low, last(close) as close, sum(volume) as volume, "
                f"avg(vwap) as vwap "
                f"FROM ohlcv "
                f"WHERE symbol = '{_escape_sql(symbol.upper())}' "
                f"AND timestamp >= '{start_str}' "
                f"AND timestamp <= '{end_str}' "
                f"{sample_clause} "
                f"ORDER BY timestamp ASC"
            )
        else:
            sql = (
                f"SELECT timestamp, open, high, low, close, volume, vwap "
                f"FROM ohlcv "
                f"WHERE symbol = '{_escape_sql(symbol.upper())}' "
                f"AND timestamp >= '{start_str}' "
                f"AND timestamp <= '{end_str}' "
                f"ORDER BY timestamp ASC"
            )

        try:
            result = await self._questdb.query(sql)
            columns = result.get("columns", [])
            dataset = result.get("dataset", [])

            col_names = [c["name"] for c in columns]
            return [dict(zip(col_names, row)) for row in dataset]
        except Exception as exc:
            logger.error("QuestDB query error for bars %s: %s", symbol, exc)
            return []

    # -- Backfill ------------------------------------------------------------

    async def backfill(
        self,
        symbol: str,
        days: int = 30,
        timespan: str = "minute",
    ) -> int:
        """
        Backfill historical OHLCV bars from Polygon REST API into QuestDB.

        Args:
            symbol: Ticker symbol to backfill.
            days: Number of days of history to fetch (default 30).
            timespan: Bar resolution (default "minute").

        Returns:
            Number of bars written to QuestDB.
        """
        if not self._rest_client:
            raise RuntimeError("MarketDataService not started — REST client unavailable")

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        from_str = start_date.strftime("%Y-%m-%d")
        to_str = end_date.strftime("%Y-%m-%d")

        logger.info(
            "Backfilling %s bars for %s from %s to %s",
            timespan,
            symbol,
            from_str,
            to_str,
        )

        bars = await self._rest_client.get_bars(
            symbol=symbol,
            timespan=timespan,
            from_date=from_str,
            to_date=to_str,
        )

        if not bars:
            logger.info("No bars returned for %s backfill", symbol)
            return 0

        # Write bars to QuestDB in batches via ILP
        batch_size = 500
        written = 0

        for i in range(0, len(bars), batch_size):
            batch = bars[i : i + batch_size]
            lines = []
            for bar in batch:
                timestamp_ns = bar.get("t", 0) * 1_000_000  # ms -> ns
                line = (
                    f"ohlcv,symbol={_escape_ilp_tag(symbol.upper())} "
                    f"open={bar.get('o', 0.0)},"
                    f"high={bar.get('h', 0.0)},"
                    f"low={bar.get('l', 0.0)},"
                    f"close={bar.get('c', 0.0)},"
                    f"volume={bar.get('v', 0)}i,"
                    f"vwap={bar.get('vw', 0.0)} "
                    f"{timestamp_ns}"
                )
                lines.append(line)

            # Write batch as a single ILP payload (newline-separated)
            payload = "\n".join(lines)
            try:
                await self._questdb.write_ilp(payload)
                written += len(batch)
            except Exception as exc:
                logger.error(
                    "QuestDB write error during backfill for %s (batch %d): %s",
                    symbol,
                    i // batch_size,
                    exc,
                )

        logger.info("Backfill complete for %s: %d bars written", symbol, written)
        return written

    # -- Ticker info ---------------------------------------------------------

    async def get_ticker_details(self, symbol: str) -> dict | None:
        """Fetch ticker details from Polygon REST API (cached in Redis for 1h)."""
        cache_key = f"ticker_details:{symbol.upper()}"
        cached = await self._redis.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                pass

        if not self._rest_client:
            return None

        try:
            details = await self._rest_client.get_ticker_details(symbol)
            if details:
                await self._redis.set(
                    cache_key,
                    json.dumps(details),
                    ex=3600,  # cache for 1 hour
                )
            return details
        except Exception as exc:
            logger.error("Error fetching ticker details for %s: %s", symbol, exc)
            return None

    # -- Health check --------------------------------------------------------

    def health(self) -> dict:
        """Return health status of the market data service."""
        ws_health = self._ws_client.health() if self._ws_client else {}
        return {
            "running": self._running,
            "ws": ws_health,
            "rest_client_active": self._rest_client is not None,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape_sql(value: str) -> str:
    """Basic SQL injection prevention for string literals."""
    return value.replace("'", "''")


def _escape_ilp_tag(value: str) -> str:
    """Escape special characters in ILP tag values."""
    return value.replace(",", r"\,").replace(" ", r"\ ").replace("=", r"\=")
