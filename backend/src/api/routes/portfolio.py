"""
Portfolio endpoints — summary, positions, and value history.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from src.models.schemas import PositionResponse

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------
_MOCK_POSITIONS = [
    PositionResponse(
        id=1,
        ticker_id=1,
        symbol="NNOX",
        side="long",
        qty=100,
        avg_entry_price=12.48,
        current_price=13.20,
        unrealized_pnl=72.00,
        stop_loss=11.50,
        trailing_stop_pct=5.0,
        opened_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ),
]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary")
async def portfolio_summary():
    """Portfolio overview: total value, P&L, cash, position count."""
    return {
        "total_value": 102_500.00,
        "cash": 101_180.00,
        "positions_value": 1_320.00,
        "unrealized_pnl": 72.00,
        "realized_pnl": 0.00,
        "daily_pnl": 72.00,
        "positions_count": len(_MOCK_POSITIONS),
        "paper_mode": True,
        "shadow_mode": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions():
    """All open positions with current prices."""
    return _MOCK_POSITIONS


@router.get("/history")
async def portfolio_history():
    """Portfolio value time series (placeholder — will be powered by QuestDB)."""
    now = datetime.now(timezone.utc)
    return {
        "period": "1W",
        "data_points": [
            {"timestamp": now.isoformat(), "value": 100_000},
            {"timestamp": now.isoformat(), "value": 100_250},
            {"timestamp": now.isoformat(), "value": 101_100},
            {"timestamp": now.isoformat(), "value": 100_800},
            {"timestamp": now.isoformat(), "value": 102_500},
        ],
        "note": "Placeholder — will be replaced with QuestDB time-series data",
    }
