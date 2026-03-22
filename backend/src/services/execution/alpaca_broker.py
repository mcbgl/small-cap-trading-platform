"""
Alpaca broker integration for paper trading.

Uses Alpaca Trade API (REST) for paper trading with $100K simulated balance.
Supports limit orders only (per conservative defaults). Position reconciliation
every 5 minutes.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BrokerOrder:
    """Normalized order representation returned by the broker."""

    broker_order_id: str
    symbol: str
    side: str
    qty: float
    price: float | None
    order_type: str
    status: str
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class BrokerPosition:
    """Normalized position representation returned by the broker."""

    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float
    raw: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Alpaca error mapping
# ---------------------------------------------------------------------------

_ALPACA_ERROR_MAP: dict[int, str] = {
    403: "Alpaca API: forbidden — check API key permissions",
    404: "Alpaca API: resource not found",
    422: "Alpaca API: unprocessable entity — invalid order parameters",
    429: "Alpaca API: rate limit exceeded (200 req/min) — retry later",
    500: "Alpaca API: internal server error — try again",
}


class AlpacaApiError(Exception):
    """Raised when an Alpaca API call fails."""

    def __init__(self, status_code: int, detail: str, raw: dict | None = None):
        self.status_code = status_code
        self.detail = detail
        self.raw = raw or {}
        super().__init__(f"Alpaca {status_code}: {detail}")


# ---------------------------------------------------------------------------
# Status mapping: Alpaca status -> our OrderStatus string
# ---------------------------------------------------------------------------

_STATUS_MAP: dict[str, str] = {
    "new": "submitted",
    "accepted": "submitted",
    "pending_new": "submitted",
    "partially_filled": "submitted",
    "filled": "filled",
    "done_for_day": "submitted",
    "canceled": "cancelled",
    "expired": "cancelled",
    "replaced": "submitted",
    "pending_cancel": "submitted",
    "pending_replace": "submitted",
    "stopped": "submitted",
    "rejected": "rejected",
    "suspended": "rejected",
}


# ---------------------------------------------------------------------------
# Broker class
# ---------------------------------------------------------------------------


class AlpacaBroker:
    """
    Async Alpaca REST client for paper (or live) trading.

    All public methods are async.  The broker enforces
    ``settings.limit_orders_only`` and ``settings.no_extended_hours`` locally
    before sending anything to Alpaca.
    """

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or settings.alpaca_api_key
        self.secret_key = secret_key or settings.alpaca_secret_key
        self.base_url = (base_url or settings.alpaca_base_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Return (lazily-created) httpx async client with auth headers."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "APCA-API-KEY-ID": self.api_key,
                    "APCA-API-SECRET-KEY": self.secret_key,
                },
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -- helpers -------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        """Execute an HTTP request against the Alpaca API and return JSON."""
        client = await self._get_client()
        resp = await client.request(method, path, json=json, params=params)

        if resp.status_code >= 400:
            detail = _ALPACA_ERROR_MAP.get(resp.status_code, "")
            try:
                body = resp.json()
                detail = body.get("message", detail) or detail
            except Exception:
                body = {}
            raise AlpacaApiError(resp.status_code, detail, raw=body)

        if resp.status_code == 204:
            return {}
        return resp.json()

    @staticmethod
    def _parse_order(data: dict) -> BrokerOrder:
        """Convert raw Alpaca order JSON to a BrokerOrder."""
        return BrokerOrder(
            broker_order_id=data["id"],
            symbol=data["symbol"],
            side=data["side"],
            qty=float(data.get("qty") or 0),
            price=float(data["limit_price"]) if data.get("limit_price") else None,
            order_type=data["type"],
            status=_STATUS_MAP.get(data.get("status", ""), data.get("status", "")),
            filled_qty=float(data.get("filled_qty") or 0),
            filled_avg_price=(
                float(data["filled_avg_price"]) if data.get("filled_avg_price") else None
            ),
            submitted_at=_parse_ts(data.get("submitted_at")),
            filled_at=_parse_ts(data.get("filled_at")),
            raw=data,
        )

    @staticmethod
    def _parse_position(data: dict) -> BrokerPosition:
        """Convert raw Alpaca position JSON to a BrokerPosition."""
        return BrokerPosition(
            symbol=data["symbol"],
            qty=float(data.get("qty") or 0),
            avg_entry_price=float(data.get("avg_entry_price") or 0),
            current_price=float(data.get("current_price") or 0),
            unrealized_pnl=float(data.get("unrealized_pl") or 0),
            market_value=float(data.get("market_value") or 0),
            raw=data,
        )

    # -- account -------------------------------------------------------------

    async def is_available(self) -> bool:
        """Check Alpaca API connectivity by hitting the account endpoint."""
        try:
            await self._request("GET", "/v2/account")
            return True
        except Exception as exc:
            logger.warning("Alpaca unavailable: %s", exc)
            return False

    async def get_account(self) -> dict:
        """Return Alpaca account info (equity, buying_power, cash, etc.)."""
        data = await self._request("GET", "/v2/account")
        return {
            "id": data.get("id"),
            "status": data.get("status"),
            "equity": float(data.get("equity") or 0),
            "buying_power": float(data.get("buying_power") or 0),
            "cash": float(data.get("cash") or 0),
            "portfolio_value": float(data.get("portfolio_value") or 0),
            "pattern_day_trader": data.get("pattern_day_trader", False),
            "trading_blocked": data.get("trading_blocked", False),
            "account_blocked": data.get("account_blocked", False),
            "currency": data.get("currency", "USD"),
        }

    # -- orders --------------------------------------------------------------

    async def submit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float | None,
        order_type: str = "limit",
        time_in_force: str = "day",
        stop_loss: float | None = None,
    ) -> BrokerOrder:
        """
        Submit an order to Alpaca.

        Enforces ``settings.limit_orders_only`` and
        ``settings.no_extended_hours`` before sending.

        When *stop_loss* is provided the order is submitted as an OTO
        (one-triggers-other) bracket with a stop-loss leg.
        """
        # Enforce limit-only
        if settings.limit_orders_only and order_type != "limit":
            raise AlpacaApiError(
                422,
                f"Only limit orders allowed (got {order_type}); "
                "set LIMIT_ORDERS_ONLY=false to allow other types",
            )

        payload: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "qty": str(qty),
            "type": order_type,
            "time_in_force": time_in_force,
        }

        if order_type == "limit" and price is not None:
            payload["limit_price"] = str(price)

        if settings.no_extended_hours:
            payload["extended_hours"] = False

        # Bracket with stop-loss leg
        if stop_loss is not None:
            payload["order_class"] = "oto"
            payload["stop_loss"] = {"stop_price": str(stop_loss)}

        logger.info(
            "Alpaca submit_order: %s %s %s @ %s (stop=%s)",
            side, qty, symbol, price, stop_loss,
        )
        data = await self._request("POST", "/v2/orders", json=payload)
        order = self._parse_order(data)
        logger.info("Alpaca order created: %s (status=%s)", order.broker_order_id, order.status)
        return order

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an open order by its Alpaca order ID."""
        try:
            await self._request("DELETE", f"/v2/orders/{broker_order_id}")
            logger.info("Alpaca order cancelled: %s", broker_order_id)
            return True
        except AlpacaApiError as exc:
            if exc.status_code == 422:
                logger.warning("Order %s already terminal — cannot cancel", broker_order_id)
                return False
            raise

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        """Fetch a single order by its Alpaca order ID."""
        data = await self._request("GET", f"/v2/orders/{broker_order_id}")
        return self._parse_order(data)

    async def get_orders(self, status: str = "open") -> list[BrokerOrder]:
        """List orders from Alpaca (open, closed, or all)."""
        data = await self._request("GET", "/v2/orders", params={"status": status})
        return [self._parse_order(o) for o in data]

    # -- positions -----------------------------------------------------------

    async def get_positions(self) -> list[BrokerPosition]:
        """Return all open positions from Alpaca."""
        data = await self._request("GET", "/v2/positions")
        return [self._parse_position(p) for p in data]

    async def get_position(self, symbol: str) -> BrokerPosition | None:
        """Return a single position by symbol, or None if not held."""
        try:
            data = await self._request("GET", f"/v2/positions/{symbol.upper()}")
            return self._parse_position(data)
        except AlpacaApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def close_position(self, symbol: str) -> bool:
        """Close an entire position for *symbol*."""
        try:
            await self._request("DELETE", f"/v2/positions/{symbol.upper()}")
            logger.info("Position closed: %s", symbol)
            return True
        except AlpacaApiError as exc:
            logger.error("Failed to close position %s: %s", symbol, exc)
            return False

    async def close_all_positions(self) -> bool:
        """
        Liquidate **all** open positions immediately (kill-switch).

        Returns True if the request was accepted.
        """
        try:
            await self._request("DELETE", "/v2/positions")
            logger.warning("KILL SWITCH: all positions liquidated")
            return True
        except AlpacaApiError as exc:
            logger.error("Kill switch failed: %s", exc)
            return False

    # -- portfolio history ---------------------------------------------------

    async def get_portfolio_history(
        self,
        period: str = "1M",
        timeframe: str = "1D",
    ) -> dict:
        """Fetch portfolio equity history from Alpaca."""
        data = await self._request(
            "GET",
            "/v2/account/portfolio/history",
            params={"period": period, "timeframe": timeframe},
        )
        return data


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (with possible trailing Z) to datetime."""
    if not value:
        return None
    try:
        # Alpaca uses RFC-3339 with fractional seconds and trailing Z
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
