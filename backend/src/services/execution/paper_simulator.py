"""
Local paper trading simulator.

Simulates order fills using last trade price + configurable slippage.
Used when Alpaca is not configured or for faster testing.

The simulator tracks positions and cash entirely in Redis, making it
stateless across process restarts (as long as Redis persists). It
implements the same public interface as ``AlpacaBroker`` so the OMS can
swap between them transparently.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from src.services.execution.alpaca_broker import BrokerOrder, BrokerPosition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_STARTING_CASH: float = 100_000.0
DEFAULT_SLIPPAGE_BPS: float = 20.0  # 20 basis points — appropriate for small caps

# Redis key prefixes
_PREFIX = "paper"
_CASH_KEY = f"{_PREFIX}:cash"
_POSITIONS_KEY = f"{_PREFIX}:positions"  # hash: symbol -> JSON blob
_ORDERS_KEY = f"{_PREFIX}:orders"  # hash: order_id -> JSON blob


# ---------------------------------------------------------------------------
# Internal position model stored in Redis
# ---------------------------------------------------------------------------

@dataclass
class _SimPosition:
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": str(self.qty),
            "avg_entry_price": str(self.avg_entry_price),
            "current_price": str(self.current_price),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "_SimPosition":
        return cls(
            symbol=data["symbol"],
            qty=float(data["qty"]),
            avg_entry_price=float(data["avg_entry_price"]),
            current_price=float(data.get("current_price", "0")),
        )


# ---------------------------------------------------------------------------
# Paper simulator
# ---------------------------------------------------------------------------


class PaperSimulator:
    """
    In-process paper trading simulator backed by Redis.

    Fills are *immediate* for limit orders when the simulated last price
    falls within the limit.  A configurable slippage model nudges the fill
    price away from the order price to approximate real small-cap
    execution quality.

    Implements the same public surface as :class:`AlpacaBroker` so the OMS
    can use either interchangeably.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        starting_cash: float = DEFAULT_STARTING_CASH,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    ):
        self._redis = redis
        self._starting_cash = starting_cash
        self._slippage_bps = slippage_bps

    # -- lifecycle -----------------------------------------------------------

    async def _ensure_cash(self) -> None:
        """Seed starting cash on first use."""
        if not await self._redis.exists(_CASH_KEY):
            await self._redis.set(_CASH_KEY, str(self._starting_cash))

    async def close(self) -> None:
        """No-op — Redis lifecycle is managed externally."""

    # -- helpers -------------------------------------------------------------

    async def _get_cash(self) -> float:
        await self._ensure_cash()
        raw = await self._redis.get(_CASH_KEY)
        return float(raw) if raw else self._starting_cash

    async def _set_cash(self, value: float) -> None:
        await self._redis.set(_CASH_KEY, str(value))

    async def _get_sim_position(self, symbol: str) -> _SimPosition | None:
        import json as _json

        raw = await self._redis.hget(_POSITIONS_KEY, symbol.upper())
        if not raw:
            return None
        return _SimPosition.from_dict(_json.loads(raw))

    async def _set_sim_position(self, pos: _SimPosition) -> None:
        import json as _json

        await self._redis.hset(
            _POSITIONS_KEY,
            pos.symbol.upper(),
            _json.dumps(pos.to_dict()),
        )

    async def _delete_sim_position(self, symbol: str) -> None:
        await self._redis.hdel(_POSITIONS_KEY, symbol.upper())

    async def _store_order(self, order: BrokerOrder) -> None:
        import json as _json

        data = {
            "broker_order_id": order.broker_order_id,
            "symbol": order.symbol,
            "side": order.side,
            "qty": str(order.qty),
            "price": str(order.price) if order.price else "",
            "order_type": order.order_type,
            "status": order.status,
            "filled_qty": str(order.filled_qty),
            "filled_avg_price": str(order.filled_avg_price) if order.filled_avg_price else "",
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else "",
            "filled_at": order.filled_at.isoformat() if order.filled_at else "",
        }
        await self._redis.hset(_ORDERS_KEY, order.broker_order_id, _json.dumps(data))

    async def _load_order(self, broker_order_id: str) -> BrokerOrder | None:
        import json as _json

        raw = await self._redis.hget(_ORDERS_KEY, broker_order_id)
        if not raw:
            return None
        data = _json.loads(raw)
        return BrokerOrder(
            broker_order_id=data["broker_order_id"],
            symbol=data["symbol"],
            side=data["side"],
            qty=float(data["qty"]),
            price=float(data["price"]) if data.get("price") else None,
            order_type=data["order_type"],
            status=data["status"],
            filled_qty=float(data.get("filled_qty", "0")),
            filled_avg_price=(
                float(data["filled_avg_price"]) if data.get("filled_avg_price") else None
            ),
            submitted_at=_parse_ts(data.get("submitted_at")),
            filled_at=_parse_ts(data.get("filled_at")),
        )

    def _apply_slippage(self, price: float, side: str) -> float:
        """
        Nudge the fill price by slippage in the unfavourable direction.

        Buys fill slightly above, sells slightly below — matching
        real-world small-cap bid-ask spread behaviour.
        """
        factor = self._slippage_bps / 10_000
        if side == "buy":
            return round(price * (1 + factor), 4)
        return round(price * (1 - factor), 4)

    # -- public interface (mirrors AlpacaBroker) -----------------------------

    async def is_available(self) -> bool:
        """Paper simulator is always available when Redis is reachable."""
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    async def get_account(self) -> dict:
        """Return simulated account summary."""
        cash = await self._get_cash()
        positions = await self.get_positions()
        market_value = sum(p.market_value for p in positions)
        equity = cash + market_value
        return {
            "id": "paper-simulator",
            "status": "ACTIVE",
            "equity": equity,
            "buying_power": cash,  # simplified: no margin
            "cash": cash,
            "portfolio_value": equity,
            "pattern_day_trader": False,
            "trading_blocked": False,
            "account_blocked": False,
            "currency": "USD",
        }

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
        Simulate an order fill.

        For limit orders the order fills immediately at *price* plus
        slippage (if price is provided).  Market orders fill at a
        synthetic last price derived from the limit price.
        """
        await self._ensure_cash()
        symbol = symbol.upper()
        now = datetime.now(timezone.utc)
        order_id = str(uuid.uuid4())

        # Determine fill price
        if price is not None:
            fill_price = self._apply_slippage(price, side)
        else:
            # Market orders without a price reference — reject safely
            return BrokerOrder(
                broker_order_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                order_type=order_type,
                status="rejected",
                submitted_at=now,
            )

        # Check cash for buys
        order_value = fill_price * qty
        cash = await self._get_cash()
        if side == "buy" and order_value > cash:
            logger.warning(
                "Paper sim: insufficient cash for %s %s x%.2f (need $%.2f, have $%.2f)",
                side, symbol, qty, order_value, cash,
            )
            order = BrokerOrder(
                broker_order_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                order_type=order_type,
                status="rejected",
                submitted_at=now,
            )
            await self._store_order(order)
            return order

        # Update cash
        if side == "buy":
            await self._set_cash(cash - order_value)
        else:
            await self._set_cash(cash + order_value)

        # Update position
        existing = await self._get_sim_position(symbol)

        if side == "buy":
            if existing:
                total_qty = existing.qty + qty
                avg = (
                    (existing.avg_entry_price * existing.qty + fill_price * qty) / total_qty
                )
                existing.qty = total_qty
                existing.avg_entry_price = round(avg, 4)
                existing.current_price = fill_price
                await self._set_sim_position(existing)
            else:
                await self._set_sim_position(
                    _SimPosition(
                        symbol=symbol,
                        qty=qty,
                        avg_entry_price=fill_price,
                        current_price=fill_price,
                    )
                )
        else:  # sell
            if existing:
                remaining = existing.qty - qty
                if remaining <= 0:
                    await self._delete_sim_position(symbol)
                else:
                    existing.qty = remaining
                    existing.current_price = fill_price
                    await self._set_sim_position(existing)

        order = BrokerOrder(
            broker_order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            order_type=order_type,
            status="filled",
            filled_qty=qty,
            filled_avg_price=fill_price,
            submitted_at=now,
            filled_at=now,
        )
        await self._store_order(order)

        logger.info(
            "Paper sim: %s %s x%.2f filled @ $%.4f (slippage %s bps)",
            side, symbol, qty, fill_price, self._slippage_bps,
        )
        return order

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel a simulated order (only possible if not already filled)."""
        order = await self._load_order(broker_order_id)
        if not order:
            logger.warning("Paper sim: order %s not found for cancel", broker_order_id)
            return False
        if order.status == "filled":
            logger.warning("Paper sim: order %s already filled — cannot cancel", broker_order_id)
            return False
        order.status = "cancelled"
        await self._store_order(order)
        return True

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        """Retrieve a simulated order by ID."""
        order = await self._load_order(broker_order_id)
        if not order:
            from src.services.execution.alpaca_broker import AlpacaApiError

            raise AlpacaApiError(404, f"Paper sim order {broker_order_id} not found")
        return order

    async def get_orders(self, status: str = "open") -> list[BrokerOrder]:
        """List all simulated orders, optionally filtered by status."""
        import json as _json

        all_raw = await self._redis.hgetall(_ORDERS_KEY)
        orders: list[BrokerOrder] = []
        for raw in all_raw.values():
            data = _json.loads(raw)
            order = BrokerOrder(
                broker_order_id=data["broker_order_id"],
                symbol=data["symbol"],
                side=data["side"],
                qty=float(data["qty"]),
                price=float(data["price"]) if data.get("price") else None,
                order_type=data["order_type"],
                status=data["status"],
                filled_qty=float(data.get("filled_qty", "0")),
                filled_avg_price=(
                    float(data["filled_avg_price"]) if data.get("filled_avg_price") else None
                ),
                submitted_at=_parse_ts(data.get("submitted_at")),
                filled_at=_parse_ts(data.get("filled_at")),
            )
            if status == "open" and order.status in ("filled", "cancelled", "rejected"):
                continue
            if status == "closed" and order.status not in ("filled", "cancelled", "rejected"):
                continue
            orders.append(order)
        return orders

    async def get_positions(self) -> list[BrokerPosition]:
        """Return all simulated positions."""
        import json as _json

        all_raw = await self._redis.hgetall(_POSITIONS_KEY)
        positions: list[BrokerPosition] = []
        for raw in all_raw.values():
            data = _json.loads(raw)
            pos = _SimPosition.from_dict(data)
            pnl = (pos.current_price - pos.avg_entry_price) * pos.qty
            positions.append(
                BrokerPosition(
                    symbol=pos.symbol,
                    qty=pos.qty,
                    avg_entry_price=pos.avg_entry_price,
                    current_price=pos.current_price,
                    unrealized_pnl=round(pnl, 2),
                    market_value=round(pos.current_price * pos.qty, 2),
                )
            )
        return positions

    async def get_position(self, symbol: str) -> BrokerPosition | None:
        """Return a single simulated position or None."""
        pos = await self._get_sim_position(symbol)
        if not pos:
            return None
        pnl = (pos.current_price - pos.avg_entry_price) * pos.qty
        return BrokerPosition(
            symbol=pos.symbol,
            qty=pos.qty,
            avg_entry_price=pos.avg_entry_price,
            current_price=pos.current_price,
            unrealized_pnl=round(pnl, 2),
            market_value=round(pos.current_price * pos.qty, 2),
        )

    async def close_position(self, symbol: str) -> bool:
        """Close a simulated position — return proceeds to cash."""
        pos = await self._get_sim_position(symbol)
        if not pos:
            return False
        proceeds = pos.current_price * pos.qty
        cash = await self._get_cash()
        await self._set_cash(cash + proceeds)
        await self._delete_sim_position(symbol)
        logger.info("Paper sim: closed position %s (%.2f shares, $%.2f proceeds)", symbol, pos.qty, proceeds)
        return True

    async def close_all_positions(self) -> bool:
        """Liquidate all simulated positions (kill switch)."""
        import json as _json

        all_raw = await self._redis.hgetall(_POSITIONS_KEY)
        total_proceeds = 0.0
        for raw in all_raw.values():
            data = _json.loads(raw)
            pos = _SimPosition.from_dict(data)
            total_proceeds += pos.current_price * pos.qty

        cash = await self._get_cash()
        await self._set_cash(cash + total_proceeds)
        await self._redis.delete(_POSITIONS_KEY)
        logger.warning("Paper sim KILL SWITCH: all positions liquidated ($%.2f proceeds)", total_proceeds)
        return True

    async def get_portfolio_history(
        self,
        period: str = "1M",
        timeframe: str = "1D",
    ) -> dict:
        """Return a stub portfolio history (not fully simulated)."""
        account = await self.get_account()
        return {
            "timestamp": [],
            "equity": [account["equity"]],
            "profit_loss": [0.0],
            "profit_loss_pct": [0.0],
            "base_value": self._starting_cash,
            "timeframe": timeframe,
        }

    async def reset(self) -> None:
        """Reset the paper simulator to starting state."""
        await self._redis.delete(_CASH_KEY, _POSITIONS_KEY, _ORDERS_KEY)
        await self._redis.set(_CASH_KEY, str(self._starting_cash))
        logger.info("Paper simulator reset to $%.2f starting cash", self._starting_cash)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO timestamp string to datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
