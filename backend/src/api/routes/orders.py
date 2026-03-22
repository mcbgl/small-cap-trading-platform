"""
Order endpoints — create, list, get, and cancel orders.

Uses the Order Management System (OMS) for order creation, which enforces
risk checks, stop-loss requirements, approval gates, and audit logging.
Falls back to mock data when the DB pool is unavailable (dev/testing).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import (
    OrderCreate,
    OrderResponse,
    OrderSide,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orders", tags=["orders"])


# ---------------------------------------------------------------------------
# Helper: get OMS (or None when infra is unavailable)
# ---------------------------------------------------------------------------

async def _get_oms():
    """
    Try to build an OMS instance from the running DB pool and Redis.

    Returns ``None`` if the pool or Redis has not been initialised (e.g.
    during local dev without infrastructure).
    """
    try:
        from src.db import get_db_pool, get_redis
        from src.services.execution.oms import OrderManagementSystem

        db_pool = get_db_pool()
        redis = get_redis()

        # Decide which broker to use
        broker = await _get_broker(redis)

        return OrderManagementSystem(
            db_pool=db_pool,
            redis=redis,
            risk_engine=None,  # Plug in when risk module is ready
            broker=broker,
        )
    except RuntimeError:
        # Pool or Redis not initialised — fall back to mock mode
        logger.warning("DB pool or Redis not available — orders route in mock mode")
        return None


async def _get_broker(redis):
    """
    Return the appropriate broker instance.

    Prefers Alpaca when API keys are configured; falls back to the local
    paper simulator otherwise.
    """
    from src.config import settings

    if settings.alpaca_api_key and settings.alpaca_secret_key:
        from src.services.execution.alpaca_broker import AlpacaBroker

        broker = AlpacaBroker()
        if await broker.is_available():
            return broker
        logger.warning("Alpaca broker not reachable — falling back to paper simulator")

    from src.services.execution.paper_simulator import PaperSimulator

    return PaperSimulator(redis=redis)


# ---------------------------------------------------------------------------
# Mock fallback (used when DB/Redis unavailable)
# ---------------------------------------------------------------------------

_MOCK_ORDERS: list[OrderResponse] = [
    OrderResponse(
        id=1,
        ticker_id=1,
        symbol="NNOX",
        side=OrderSide.BUY,
        qty=100,
        price=12.50,
        order_type=OrderType.LIMIT,
        status=OrderStatus.FILLED,
        stop_loss=11.50,
        paper_mode=True,
        filled_qty=100,
        filled_avg_price=12.48,
        submitted_at=datetime.now(timezone.utc),
        filled_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    ),
]
_next_id = 2


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    status: OrderStatus | None = Query(default=None),
    ticker: str | None = Query(default=None, description="Filter by ticker symbol"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    List orders with optional filters.

    Falls back to in-memory mock data when the database is not available.
    """
    oms = await _get_oms()

    if oms is not None:
        try:
            return await oms.get_orders(
                status=status.value if status else None,
                ticker=ticker,
                limit=limit,
            )
        except Exception as exc:
            logger.error("Failed to query orders from DB: %s", exc)
            # Fall through to mock

    # Mock fallback
    results = list(_MOCK_ORDERS)
    if status:
        results = [o for o in results if o.status == status]
    if ticker:
        results = [o for o in results if o.symbol and o.symbol.upper() == ticker.upper()]
    return results[:limit]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int):
    """Retrieve a single order by ID."""
    oms = await _get_oms()

    if oms is not None:
        try:
            order = await oms.get_order(order_id)
            if order is None:
                raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
            return order
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to fetch order %d from DB: %s", order_id, exc)
            # Fall through to mock

    # Mock fallback
    for o in _MOCK_ORDERS:
        if o.id == order_id:
            return o
    raise HTTPException(status_code=404, detail=f"Order {order_id} not found")


@router.post("/", response_model=OrderResponse, status_code=201)
async def create_order(order: OrderCreate):
    """
    Create a new order via the Order Management System.

    The OMS enforces:
    - Stop-loss requirement (Tier 1 hardcoded)
    - Limit-orders-only mode
    - Risk pre-trade checks
    - Human approval gate (above $5,000 default)
    - Shadow mode (log only, no broker submission)
    - Full audit logging
    """
    oms = await _get_oms()

    if oms is not None:
        try:
            from src.services.execution.oms import OrderResult

            result: OrderResult = await oms.submit_order(order, source="api")

            if result.order_id is None:
                # Order was rejected before DB insertion
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": result.message,
                        "warnings": result.warnings,
                        "risk_checks_passed": result.risk_checks_passed,
                    },
                )

            # Fetch the full order from DB to return a consistent response
            db_order = await oms.get_order(result.order_id)
            if db_order is None:
                raise HTTPException(
                    status_code=500,
                    detail="Order created but could not be retrieved",
                )
            return db_order

        except HTTPException:
            raise
        except Exception as exc:
            logger.error("OMS submit_order failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Order submission failed: {exc}",
            )

    # Mock fallback
    global _next_id
    new_order = OrderResponse(
        id=_next_id,
        ticker_id=order.ticker_id,
        side=order.side,
        qty=order.qty,
        price=order.price,
        order_type=order.order_type,
        status=OrderStatus.CREATED,
        stop_loss=order.stop_loss,
        paper_mode=True,
        created_at=datetime.now(timezone.utc),
    )
    _MOCK_ORDERS.append(new_order)
    _next_id += 1
    logger.info("Mock order created: id=%d (DB unavailable)", new_order.id)
    return new_order


@router.delete("/{order_id}", status_code=204)
async def cancel_order(order_id: int):
    """Cancel a pending or submitted order."""
    oms = await _get_oms()

    if oms is not None:
        try:
            await oms.cancel_order(order_id)
            return
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("OMS cancel_order failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Cancel failed: {exc}")

    # Mock fallback
    for o in _MOCK_ORDERS:
        if o.id == order_id:
            if o.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot cancel order in {o.status} status",
                )
            o.status = OrderStatus.CANCELLED
            return
    raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
