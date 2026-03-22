"""
Signal endpoints — list and retrieve trading signals.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from src.models.schemas import SignalResponse, SignalType

router = APIRouter(prefix="/api/signals", tags=["signals"])

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------
_MOCK_SIGNALS = [
    SignalResponse(
        id=1,
        ticker_id=1,
        symbol="NNOX",
        signal_type=SignalType.VOLUME,
        score=7.5,
        confidence=0.82,
        model="volume_scanner_v1",
        reasoning="Volume spike 3.2x above 20-day average on no news",
        created_at=datetime.now(timezone.utc),
    ),
    SignalResponse(
        id=2,
        ticker_id=3,
        symbol="SYTA",
        signal_type=SignalType.SQUEEZE,
        score=8.1,
        confidence=0.75,
        model="squeeze_detector_v1",
        reasoning="Bollinger Bands inside Keltner Channel for 6 consecutive days",
        created_at=datetime.now(timezone.utc),
    ),
    SignalResponse(
        id=3,
        ticker_id=2,
        symbol="HIMS",
        signal_type=SignalType.AI_COMPOSITE,
        score=6.8,
        confidence=0.71,
        model="claude-opus-4-6",
        reasoning="Positive sentiment from recent 10-Q, revenue growth +23% YoY",
        created_at=datetime.now(timezone.utc),
    ),
]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[SignalResponse])
async def list_signals(
    ticker: str | None = Query(default=None, description="Filter by ticker symbol"),
    signal_type: SignalType | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=10.0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List signals with optional filters."""
    results = _MOCK_SIGNALS

    if ticker:
        results = [s for s in results if s.symbol and s.symbol.upper() == ticker.upper()]
    if signal_type:
        results = [s for s in results if s.signal_type == signal_type]
    if min_score is not None:
        results = [s for s in results if s.score >= min_score]

    return results[:limit]


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: int):
    """Get a single signal by ID."""
    for s in _MOCK_SIGNALS:
        if s.id == signal_id:
            return s
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
