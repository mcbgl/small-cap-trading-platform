"""
SEC Filing endpoints -- browse and search EDGAR filings with AI analysis.

Provides listing, detail, keyword frequency, and AI analysis trigger endpoints.
All queries use asyncpg raw SQL against the filings and tickers tables.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/filings", tags=["filings"])


# ---------------------------------------------------------------------------
# GET / — list filings with filters
# ---------------------------------------------------------------------------

@router.get("")
async def list_filings(
    ticker: str | None = Query(
        default=None, description="Filter by ticker symbol"
    ),
    form_type: str | None = Query(
        default=None, description="Filter by form type (e.g. 8-K, 10-Q, 10-K)"
    ),
    has_keywords: bool | None = Query(
        default=None, description="Filter for filings with distress keywords found"
    ),
    min_ai_score: float | None = Query(
        default=None, ge=0.0, le=10.0, description="Minimum AI analysis score"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    List SEC filings with optional filters.

    Joins with tickers table for symbol resolution.  Returns filing metadata,
    keywords_found array, and ai_summary/ai_score if available.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        return {"error": "Database not available", "filings": []}

    try:
        conditions: list[str] = []
        params: list = []
        idx = 1

        if ticker:
            conditions.append(f"t.symbol = ${idx}")
            params.append(ticker.upper())
            idx += 1

        if form_type:
            conditions.append(f"f.form_type = ${idx}")
            params.append(form_type)
            idx += 1

        if has_keywords is True:
            conditions.append("f.keywords_found IS NOT NULL")
            conditions.append("f.keywords_found::text != '[]'")
        elif has_keywords is False:
            conditions.append(
                "(f.keywords_found IS NULL OR f.keywords_found::text = '[]')"
            )

        if min_ai_score is not None:
            conditions.append(f"f.ai_score >= ${idx}")
            params.append(min_ai_score)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Count total matching rows for pagination metadata
        count_query = f"""
            SELECT COUNT(*) AS total
            FROM filings f
            JOIN tickers t ON t.id = f.ticker_id
            {where}
        """
        total_row = await pool.fetchrow(count_query, *params)
        total = int(total_row["total"]) if total_row else 0

        # Fetch page of results
        params.extend([limit, offset])
        rows = await pool.fetch(
            f"""
            SELECT
                f.id,
                f.ticker_id,
                t.symbol,
                t.name AS ticker_name,
                f.form_type,
                f.accession_number,
                f.filed_date,
                f.title,
                f.url,
                f.keywords_found,
                f.ai_summary,
                f.ai_score,
                f.processed,
                f.created_at
            FROM filings f
            JOIN tickers t ON t.id = f.ticker_id
            {where}
            ORDER BY f.filed_date DESC, f.created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )

        filings = []
        for row in rows:
            filing = dict(row)
            # Parse keywords_found from jsonb to list if needed
            kw = filing.get("keywords_found")
            if isinstance(kw, str):
                import json

                try:
                    filing["keywords_found"] = json.loads(kw)
                except (json.JSONDecodeError, TypeError):
                    filing["keywords_found"] = []
            filing["keyword_count"] = (
                len(filing["keywords_found"])
                if isinstance(filing["keywords_found"], list)
                else 0
            )
            filings.append(filing)

        return {
            "filings": filings,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total,
        }

    except Exception:
        logger.exception("Failed to list filings")
        raise HTTPException(status_code=500, detail="Failed to retrieve filings")


# ---------------------------------------------------------------------------
# GET /{filing_id} — single filing detail
# ---------------------------------------------------------------------------

@router.get("/{filing_id}")
async def get_filing(filing_id: int):
    """
    Retrieve a single filing by ID with full detail.

    Includes all metadata, keywords_found, items_8k, AI summary/score,
    and cached text content if available.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        row = await pool.fetchrow(
            """
            SELECT
                f.id,
                f.ticker_id,
                t.symbol,
                t.name AS ticker_name,
                t.sector,
                t.market_cap,
                f.cik,
                f.form_type,
                f.accession_number,
                f.filed_date,
                f.title,
                f.url,
                f.keywords_found,
                f.items_8k,
                f.ai_summary,
                f.ai_score,
                f.processed,
                f.created_at,
                f.updated_at
            FROM filings f
            JOIN tickers t ON t.id = f.ticker_id
            WHERE f.id = $1
            """,
            filing_id,
        )

        if row is None:
            raise HTTPException(status_code=404, detail="Filing not found")

        filing = dict(row)

        # Parse JSONB fields
        import json

        for json_field in ("keywords_found", "items_8k"):
            val = filing.get(json_field)
            if isinstance(val, str):
                try:
                    filing[json_field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    filing[json_field] = []

        # Fetch related signals for this ticker
        signals = await pool.fetch(
            """
            SELECT s.id, s.signal_type, s.score, s.confidence, s.reasoning,
                   s.created_at
            FROM signals s
            WHERE s.symbol = $1
              AND s.created_at >= NOW() - INTERVAL '30 days'
            ORDER BY s.created_at DESC
            LIMIT 10
            """,
            row["symbol"],
        )
        filing["related_signals"] = [dict(s) for s in signals]

        # Count total filings for this ticker (context)
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM filings WHERE ticker_id = $1",
            row["ticker_id"],
        )
        filing["ticker_filing_count"] = int(count or 0)

        return filing

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get filing %d", filing_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve filing")


# ---------------------------------------------------------------------------
# GET /keywords — keyword frequency across filings
# ---------------------------------------------------------------------------

@router.get("/keywords")
async def list_keywords():
    """
    List all distress keywords and their frequency across recent filings.

    Scans the keywords_found JSONB column of filings from the last 180 days
    and aggregates by keyword string.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        return {"error": "Database not available", "keywords": []}

    try:
        rows = await pool.fetch(
            """
            SELECT
                kw->>'keyword' AS keyword,
                COUNT(*) AS frequency,
                COUNT(DISTINCT f.ticker_id) AS ticker_count,
                MAX(f.filed_date) AS last_seen
            FROM filings f,
                 jsonb_array_elements(f.keywords_found) AS kw
            WHERE f.keywords_found IS NOT NULL
              AND f.keywords_found::text != '[]'
              AND f.filed_date >= (NOW() - INTERVAL '180 days')::text
            GROUP BY kw->>'keyword'
            ORDER BY frequency DESC
            """
        )

        keywords = [
            {
                "keyword": row["keyword"],
                "frequency": int(row["frequency"]),
                "ticker_count": int(row["ticker_count"]),
                "last_seen": row["last_seen"],
            }
            for row in rows
        ]

        return {
            "keywords": keywords,
            "total_keywords": len(keywords),
            "total_matches": sum(k["frequency"] for k in keywords),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    except Exception:
        logger.exception("Failed to aggregate filing keywords")
        return {"error": "Failed to compute keyword frequencies", "keywords": []}


# ---------------------------------------------------------------------------
# POST /{filing_id}/analyze — trigger AI analysis
# ---------------------------------------------------------------------------

@router.post("/{filing_id}/analyze")
async def analyze_filing(filing_id: int):
    """
    Trigger AI analysis of a specific filing.

    Verifies the filing exists, then queues an AI analysis job via the
    ai_worker. Returns immediately with a queued status.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    # Verify filing exists
    filing = await pool.fetchrow(
        """
        SELECT f.id, t.symbol, f.form_type, f.accession_number, f.processed
        FROM filings f
        JOIN tickers t ON t.id = f.ticker_id
        WHERE f.id = $1
        """,
        filing_id,
    )

    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found")

    # Check if already analysed
    if filing["processed"]:
        return {
            "status": "already_processed",
            "filing_id": filing_id,
            "symbol": filing["symbol"],
            "message": (
                f"Filing {filing['accession_number']} has already been analysed. "
                "Use GET /api/filings/{id} to retrieve the results."
            ),
        }

    # Queue analysis job
    try:
        from src.workers.ai_worker import queue_analysis

        await queue_analysis(
            task_type="filing_analysis",
            payload={
                "filing_id": filing_id,
                "symbol": filing["symbol"],
                "form_type": filing["form_type"],
                "accession_number": filing["accession_number"],
            },
            priority=3,
        )
        return {
            "status": "queued",
            "filing_id": filing_id,
            "symbol": filing["symbol"],
            "form_type": filing["form_type"],
            "message": "Filing analysis has been queued for AI processing",
        }
    except Exception as exc:
        logger.error("Failed to queue filing analysis for %d: %s", filing_id, exc)
        raise HTTPException(status_code=500, detail="Failed to queue analysis")
