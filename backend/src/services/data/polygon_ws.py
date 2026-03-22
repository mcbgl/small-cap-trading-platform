"""
Polygon.io WebSocket client for real-time market data.

Connects to wss://socket.polygon.io/stocks for real-time trades and quotes.
Aggregates trades into 1-minute OHLCV bars, writes to QuestDB, publishes to Redis.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import websockets
import websockets.exceptions

from src.config import settings
from src.db import QuestDBClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WS_URL = "wss://socket.polygon.io/stocks"
REST_BASE_URL = "https://api.polygon.io"

RECONNECT_BASE_DELAY = 1.0  # seconds
RECONNECT_MAX_DELAY = 30.0
HEARTBEAT_INTERVAL = 30.0  # send ping every 30s
HEARTBEAT_TIMEOUT = 10.0  # expect pong within 10s
MAX_MESSAGE_RATE = 50_000  # Polygon max ~50K messages/sec


# ---------------------------------------------------------------------------
# Internal bar aggregator
# ---------------------------------------------------------------------------

@dataclass
class _BarState:
    """Tracks in-progress OHLCV bar for a single symbol in the current minute."""

    symbol: str
    minute_ts: int  # unix timestamp rounded to minute boundary
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: float = 0.0
    vwap_numerator: float = 0.0  # sum(price * size) for VWAP calc
    trade_count: int = 0


class _BarAggregator:
    """
    Aggregates individual trade ticks into 1-minute OHLCV bars.

    Maintains one in-progress bar per symbol. When the minute boundary rolls
    over, the completed bar is flushed and a new bar starts.
    """

    def __init__(self) -> None:
        self._bars: dict[str, _BarState] = {}

    def update(self, symbol: str, price: float, size: float, timestamp_ms: int) -> _BarState | None:
        """
        Ingest a single trade tick.

        Returns the completed bar if a minute boundary was crossed, else None.
        """
        minute_ts = (timestamp_ms // 60_000) * 60_000  # truncate to minute

        current = self._bars.get(symbol)
        completed: _BarState | None = None

        # If we have an existing bar and the minute has rolled over, flush it
        if current is not None and current.minute_ts != minute_ts:
            completed = current
            current = None

        # Start a new bar if needed
        if current is None:
            current = _BarState(
                symbol=symbol,
                minute_ts=minute_ts,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=size,
                vwap_numerator=price * size,
                trade_count=1,
            )
            self._bars[symbol] = current
        else:
            # Update existing bar
            current.high = max(current.high, price)
            current.low = min(current.low, price)
            current.close = price
            current.volume += size
            current.vwap_numerator += price * size
            current.trade_count += 1

        return completed

    def flush_all(self) -> list[_BarState]:
        """Flush all in-progress bars (used at shutdown or end of session)."""
        bars = list(self._bars.values())
        self._bars.clear()
        return bars

    def flush_symbol(self, symbol: str) -> _BarState | None:
        """Flush the in-progress bar for a specific symbol."""
        return self._bars.pop(symbol, None)

    @property
    def active_symbols(self) -> set[str]:
        return set(self._bars.keys())


# ---------------------------------------------------------------------------
# Polygon WebSocket Client
# ---------------------------------------------------------------------------

class PolygonWebSocket:
    """
    Async Polygon.io WebSocket client with automatic reconnection,
    heartbeat monitoring, and in-memory trade-to-bar aggregation.
    """

    def __init__(
        self,
        api_key: str,
        questdb: QuestDBClient,
        redis: "redis.asyncio.Redis",
    ) -> None:
        self._api_key = api_key
        self._questdb = questdb
        self._redis = redis

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscribed_symbols: set[str] = set()
        self._aggregator = _BarAggregator()

        self._connected = False
        self._authenticated = False
        self._should_run = False
        self._reconnect_delay = RECONNECT_BASE_DELAY

        self._listen_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

        self._last_message_ts: float = 0.0
        self._message_count: int = 0
        self._error_count: int = 0

    # -- Public interface ----------------------------------------------------

    async def connect(self) -> None:
        """Establish WebSocket connection and start listening."""
        self._should_run = True
        self._listen_task = asyncio.create_task(self._connection_loop(), name="polygon-ws-listen")
        logger.info("Polygon WebSocket connection loop started")

    async def disconnect(self) -> None:
        """Gracefully disconnect and flush pending bars."""
        logger.info("Polygon WebSocket shutting down")
        self._should_run = False

        # Cancel heartbeat
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Cancel listener
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        # Flush remaining bars to QuestDB
        await self._flush_all_bars()

        # Close WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        self._connected = False
        self._authenticated = False
        logger.info("Polygon WebSocket disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to trade, quote, and minute aggregate channels for given symbols."""
        if not symbols:
            return

        new_symbols = set(s.upper() for s in symbols) - self._subscribed_symbols
        if not new_symbols:
            return

        channels = []
        for sym in new_symbols:
            channels.extend([f"T.{sym}", f"Q.{sym}", f"AM.{sym}"])

        if self._ws and self._authenticated:
            msg = {"action": "subscribe", "params": ",".join(channels)}
            await self._ws.send(json.dumps(msg))
            logger.info("Subscribed to %d new symbols: %s", len(new_symbols), new_symbols)

        self._subscribed_symbols |= new_symbols

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from channels for given symbols."""
        if not symbols:
            return

        remove_symbols = set(s.upper() for s in symbols) & self._subscribed_symbols
        if not remove_symbols:
            return

        channels = []
        for sym in remove_symbols:
            channels.extend([f"T.{sym}", f"Q.{sym}", f"AM.{sym}"])

        if self._ws and self._authenticated:
            msg = {"action": "unsubscribe", "params": ",".join(channels)}
            await self._ws.send(json.dumps(msg))
            logger.info("Unsubscribed from %d symbols: %s", len(remove_symbols), remove_symbols)

        self._subscribed_symbols -= remove_symbols

        # Flush bars for removed symbols
        for sym in remove_symbols:
            bar = self._aggregator.flush_symbol(sym)
            if bar:
                await self._write_bar_to_questdb(bar)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._authenticated

    @property
    def subscribed_symbols(self) -> set[str]:
        return self._subscribed_symbols.copy()

    @property
    def last_message_ts(self) -> float:
        return self._last_message_ts

    @property
    def message_count(self) -> int:
        return self._message_count

    def health(self) -> dict:
        """Return health check information."""
        return {
            "connected": self._connected,
            "authenticated": self._authenticated,
            "symbols_count": len(self._subscribed_symbols),
            "last_message_ts": self._last_message_ts,
            "last_message_age_s": time.time() - self._last_message_ts if self._last_message_ts else None,
            "message_count": self._message_count,
            "error_count": self._error_count,
            "active_bars": len(self._aggregator.active_symbols),
        }

    # -- Connection loop with auto-reconnect --------------------------------

    async def _connection_loop(self) -> None:
        """Main loop: connect, authenticate, listen. Reconnects on failure."""
        while self._should_run:
            try:
                await self._establish_connection()
                self._reconnect_delay = RECONNECT_BASE_DELAY  # reset on success
                await self._listen()
            except asyncio.CancelledError:
                logger.info("WebSocket listen task cancelled")
                return
            except websockets.exceptions.ConnectionClosedError as exc:
                logger.warning("WebSocket connection closed: %s", exc)
                self._error_count += 1
            except Exception as exc:
                logger.error("WebSocket error: %s", exc, exc_info=True)
                self._error_count += 1

            self._connected = False
            self._authenticated = False

            if self._should_run:
                logger.info(
                    "Reconnecting in %.1fs (attempt backoff)",
                    self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, RECONNECT_MAX_DELAY
                )

    async def _establish_connection(self) -> None:
        """Open WS, authenticate, re-subscribe to previously tracked symbols."""
        logger.info("Connecting to Polygon WebSocket at %s", WS_URL)
        self._ws = await websockets.connect(
            WS_URL,
            ping_interval=HEARTBEAT_INTERVAL,
            ping_timeout=HEARTBEAT_TIMEOUT,
            max_size=2**22,  # 4 MB max message size
            close_timeout=5,
        )
        self._connected = True
        logger.info("WebSocket connected, authenticating...")

        # Authenticate
        auth_msg = {"action": "auth", "params": self._api_key}
        await self._ws.send(json.dumps(auth_msg))

        # Wait for auth response
        raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
        messages = json.loads(raw)
        if not isinstance(messages, list):
            messages = [messages]

        auth_success = False
        for msg in messages:
            if msg.get("ev") == "status":
                status = msg.get("status", "")
                if status == "auth_success":
                    auth_success = True
                    logger.info("Polygon WebSocket authenticated successfully")
                elif status == "auth_failed":
                    raise ConnectionError(
                        f"Polygon authentication failed: {msg.get('message', 'unknown')}"
                    )

        if not auth_success:
            # Some messages arrive before the auth_success; keep reading briefly
            for _ in range(5):
                raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
                for msg in json.loads(raw) if isinstance(json.loads(raw), list) else [json.loads(raw)]:
                    if msg.get("ev") == "status" and msg.get("status") == "auth_success":
                        auth_success = True
                        logger.info("Polygon WebSocket authenticated successfully (delayed)")
                        break
                if auth_success:
                    break

        if not auth_success:
            raise ConnectionError("Polygon authentication: no auth_success received")

        self._authenticated = True

        # Re-subscribe to any previously tracked symbols
        if self._subscribed_symbols:
            channels = []
            for sym in self._subscribed_symbols:
                channels.extend([f"T.{sym}", f"Q.{sym}", f"AM.{sym}"])
            sub_msg = {"action": "subscribe", "params": ",".join(channels)}
            await self._ws.send(json.dumps(sub_msg))
            logger.info(
                "Re-subscribed to %d symbols after reconnect",
                len(self._subscribed_symbols),
            )

    # -- Message listener ----------------------------------------------------

    async def _listen(self) -> None:
        """Read messages from the WebSocket and dispatch to handlers."""
        assert self._ws is not None

        async for raw in self._ws:
            if not self._should_run:
                break

            self._last_message_ts = time.time()
            self._message_count += 1

            try:
                messages = json.loads(raw)
                if not isinstance(messages, list):
                    messages = [messages]

                for msg in messages:
                    ev = msg.get("ev")
                    if ev == "T":
                        await self._handle_trade(msg)
                    elif ev == "Q":
                        await self._handle_quote(msg)
                    elif ev == "AM":
                        await self._handle_minute_agg(msg)
                    elif ev == "status":
                        self._handle_status(msg)
                    # A, second agg, etc. — ignored for now

            except json.JSONDecodeError:
                logger.warning("Received non-JSON message: %s", raw[:200])
            except Exception as exc:
                logger.error("Error processing message: %s", exc, exc_info=True)

    # -- Message handlers ----------------------------------------------------

    async def _handle_trade(self, msg: dict) -> None:
        """
        Handle a trade tick (ev=T).

        Fields: sym, p (price), s (size), t (timestamp ms), c (conditions),
                x (exchange id), i (trade id).
        """
        symbol = msg.get("sym", "")
        price = msg.get("p", 0.0)
        size = msg.get("s", 0)
        timestamp_ms = msg.get("t", 0)

        if not symbol or price <= 0:
            return

        # Update in-memory aggregation, check if a bar completed
        completed_bar = self._aggregator.update(symbol, price, size, timestamp_ms)
        if completed_bar:
            await self._write_bar_to_questdb(completed_bar)

        # Publish latest price to Redis for real-time consumers
        try:
            price_data = json.dumps({
                "symbol": symbol,
                "price": price,
                "volume": size,
                "timestamp": datetime.fromtimestamp(
                    timestamp_ms / 1000, tz=timezone.utc
                ).isoformat(),
            })
            # Set key for point-in-time lookups
            await self._redis.set(f"price:{symbol}", price_data, ex=300)
            # Publish to channel for streaming consumers
            await self._redis.publish("channel:prices", price_data)
        except Exception as exc:
            logger.debug("Redis publish error for %s: %s", symbol, exc)

    async def _handle_quote(self, msg: dict) -> None:
        """
        Handle a quote update (ev=Q).

        Fields: sym, bp (bid price), bs (bid size), ap (ask price),
                as_ (ask size), t (timestamp ms).
        """
        symbol = msg.get("sym", "")
        bid_price = msg.get("bp", 0.0)
        ask_price = msg.get("ap", 0.0)

        if not symbol:
            return

        try:
            quote_data = json.dumps({
                "symbol": symbol,
                "bid": bid_price,
                "bid_size": msg.get("bs", 0),
                "ask": ask_price,
                "ask_size": msg.get("as", 0),
                "mid": (bid_price + ask_price) / 2 if bid_price and ask_price else None,
                "timestamp": datetime.fromtimestamp(
                    msg.get("t", 0) / 1000, tz=timezone.utc
                ).isoformat(),
            })
            await self._redis.set(f"quote:{symbol}", quote_data, ex=300)
            await self._redis.publish("channel:quotes", quote_data)
        except Exception as exc:
            logger.debug("Redis publish error for quote %s: %s", symbol, exc)

    async def _handle_minute_agg(self, msg: dict) -> None:
        """
        Handle a minute aggregate bar from Polygon (ev=AM).

        This is Polygon's own server-side aggregation. We write it directly
        to QuestDB, which is authoritative over our client-side aggregation.

        Fields: sym, o, h, l, c, v, vw, s (start timestamp ms), e (end timestamp ms).
        """
        symbol = msg.get("sym", "")
        if not symbol:
            return

        timestamp_ns = msg.get("s", 0) * 1_000_000  # ms -> ns for QuestDB

        line = (
            f"ohlcv,symbol={_escape_tag(symbol)} "
            f"open={msg.get('o', 0.0)},"
            f"high={msg.get('h', 0.0)},"
            f"low={msg.get('l', 0.0)},"
            f"close={msg.get('c', 0.0)},"
            f"volume={msg.get('v', 0.0)}i,"
            f"vwap={msg.get('vw', 0.0)} "
            f"{timestamp_ns}"
        )

        try:
            await self._questdb.write_ilp(line)
        except Exception as exc:
            logger.error("QuestDB write error for AM bar %s: %s", symbol, exc)

        # Also flush any client-side bar for this minute (server-side is authoritative)
        self._aggregator.flush_symbol(symbol)

    def _handle_status(self, msg: dict) -> None:
        """Handle status messages from Polygon."""
        status = msg.get("status", "")
        message = msg.get("message", "")
        logger.info("Polygon status: %s - %s", status, message)

    # -- Bar persistence -----------------------------------------------------

    async def _write_bar_to_questdb(self, bar: _BarState) -> None:
        """Write a completed aggregated bar to QuestDB via ILP."""
        if bar.trade_count == 0:
            return

        vwap = bar.vwap_numerator / bar.volume if bar.volume > 0 else bar.close
        timestamp_ns = bar.minute_ts * 1_000_000  # ms -> ns

        line = (
            f"ohlcv,symbol={_escape_tag(bar.symbol)} "
            f"open={bar.open},"
            f"high={bar.high},"
            f"low={bar.low},"
            f"close={bar.close},"
            f"volume={bar.volume}i,"
            f"vwap={vwap} "
            f"{timestamp_ns}"
        )

        try:
            await self._questdb.write_ilp(line)
            logger.debug(
                "Wrote aggregated bar for %s @ %s: O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f",
                bar.symbol,
                datetime.fromtimestamp(bar.minute_ts / 1000, tz=timezone.utc).isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
            )
        except Exception as exc:
            logger.error("QuestDB write error for aggregated bar %s: %s", bar.symbol, exc)

    async def _flush_all_bars(self) -> None:
        """Flush all in-progress bars to QuestDB (used at shutdown)."""
        bars = self._aggregator.flush_all()
        for bar in bars:
            await self._write_bar_to_questdb(bar)
        if bars:
            logger.info("Flushed %d in-progress bars at shutdown", len(bars))


# ---------------------------------------------------------------------------
# Polygon REST Client (for historical backfill and ticker info)
# ---------------------------------------------------------------------------

class PolygonRESTClient:
    """
    Async Polygon.io REST API client for historical data, ticker details,
    and market snapshots.

    Handles rate limiting (max 5 req/sec for free tier) with a simple
    semaphore and minimum inter-request delay.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.polygon_api_key
        self._client: httpx.AsyncClient | None = None
        self._rate_semaphore = asyncio.Semaphore(5)
        self._last_request_ts: float = 0.0
        self._min_request_interval: float = 0.22  # ~4.5 req/sec, safe under 5/s

    async def init(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=REST_BASE_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
        )
        logger.info("Polygon REST client initialised")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _rate_limited_request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Execute an HTTP request with rate limiting."""
        if not self._client:
            raise RuntimeError("Polygon REST client not initialised — call init() first")

        async with self._rate_semaphore:
            # Enforce minimum interval between requests
            now = time.time()
            elapsed = now - self._last_request_ts
            if elapsed < self._min_request_interval:
                await asyncio.sleep(self._min_request_interval - elapsed)

            response = await self._client.request(method, url, **kwargs)
            self._last_request_ts = time.time()

            if response.status_code == 429:
                # Rate limited — wait and retry once
                retry_after = float(response.headers.get("Retry-After", "5"))
                logger.warning(
                    "Polygon rate limited, retrying after %.1fs", retry_after
                )
                await asyncio.sleep(retry_after)
                response = await self._client.request(method, url, **kwargs)
                self._last_request_ts = time.time()

            response.raise_for_status()
            return response

    async def get_bars(
        self,
        symbol: str,
        timespan: str = "minute",
        from_date: str = "",
        to_date: str = "",
        multiplier: int = 1,
        limit: int = 50_000,
    ) -> list[dict]:
        """
        Fetch OHLCV bars from Polygon REST API.

        Args:
            symbol: Ticker symbol (e.g. "AAPL").
            timespan: Bar resolution — "minute", "hour", "day", "week", "month".
            from_date: Start date as YYYY-MM-DD or unix milliseconds string.
            to_date: End date as YYYY-MM-DD or unix milliseconds string.
            multiplier: Multiplier for timespan (e.g. 5 for 5-minute bars).
            limit: Maximum number of bars to return (max 50000).

        Returns:
            List of bar dicts with keys: o, h, l, c, v, vw, t, n.
        """
        url = f"/v2/aggs/ticker/{symbol.upper()}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": min(limit, 50_000),
        }

        all_results: list[dict] = []
        next_url: str | None = None

        # First request
        resp = await self._rate_limited_request("GET", url, params=params)
        data = resp.json()
        results = data.get("results", [])
        all_results.extend(results)
        next_url = data.get("next_url")

        # Paginate through remaining results
        while next_url and len(all_results) < limit:
            resp = await self._rate_limited_request(
                "GET",
                next_url,
                params={"apiKey": self._api_key},
            )
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            all_results.extend(results)
            next_url = data.get("next_url")

        logger.info(
            "Fetched %d bars for %s (%s %s %s-%s)",
            len(all_results),
            symbol,
            multiplier,
            timespan,
            from_date,
            to_date,
        )
        return all_results[:limit]

    async def get_ticker_details(self, symbol: str) -> dict:
        """
        Fetch ticker details from Polygon reference API.

        Returns dict with keys: ticker, name, market, locale, primary_exchange,
        type, currency_name, market_cap, phone_number, address, description,
        sic_code, sic_description, ticker_root, homepage_url, total_employees,
        list_date, share_class_shares_outstanding, weighted_shares_outstanding.
        """
        url = f"/v3/reference/tickers/{symbol.upper()}"
        resp = await self._rate_limited_request("GET", url)
        data = resp.json()
        return data.get("results", {})

    async def get_snapshot(self, symbols: list[str] | None = None) -> list[dict]:
        """
        Get current market snapshot for given symbols (or all tickers).

        Returns list of snapshot dicts with keys: ticker, todaysChange,
        todaysChangePerc, updated, day, lastTrade, lastQuote, min, prevDay.
        """
        url = "/v2/snapshot/locale/us/markets/stocks/tickers"
        params: dict = {}
        if symbols:
            params["tickers"] = ",".join(s.upper() for s in symbols)

        resp = await self._rate_limited_request("GET", url, params=params)
        data = resp.json()
        return data.get("tickers", [])

    async def get_grouped_daily(self, date: str) -> list[dict]:
        """
        Fetch grouped daily bars for all tickers on a given date.

        Args:
            date: Date as YYYY-MM-DD.

        Returns:
            List of bar dicts with keys: T (ticker), o, h, l, c, v, vw, t, n.
        """
        url = f"/v2/aggs/grouped/locale/us/market/stocks/{date}"
        params = {"adjusted": "true"}
        resp = await self._rate_limited_request("GET", url, params=params)
        data = resp.json()
        return data.get("results", [])


# ---------------------------------------------------------------------------
# ILP helpers
# ---------------------------------------------------------------------------

def _escape_tag(value: str) -> str:
    """Escape special characters in ILP tag values (comma, space, equals)."""
    return value.replace(",", r"\,").replace(" ", r"\ ").replace("=", r"\=")
