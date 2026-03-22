"""
Screener endpoints — preset screens for finding trading opportunities.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/screener", tags=["screener"])


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------
_PRESETS = {
    "distressed": {
        "name": "distressed",
        "label": "Distressed / Deep Value",
        "description": "Stocks trading near 52-week lows with improving fundamentals",
        "filters": {
            "price_vs_52w_low_pct": 15,
            "min_volume": 100_000,
            "positive_fcf": True,
        },
    },
    "squeeze": {
        "name": "squeeze",
        "label": "Volatility Squeeze",
        "description": "Bollinger Bands inside Keltner Channel — imminent breakout candidates",
        "filters": {
            "bb_inside_kc_days": 4,
            "min_volume": 200_000,
        },
    },
    "insider": {
        "name": "insider",
        "label": "Insider Buying",
        "description": "Cluster insider purchases in the last 30 days",
        "filters": {
            "insider_buys_30d": 2,
            "min_total_value": 50_000,
        },
    },
    "ai_opportunity": {
        "name": "ai_opportunity",
        "label": "AI Opportunity",
        "description": "AI composite scoring combining volume, technicals, filings, and sentiment",
        "filters": {
            "ai_score_min": 7.0,
            "confidence_min": 0.70,
        },
    },
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/presets")
async def list_presets():
    """List available preset screens."""
    return list(_PRESETS.values())


@router.get("/presets/{preset_name}")
async def run_preset(preset_name: str):
    """
    Run a preset screen and return matching tickers.

    In production this will query the database and run real-time calculations.
    """
    if preset_name not in _PRESETS:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_name}' not found")

    preset = _PRESETS[preset_name]

    # Placeholder results
    return {
        "preset": preset,
        "results": [
            {
                "symbol": "SYTA",
                "name": "Siyata Mobile",
                "score": 8.1,
                "market_cap": 15_000_000,
                "signal_count": 2,
                "latest_signal": "squeeze",
            },
        ],
        "total": 1,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "note": "Placeholder — will run real screener queries",
    }
