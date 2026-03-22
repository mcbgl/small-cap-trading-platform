"""
Order Management System (OMS).

Manages the full order lifecycle: creation -> risk check -> approval gate ->
broker submission -> fill tracking -> position update -> audit logging.

Every order must pass through risk checks before submission. The OMS enforces
stop-loss requirements, human approval thresholds, and shadow mode.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import asyncpg
import redis.asyncio as aioredis

from src.config import HardcodedLimits, settings
from src.models.schemas import OrderCreate, OrderResponse, OrderStatus, OrderType
from src.services.execution.alpaca_broker import BrokerOrder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocols — allow duck-typed broker and risk engine dependencies
# ---------------------------------------------------------------------------


class BrokerProtocol(Protocol):
    """Minimal broker interface consumed by the OMS."""

    async def submit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float | None,
        order_type: str,
        time_in_force: str,
        stop_loss: float | None,
    ) -> BrokerOrder: ...

    async def cancel_order(self, broker_order_id: str) -> bool: ...
    async def get_order(self, broker_order_id: str) -> BrokerOrder: ...
    async def get_positions(self) -> list: ...


class RiskEngineProtocol(Protocol):
    """Minimal risk engine interface consumed by the OMS."""

    async def pre_trade_check(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        stop_loss: float | None,
    ) -> "RiskCheckResult": ...


@dataclass
class RiskCheckResult:
    """Result returned by the risk engine's pre-trade check."""

    passed: bool
    warnings: list[str] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# Order result
# ---------------------------------------------------------------------------


@dataclass
class OrderResult:
    """Returned to the caller after ``submit_order``."""

    order_id: int | None
    status: str
    message: str
    warnings: list[str] = field(default_factory=list)
    risk_checks_passed: bool = True
    requires_approval: bool = False
    shadow_mode: bool = False
    broker_order_id: str | None = None


# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.RISK_CHECKED, OrderStatus.REJECTED},
    OrderStatus.RISK_CHECKED: {OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.SUBMITTED: {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    # Terminal states — no further transitions
    OrderStatus.FILLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.CANCELLED: set(),
}


# ---------------------------------------------------------------------------
# OMS
# ---------------------------------------------------------------------------


class OrderManagementSystem:
    """
    Central order lifecycle manager.

    The OMS coordinates validation, risk checks, approval gates, broker
    submission, and audit logging for every order that enters the system.
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        redis: aioredis.Redis,
        risk_engine: RiskEngineProtocol | None = None,
        broker: BrokerProtocol | None = None,
    ):
        self._db = db_pool
        self._redis = redis
        self._risk = risk_engine
        self._broker = broker

    # -- public API ----------------------------------------------------------

    async def submit_order(
        self,
        order: OrderCreate,
        source: str = "manual",
        ai_context: dict | None = None,
    ) -> OrderResult:
        """
        Full order lifecycle:

        1. Validate basic params
        2. Enforce stop-loss requirement
        3. Enforce limit-orders-only
        4. Run risk pre-checks
        5. Check human approval gate
        6. Shadow mode guard
        7. Submit to broker
        8. Store in DB
        9. Audit log
        10. Return result
        """
        warnings: list[str] = []

        # ---- 1. Basic validation -------------------------------------------
        if order.qty <= 0:
            return OrderResult(
                order_id=None,
                status="rejected",
                message="Quantity must be positive",
                risk_checks_passed=False,
            )

        if order.price is not None and order.price <= 0:
            return OrderResult(
                order_id=None,
                status="rejected",
                message="Price must be positive",
                risk_checks_passed=False,
            )

        # Resolve symbol from ticker_id
        symbol = await self._resolve_symbol(order.ticker_id)
        if not symbol:
            return OrderResult(
                order_id=None,
                status="rejected",
                message=f"Ticker ID {order.ticker_id} not found",
                risk_checks_passed=False,
            )

        # ---- 2. Enforce stop-loss requirement (Tier 1) ---------------------
        if HardcodedLimits.STOP_LOSS_REQUIRED and order.stop_loss is None:
            return OrderResult(
                order_id=None,
                status="rejected",
                message="Stop-loss is required on every order (STOP_LOSS_REQUIRED=True)",
                risk_checks_passed=False,
            )

        # ---- 3. Enforce limit-orders-only ----------------------------------
        if settings.limit_orders_only and order.order_type != OrderType.LIMIT:
            return OrderResult(
                order_id=None,
                status="rejected",
                message=f"Only limit orders allowed (got {order.order_type}); "
                        "set LIMIT_ORDERS_ONLY=false to allow other types",
                risk_checks_passed=False,
            )

        # Must have a price for limit orders
        if order.order_type == OrderType.LIMIT and order.price is None:
            return OrderResult(
                order_id=None,
                status="rejected",
                message="Limit orders require a price",
                risk_checks_passed=False,
            )

        # ---- Compute order value -------------------------------------------
        effective_price = order.price or 0.0
        order_value = effective_price * order.qty

        # Enforce absolute max order value (Tier 1)
        if order_value > HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE:
            return OrderResult(
                order_id=None,
                status="rejected",
                message=f"Order value ${order_value:,.2f} exceeds absolute maximum "
                        f"${HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE:,.2f}",
                risk_checks_passed=False,
            )

        # ---- 4. Risk pre-checks -------------------------------------------
        risk_passed = True
        if self._risk:
            try:
                risk_result = await self._risk.pre_trade_check(
                    symbol=symbol,
                    side=order.side,
                    qty=order.qty,
                    price=effective_price,
                    stop_loss=order.stop_loss,
                )
                risk_passed = risk_result.passed
                warnings.extend(risk_result.warnings)
                if not risk_passed:
                    return OrderResult(
                        order_id=None,
                        status="rejected",
                        message=f"Risk check failed: {risk_result.reason}",
                        warnings=warnings,
                        risk_checks_passed=False,
                    )
            except Exception as exc:
                logger.error("Risk engine error (failing safe — rejecting): %s", exc)
                return OrderResult(
                    order_id=None,
                    status="rejected",
                    message=f"Risk engine error: {exc}",
                    risk_checks_passed=False,
                )
        else:
            warnings.append("No risk engine configured — skipping pre-trade checks")

        # ---- 5. Human approval gate ----------------------------------------
        requires_approval = self._check_approval_required(order_value)
        if requires_approval:
            order_id = await self._insert_order(
                order, symbol, status=OrderStatus.RISK_CHECKED,
                broker_name=self._broker_name(),
            )
            await self._log_audit(
                action="order_pending_approval",
                order_id=order_id,
                ai_context=ai_context,
                decision=f"queued for approval (value=${order_value:,.2f})",
                source=source,
            )
            return OrderResult(
                order_id=order_id,
                status="risk_checked",
                message=f"Order queued for human approval (value ${order_value:,.2f} > "
                        f"threshold ${settings.human_approval_above_usd:,.2f})",
                warnings=warnings,
                risk_checks_passed=True,
                requires_approval=True,
            )

        # ---- 6. Shadow mode ------------------------------------------------
        if settings.shadow_mode:
            order_id = await self._insert_order(
                order, symbol, status=OrderStatus.FILLED,
                broker_name="shadow",
                filled_qty=order.qty,
                filled_avg_price=effective_price,
            )
            await self._log_audit(
                action="order_shadow_filled",
                order_id=order_id,
                ai_context=ai_context,
                decision="shadow_filled",
                source=source,
            )
            return OrderResult(
                order_id=order_id,
                status="filled",
                message="Shadow mode — order logged but not submitted to broker",
                warnings=warnings,
                risk_checks_passed=True,
                shadow_mode=True,
            )

        # ---- 7. Submit to broker -------------------------------------------
        if not self._broker:
            return OrderResult(
                order_id=None,
                status="rejected",
                message="No broker configured and shadow_mode is off",
                warnings=warnings,
                risk_checks_passed=True,
            )

        try:
            broker_order = await self._broker.submit_order(
                symbol=symbol,
                side=order.side,
                qty=order.qty,
                price=order.price,
                order_type=order.order_type,
                time_in_force="day",
                stop_loss=order.stop_loss,
            )
        except Exception as exc:
            logger.error("Broker submission failed: %s", exc)
            order_id = await self._insert_order(
                order, symbol, status=OrderStatus.REJECTED,
                broker_name=self._broker_name(),
            )
            await self._log_audit(
                action="order_broker_rejected",
                order_id=order_id,
                ai_context=ai_context,
                decision=f"broker_error: {exc}",
                source=source,
            )
            return OrderResult(
                order_id=order_id,
                status="rejected",
                message=f"Broker submission failed: {exc}",
                warnings=warnings,
                risk_checks_passed=True,
            )

        # ---- 8. Store order in DB ------------------------------------------
        db_status = _map_broker_status(broker_order.status)
        order_id = await self._insert_order(
            order,
            symbol,
            status=db_status,
            broker_name=self._broker_name(),
            broker_order_id=broker_order.broker_order_id,
            filled_qty=broker_order.filled_qty,
            filled_avg_price=broker_order.filled_avg_price,
        )

        # ---- 9. Audit log --------------------------------------------------
        await self._log_audit(
            action="order_submitted",
            order_id=order_id,
            ai_context=ai_context,
            decision=f"submitted to {self._broker_name()} "
                     f"(broker_id={broker_order.broker_order_id})",
            source=source,
        )

        # ---- 10. Return result ---------------------------------------------
        return OrderResult(
            order_id=order_id,
            status=broker_order.status,
            message=f"Order submitted to {self._broker_name()}",
            warnings=warnings,
            risk_checks_passed=True,
            broker_order_id=broker_order.broker_order_id,
        )

    async def cancel_order(self, order_id: int) -> bool:
        """Cancel an order via the broker and update the DB."""
        row = await self._db.fetchrow(
            "SELECT id, status, broker_order_id, broker FROM orders WHERE id = $1",
            order_id,
        )
        if not row:
            raise ValueError(f"Order {order_id} not found")

        current_status = OrderStatus(row["status"])
        if current_status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            raise ValueError(f"Cannot cancel order in {current_status} status")

        # Cancel at broker if we have a broker order ID
        broker_order_id = row["broker_order_id"]
        if broker_order_id and self._broker:
            try:
                cancelled = await self._broker.cancel_order(broker_order_id)
                if not cancelled:
                    logger.warning("Broker did not confirm cancel for %s", broker_order_id)
            except Exception as exc:
                logger.error("Broker cancel failed for %s: %s", broker_order_id, exc)

        await self.update_order_status(order_id, OrderStatus.CANCELLED)
        await self._log_audit(
            action="order_cancelled",
            order_id=order_id,
            decision="cancelled by user",
        )
        return True

    async def get_order(self, order_id: int) -> OrderResponse | None:
        """Fetch a single order from the DB."""
        row = await self._db.fetchrow(
            """
            SELECT o.*, t.symbol
            FROM orders o
            LEFT JOIN tickers t ON t.id = o.ticker_id
            WHERE o.id = $1
            """,
            order_id,
        )
        if not row:
            return None
        return _row_to_order_response(row)

    async def get_orders(
        self,
        status: str | None = None,
        ticker: str | None = None,
        limit: int = 50,
    ) -> list[OrderResponse]:
        """Fetch orders from the DB with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        idx = 1

        if status:
            clauses.append(f"o.status = ${idx}")
            params.append(status)
            idx += 1

        if ticker:
            clauses.append(f"UPPER(t.symbol) = ${idx}")
            params.append(ticker.upper())
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        clauses_limit = f"LIMIT ${idx}"
        params.append(limit)

        query = f"""
            SELECT o.*, t.symbol
            FROM orders o
            LEFT JOIN tickers t ON t.id = o.ticker_id
            {where}
            ORDER BY o.created_at DESC
            {clauses_limit}
        """
        rows = await self._db.fetch(query, *params)
        return [_row_to_order_response(r) for r in rows]

    async def update_order_status(
        self,
        order_id: int,
        new_status: OrderStatus,
        fill_data: dict | None = None,
    ) -> None:
        """
        Transition an order to a new status with validation.

        Raises ``ValueError`` on invalid transitions.
        """
        row = await self._db.fetchrow(
            "SELECT status FROM orders WHERE id = $1", order_id,
        )
        if not row:
            raise ValueError(f"Order {order_id} not found")

        current = OrderStatus(row["status"])
        allowed = _VALID_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {current} -> {new_status} "
                f"(allowed: {allowed or 'none — terminal state'})"
            )

        now = datetime.now(timezone.utc)
        updates = ["status = $2", "updated_at = $3"]
        params: list[Any] = [order_id, new_status.value, now]
        idx = 4

        if fill_data:
            if "filled_qty" in fill_data:
                updates.append(f"filled_qty = ${idx}")
                params.append(fill_data["filled_qty"])
                idx += 1
            if "filled_avg_price" in fill_data:
                updates.append(f"filled_avg_price = ${idx}")
                params.append(fill_data["filled_avg_price"])
                idx += 1
            if new_status == OrderStatus.FILLED:
                updates.append(f"filled_at = ${idx}")
                params.append(now)
                idx += 1

        if new_status == OrderStatus.SUBMITTED:
            updates.append(f"submitted_at = ${idx}")
            params.append(now)
            idx += 1

        set_clause = ", ".join(updates)
        await self._db.execute(
            f"UPDATE orders SET {set_clause} WHERE id = $1", *params,
        )
        logger.info("Order %d: %s -> %s", order_id, current, new_status)

    async def reconcile_positions(self) -> dict:
        """
        Compare DB positions with broker positions and report discrepancies.

        Returns a summary dict with ``matched``, ``db_only``, and
        ``broker_only`` counts and details.
        """
        if not self._broker:
            return {"error": "No broker configured"}

        broker_positions = await self._broker.get_positions()
        broker_by_symbol: dict[str, Any] = {p.symbol: p for p in broker_positions}

        db_rows = await self._db.fetch(
            """
            SELECT p.*, t.symbol
            FROM positions p
            JOIN tickers t ON t.id = p.ticker_id
            """
        )
        db_by_symbol: dict[str, asyncpg.Record] = {r["symbol"]: r for r in db_rows}

        matched: list[dict] = []
        discrepancies: list[dict] = []
        db_only: list[str] = []
        broker_only: list[str] = []

        all_symbols = set(broker_by_symbol.keys()) | set(db_by_symbol.keys())

        for sym in all_symbols:
            in_broker = sym in broker_by_symbol
            in_db = sym in db_by_symbol

            if in_broker and in_db:
                bp = broker_by_symbol[sym]
                dr = db_by_symbol[sym]
                if abs(bp.qty - float(dr["qty"])) < 0.01:
                    matched.append({"symbol": sym, "qty": bp.qty})
                else:
                    discrepancies.append({
                        "symbol": sym,
                        "broker_qty": bp.qty,
                        "db_qty": float(dr["qty"]),
                    })
            elif in_broker:
                broker_only.append(sym)
            else:
                db_only.append(sym)

        summary = {
            "matched": len(matched),
            "discrepancies": discrepancies,
            "db_only": db_only,
            "broker_only": broker_only,
            "total_broker": len(broker_positions),
            "total_db": len(db_rows),
        }

        if discrepancies or db_only or broker_only:
            logger.warning("Position reconciliation found issues: %s", summary)
        else:
            logger.info("Position reconciliation clean: %d matched", len(matched))

        return summary

    # -- private helpers -----------------------------------------------------

    def _check_approval_required(self, order_value: float) -> bool:
        """Return True if the order value exceeds the human approval threshold."""
        return order_value > settings.human_approval_above_usd

    def _broker_name(self) -> str:
        """Friendly name of the configured broker."""
        if self._broker is None:
            return "none"
        cls_name = type(self._broker).__name__
        if "Alpaca" in cls_name:
            return "alpaca_paper" if settings.paper_mode else "alpaca_live"
        if "Paper" in cls_name or "Simulator" in cls_name:
            return "paper_simulator"
        return cls_name.lower()

    async def _resolve_symbol(self, ticker_id: int) -> str | None:
        """Look up the symbol for a ticker ID."""
        row = await self._db.fetchrow(
            "SELECT symbol FROM tickers WHERE id = $1", ticker_id,
        )
        return row["symbol"] if row else None

    async def _insert_order(
        self,
        order: OrderCreate,
        symbol: str,
        *,
        status: OrderStatus,
        broker_name: str = "none",
        broker_order_id: str | None = None,
        filled_qty: float = 0.0,
        filled_avg_price: float | None = None,
    ) -> int:
        """Insert a new order row and return its ID."""
        now = datetime.now(timezone.utc)
        row = await self._db.fetchrow(
            """
            INSERT INTO orders (
                ticker_id, side, qty, price, order_type, status, stop_loss,
                broker, broker_order_id, paper_mode,
                filled_qty, filled_avg_price,
                submitted_at, filled_at, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10,
                $11, $12,
                $13, $14, $15, $15
            )
            RETURNING id
            """,
            order.ticker_id,
            order.side.value,
            order.qty,
            order.price,
            order.order_type.value,
            status.value,
            order.stop_loss,
            broker_name,
            broker_order_id,
            settings.paper_mode,
            filled_qty,
            filled_avg_price,
            now if status in (OrderStatus.SUBMITTED, OrderStatus.FILLED) else None,
            now if status == OrderStatus.FILLED else None,
            now,
        )
        return row["id"]

    async def _log_audit(
        self,
        action: str,
        order_id: int | None = None,
        ai_context: dict | None = None,
        decision: str = "",
        source: str = "system",
    ) -> None:
        """Write an entry to the audit_log table."""
        if not HardcodedLimits.AUDIT_LOGGING_ALWAYS_ON:
            return

        input_snapshot = {
            "source": source,
            **(ai_context or {}),
        }
        input_json = json.dumps(input_snapshot, default=str)
        prompt_hash = hashlib.sha256(input_json.encode()).hexdigest()[:16]
        model_id = (ai_context or {}).get("model", None)

        try:
            await self._db.execute(
                """
                INSERT INTO audit_log (
                    action, model_id, prompt_hash, input_snapshot,
                    output, decision, human_override, order_id, created_at
                ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8, $9)
                """,
                action,
                model_id,
                prompt_hash,
                input_json,
                json.dumps({"decision": decision}, default=str),
                decision,
                False,
                order_id,
                datetime.now(timezone.utc),
            )
        except Exception as exc:
            # Audit logging must never block the order flow
            logger.error("Failed to write audit log: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _map_broker_status(broker_status: str) -> OrderStatus:
    """Map a broker status string to our OrderStatus enum."""
    mapping = {
        "submitted": OrderStatus.SUBMITTED,
        "filled": OrderStatus.FILLED,
        "cancelled": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
    }
    return mapping.get(broker_status, OrderStatus.SUBMITTED)


def _row_to_order_response(row: asyncpg.Record) -> OrderResponse:
    """Convert a DB row (with joined symbol) to an OrderResponse."""
    return OrderResponse(
        id=row["id"],
        ticker_id=row["ticker_id"],
        symbol=row.get("symbol"),
        side=row["side"],
        qty=float(row["qty"]),
        price=float(row["price"]) if row["price"] is not None else None,
        order_type=row["order_type"],
        status=row["status"],
        stop_loss=float(row["stop_loss"]) if row["stop_loss"] is not None else None,
        broker=row.get("broker"),
        broker_order_id=row.get("broker_order_id"),
        paper_mode=row.get("paper_mode", True),
        filled_qty=float(row.get("filled_qty") or 0),
        filled_avg_price=(
            float(row["filled_avg_price"]) if row.get("filled_avg_price") is not None else None
        ),
        submitted_at=row.get("submitted_at"),
        filled_at=row.get("filled_at"),
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
    )
