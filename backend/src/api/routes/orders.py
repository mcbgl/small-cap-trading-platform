"""
Order endpoints — create, list, and cancel orders.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import OrderCreate, OrderResponse, OrderSide, OrderStatus, OrderType

router = APIRouter(prefix="/api/orders", tags=["orders"])

# ---------------------------------------------------------------------------
# Mock data
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
):
    """List orders with optional filters."""
    results = _MOCK_ORDERS

    if status:
        results = [o for o in results if o.status == status]
    if ticker:
        results = [o for o in results if o.symbol and o.symbol.upper() == ticker.upper()]

    return results


@router.post("/", response_model=OrderResponse, status_code=201)
async def create_order(order: OrderCreate):
    """
    Create a new order. In production this will run through:
    1. Risk pre-check (position limits, drawdown, stop-loss validation)
    2. AI confidence gate
    3. Human approval gate (if above threshold)
    4. Broker submission
    """
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
    return new_order


@router.delete("/{order_id}", status_code=204)
async def cancel_order(order_id: int):
    """Cancel a pending order."""
    for o in _MOCK_ORDERS:
        if o.id == order_id:
            if o.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
                raise HTTPException(
                    status_code=400, detail=f"Cannot cancel order in {o.status} status"
                )
            o.status = OrderStatus.CANCELLED
            return
    raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
