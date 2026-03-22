"""
Ticker endpoints — list and retrieve stock tickers.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from src.models.schemas import TickerResponse

router = APIRouter(prefix="/api/tickers", tags=["tickers"])

# ---------------------------------------------------------------------------
# Mock data (replaced by DB queries once connected)
# ---------------------------------------------------------------------------
_MOCK_TICKERS = [
    TickerResponse(
        id=1,
        symbol="NNOX",
        name="Nano-X Imaging",
        sector="Healthcare",
        industry="Medical Devices",
        market_cap=580_000_000,
        avg_volume=1_200_000,
        exchange="NASDAQ",
        is_otc=False,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    ),
    TickerResponse(
        id=2,
        symbol="HIMS",
        name="Hims & Hers Health",
        sector="Healthcare",
        industry="Specialty Pharmacy",
        market_cap=4_200_000_000,
        avg_volume=8_500_000,
        exchange="NYSE",
        is_otc=False,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    ),
    TickerResponse(
        id=3,
        symbol="SYTA",
        name="Siyata Mobile",
        sector="Technology",
        industry="Communication Equipment",
        market_cap=15_000_000,
        avg_volume=3_000_000,
        exchange="NASDAQ",
        is_otc=False,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    ),
]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[TickerResponse])
async def list_tickers(
    search: str | None = Query(default=None, description="Search by symbol or name"),
    sector: str | None = Query(default=None),
    min_cap: float | None = Query(default=None, description="Minimum market cap"),
    max_cap: float | None = Query(default=None, description="Maximum market cap"),
    is_active: bool | None = Query(default=None),
):
    """List tickers with optional filters."""
    results = _MOCK_TICKERS

    if search:
        q = search.upper()
        results = [t for t in results if q in t.symbol or q in t.name.upper()]
    if sector:
        results = [t for t in results if t.sector and t.sector.lower() == sector.lower()]
    if min_cap is not None:
        results = [t for t in results if t.market_cap and t.market_cap >= min_cap]
    if max_cap is not None:
        results = [t for t in results if t.market_cap and t.market_cap <= max_cap]
    if is_active is not None:
        results = [t for t in results if t.is_active == is_active]

    return results


@router.get("/{symbol}", response_model=TickerResponse)
async def get_ticker(symbol: str):
    """Get a single ticker by symbol."""
    symbol_upper = symbol.upper()
    for t in _MOCK_TICKERS:
        if t.symbol == symbol_upper:
            return t
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Ticker {symbol_upper} not found")
