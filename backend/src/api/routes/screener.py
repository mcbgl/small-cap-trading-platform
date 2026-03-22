"""
Screener endpoints -- preset screens for finding trading opportunities.

Provides four preset screeners (distressed, squeeze, insider, ai_opportunity)
plus a custom filter endpoint and an overview endpoint for dashboard badges.
"""

import logging
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screener", tags=["screener"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_screener_service():
    """
    Instantiate a ScreenerService using the live database pool.

    Returns (service, None) on success, or (None, error_message) on failure.
    """
    try:
        from src.db import get_db_pool, get_redis
        from src.services.screener.presets import ScreenerService

        pool = get_db_pool()
        try:
            redis = get_redis()
        except RuntimeError:
            redis = None

        return ScreenerService(db_pool=pool, redis=redis), None
    except RuntimeError as exc:
        return None, str(exc)


def _screener_result_to_dict(result) -> dict:
    """Convert a ScreenerResult dataclass to a JSON-serialisable dict."""
    d = asdict(result)
    # Convert InsightCard (Pydantic model) if present
    if result.ai_insight is not None:
        d["ai_insight"] = result.ai_insight.model_dump()
    return d


def _screener_response_to_dict(response) -> dict:
    """Convert a ScreenerResponse dataclass to a JSON-serialisable dict."""
    return {
        "preset_name": response.preset_name,
        "results": [_screener_result_to_dict(r) for r in response.results],
        "total": response.total,
        "limit": response.limit,
        "offset": response.offset,
        "executed_at": response.executed_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /presets — list available presets
# ---------------------------------------------------------------------------

@router.get("/presets")
async def list_presets():
    """
    List all available screener presets with their descriptions.

    Returns a list of preset definitions (name, label, description, icon).
    No database access required.
    """
    from src.services.screener.presets import ScreenerService

    return ScreenerService.get_available_presets()


# ---------------------------------------------------------------------------
# GET /presets/{preset_name} — run a preset screen
# ---------------------------------------------------------------------------

@router.get("/presets/{preset_name}")
async def run_preset(
    preset_name: str,
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    sort_by: str = Query(
        default="score",
        description="Sort field: score, market_cap, signal_count, symbol",
    ),
):
    """
    Run a named preset screen and return matching tickers.

    Supported presets: distressed, squeeze, insider, ai_opportunity.
    Returns enriched results with signal data, metadata, and optional AI insights.
    """
    service, error = _get_screener_service()
    if service is None:
        return {
            "preset_name": preset_name,
            "results": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "message": f"Database not available: {error}",
        }

    try:
        response = await service.run_preset(
            preset_name=preset_name,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
        )
        return _screener_response_to_dict(response)

    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Screener preset '%s' failed", preset_name)
        raise HTTPException(
            status_code=500,
            detail=f"Screener preset '{preset_name}' encountered an error",
        )


# ---------------------------------------------------------------------------
# GET /custom — custom screen with manual filters
# ---------------------------------------------------------------------------

@router.get("/custom")
async def custom_screen(
    min_market_cap: float | None = Query(
        default=None, ge=0, description="Minimum market cap"
    ),
    max_market_cap: float | None = Query(
        default=None, ge=0, description="Maximum market cap"
    ),
    min_volume: int | None = Query(
        default=None, ge=0, description="Minimum average volume"
    ),
    sector: str | None = Query(default=None, description="Sector filter"),
    min_signal_score: float | None = Query(
        default=None, ge=0.0, le=10.0, description="Minimum signal score"
    ),
    signal_types: str | None = Query(
        default=None, description="Comma-separated signal types (e.g. squeeze,volume)"
    ),
    has_insider_buying: bool | None = Query(
        default=None, description="Filter for tickers with recent insider buying"
    ),
    has_filing_keywords: bool | None = Query(
        default=None, description="Filter for tickers with distress filing keywords"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    Custom screener with dynamic filters.

    Build a screen by combining market cap, volume, sector, signal score,
    signal type, insider buying, and filing keyword filters.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        return {
            "preset_name": "custom",
            "results": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "message": "Database not available",
        }

    try:
        # Build dynamic WHERE conditions
        conditions: list[str] = ["t.is_active = true"]
        params: list = []
        idx = 1

        if min_market_cap is not None:
            conditions.append(f"t.market_cap >= ${idx}")
            params.append(min_market_cap)
            idx += 1

        if max_market_cap is not None:
            conditions.append(f"t.market_cap <= ${idx}")
            params.append(max_market_cap)
            idx += 1

        if min_volume is not None:
            conditions.append(f"t.avg_volume >= ${idx}")
            params.append(min_volume)
            idx += 1

        if sector is not None:
            conditions.append(f"LOWER(t.sector) = LOWER(${idx})")
            params.append(sector)
            idx += 1

        # Signal-based joins
        signal_join = ""
        signal_conditions: list[str] = []

        if min_signal_score is not None or signal_types is not None:
            signal_join = """
                JOIN LATERAL (
                    SELECT s.score, s.signal_type, s.confidence, s.reasoning,
                           s.created_at
                    FROM signals s
                    WHERE s.symbol = t.symbol
                      AND s.created_at >= NOW() - INTERVAL '30 days'
                    ORDER BY s.score DESC
                    LIMIT 1
                ) latest_signal ON true
            """
            if min_signal_score is not None:
                signal_conditions.append(f"latest_signal.score >= ${idx}")
                params.append(min_signal_score)
                idx += 1

            if signal_types is not None:
                type_list = [st.strip() for st in signal_types.split(",") if st.strip()]
                if type_list:
                    placeholders = ", ".join(f"${idx + i}" for i in range(len(type_list)))
                    signal_conditions.append(
                        f"latest_signal.signal_type IN ({placeholders})"
                    )
                    params.extend(type_list)
                    idx += len(type_list)

        # Insider buying subquery
        insider_join = ""
        if has_insider_buying:
            insider_join = """
                JOIN (
                    SELECT DISTINCT it2.ticker_id
                    FROM insider_transactions it2
                    WHERE it2.transaction_type = 'P'
                      AND it2.transaction_date >= (NOW() - INTERVAL '30 days')::date
                ) ib ON ib.ticker_id = t.id
            """

        # Filing keywords subquery
        filing_join = ""
        if has_filing_keywords:
            filing_join = """
                JOIN (
                    SELECT DISTINCT f2.ticker_id
                    FROM filings f2
                    WHERE f2.keywords_found IS NOT NULL
                      AND f2.keywords_found::text != '[]'
                      AND f2.filed_date >= (NOW() - INTERVAL '90 days')::text
                ) fk ON fk.ticker_id = t.id
            """

        where_clause = " AND ".join(conditions + signal_conditions)

        # Build signal select columns
        signal_select = ""
        if signal_join:
            signal_select = """,
                latest_signal.score AS signal_score,
                latest_signal.signal_type,
                latest_signal.confidence,
                latest_signal.reasoning"""

        query = f"""
            SELECT
                t.id, t.symbol, t.name, t.market_cap, t.sector,
                t.avg_volume,
                (SELECT COUNT(*) FROM signals s
                 WHERE s.symbol = t.symbol
                   AND s.created_at >= NOW() - INTERVAL '30 days'
                ) AS signal_count
                {signal_select}
            FROM tickers t
            {signal_join}
            {insider_join}
            {filing_join}
            WHERE {where_clause}
            ORDER BY t.market_cap DESC NULLS LAST
            LIMIT ${idx} OFFSET ${idx + 1}
        """
        params.extend([limit, offset])

        rows = await pool.fetch(query, *params)

        results = []
        for row in rows:
            result = {
                "symbol": row["symbol"],
                "name": row["name"] or row["symbol"],
                "score": float(row.get("signal_score", 0) or 0),
                "market_cap": float(row["market_cap"]) if row["market_cap"] else None,
                "sector": row["sector"],
                "signal_count": int(row["signal_count"]),
                "signals": [],
                "latest_signal_type": row.get("signal_type"),
                "metadata": {},
                "ai_insight": None,
            }
            # Attach signal summary if we have signal data
            if row.get("signal_score"):
                result["signals"].append(
                    {
                        "type": row["signal_type"],
                        "score": float(row["signal_score"]),
                        "confidence": float(row["confidence"]),
                        "reasoning": row["reasoning"],
                    }
                )
            results.append(result)

        return {
            "preset_name": "custom",
            "results": results,
            "total": len(results),
            "limit": limit,
            "offset": offset,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception:
        logger.exception("Custom screener failed")
        raise HTTPException(status_code=500, detail="Custom screener encountered an error")


# ---------------------------------------------------------------------------
# GET /overview — preset counts for dashboard badges
# ---------------------------------------------------------------------------

@router.get("/overview")
async def screener_overview():
    """
    Return the count of tickers matching each preset.

    Used for dashboard badges showing how many opportunities each
    preset currently has.
    """
    service, error = _get_screener_service()
    if service is None:
        return {
            "counts": {
                "distressed": 0,
                "squeeze": 0,
                "insider": 0,
                "ai_opportunity": 0,
            },
            "message": f"Database not available: {error}",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    try:
        counts = await service.get_preset_counts()
        return {
            "counts": counts,
            "total": sum(counts.values()),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        logger.exception("Screener overview failed")
        return {
            "counts": {
                "distressed": 0,
                "squeeze": 0,
                "insider": 0,
                "ai_opportunity": 0,
            },
            "message": "Error computing preset counts",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
