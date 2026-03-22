"""
Screener preset implementations.

Four preset screens: Distressed, Short Squeeze, Insider Buying, AI Opportunity.
Each queries PostgreSQL/QuestDB for matching tickers and enriches with signal data.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import asyncpg

from src.config import settings
from src.db import QuestDBClient
from src.models.schemas import InsightCard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScreenerResult:
    """A single screener match — one ticker that passed the preset filter."""

    symbol: str
    name: str
    score: float  # 0-10 composite opportunity score
    market_cap: float | None = None
    sector: str | None = None
    signal_count: int = 0
    signals: list[dict] = field(default_factory=list)  # signal summaries
    latest_signal_type: str | None = None
    metadata: dict = field(default_factory=dict)
    ai_insight: InsightCard | None = None


@dataclass
class ScreenerResponse:
    """Response envelope for a preset screen run."""

    preset_name: str
    results: list[ScreenerResult]
    total: int
    limit: int
    offset: int
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Preset definitions (static metadata)
# ---------------------------------------------------------------------------

_PRESET_DEFS: list[dict] = [
    {
        "name": "distressed",
        "label": "Distressed / Deep Value",
        "description": (
            "Stocks with distress signals (going concern, covenant breach) "
            "but potential turnaround catalysts. Sorted by composite distress "
            "opportunity score."
        ),
        "icon": "alert-triangle",
        "default_sort": "score",
    },
    {
        "name": "squeeze",
        "label": "Short Squeeze Candidates",
        "description": (
            "High short interest + rising volume + technical squeeze setup. "
            "Enriched with FINRA SI%, days-to-cover, RVOL, RSI."
        ),
        "icon": "trending-up",
        "default_sort": "score",
    },
    {
        "name": "insider",
        "label": "Insider Buying Clusters",
        "description": (
            "Tickers with 2+ distinct insiders making open-market purchases "
            "in the last 30 days. Academic alpha of 4-6%."
        ),
        "icon": "users",
        "default_sort": "score",
    },
    {
        "name": "ai_opportunity",
        "label": "AI Opportunity",
        "description": (
            "Highest-conviction multi-signal convergence opportunities. "
            "AI composite score >= 7.0 with confidence above threshold."
        ),
        "icon": "cpu",
        "default_sort": "score",
    },
]


# ---------------------------------------------------------------------------
# ScreenerService
# ---------------------------------------------------------------------------

class ScreenerService:
    """
    Runs preset and custom screener queries against PostgreSQL.

    Each preset builds SQL that joins the tickers table with signals,
    filings, and/or insider_transactions to find matching opportunities,
    then enriches results with metadata from the relevant data source.
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        questdb: QuestDBClient | None = None,
        redis: object | None = None,
    ) -> None:
        self._pool = db_pool
        self._qdb = questdb
        self._redis = redis

    # ------------------------------------------------------------------
    # Public: run a named preset
    # ------------------------------------------------------------------

    async def run_preset(
        self,
        preset_name: str,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "score",
    ) -> ScreenerResponse:
        """
        Dispatch to the correct preset runner by name.

        Raises ValueError if the preset name is unknown.
        """
        runners = {
            "distressed": self.run_distressed,
            "squeeze": self.run_squeeze,
            "insider": self.run_insider,
            "ai_opportunity": self.run_ai_opportunity,
        }

        runner = runners.get(preset_name)
        if runner is None:
            raise ValueError(
                f"Unknown preset '{preset_name}'. "
                f"Available: {', '.join(runners.keys())}"
            )

        results = await runner(limit=limit, offset=offset)

        # Sort results
        reverse = True
        if sort_by == "market_cap":
            results.sort(key=lambda r: r.market_cap or 0, reverse=reverse)
        elif sort_by == "signal_count":
            results.sort(key=lambda r: r.signal_count, reverse=reverse)
        elif sort_by == "symbol":
            results.sort(key=lambda r: r.symbol, reverse=False)
        else:
            # Default: sort by score descending
            results.sort(key=lambda r: r.score, reverse=reverse)

        # Count total before pagination (results are already limited by SQL,
        # but we re-slice for safety)
        total = len(results)

        return ScreenerResponse(
            preset_name=preset_name,
            results=results,
            total=total,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Preset: Distressed / Deep Value
    # ------------------------------------------------------------------

    async def run_distressed(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScreenerResult]:
        """
        Find tickers with distress signals and filing keywords.

        Joins signals (type='distressed', score>=4) with filings that
        contain going concern / covenant keywords.  Computes a composite
        distress opportunity score from signal strength + filing keyword count.
        """
        rows = await self._pool.fetch(
            """
            WITH distress_signals AS (
                SELECT
                    s.symbol,
                    s.score,
                    s.confidence,
                    s.reasoning,
                    s.metadata::text AS meta_text,
                    s.created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.symbol ORDER BY s.created_at DESC
                    ) AS rn
                FROM signals s
                WHERE s.signal_type = 'distressed'
                  AND s.score >= 4.0
                  AND s.created_at >= NOW() - INTERVAL '30 days'
            ),
            ticker_signals AS (
                SELECT
                    t.id AS ticker_id,
                    t.symbol,
                    t.name,
                    t.market_cap,
                    t.sector,
                    ds.score AS signal_score,
                    ds.confidence,
                    ds.reasoning,
                    ds.meta_text,
                    ds.created_at AS signal_at
                FROM tickers t
                JOIN distress_signals ds ON ds.symbol = t.symbol AND ds.rn = 1
                WHERE t.is_active = true
            ),
            filing_keywords AS (
                SELECT
                    f.ticker_id,
                    COUNT(*) AS filing_count,
                    jsonb_agg(
                        jsonb_build_object(
                            'form_type', f.form_type,
                            'filed_date', f.filed_date,
                            'keywords', f.keywords_found
                        )
                        ORDER BY f.filed_date DESC
                    ) AS filings_json
                FROM filings f
                WHERE f.keywords_found IS NOT NULL
                  AND f.keywords_found::text != '[]'
                  AND f.filed_date >= (NOW() - INTERVAL '90 days')::text
                GROUP BY f.ticker_id
            ),
            recent_8k AS (
                SELECT
                    f.ticker_id,
                    COUNT(*) AS eightk_count
                FROM filings f
                WHERE f.form_type = '8-K'
                  AND f.filed_date >= (NOW() - INTERVAL '30 days')::text
                GROUP BY f.ticker_id
            ),
            signal_counts AS (
                SELECT
                    s.symbol,
                    COUNT(*) AS total_signals
                FROM signals s
                WHERE s.created_at >= NOW() - INTERVAL '30 days'
                GROUP BY s.symbol
            )
            SELECT
                ts.symbol,
                ts.name,
                ts.market_cap,
                ts.sector,
                ts.signal_score,
                ts.confidence,
                ts.reasoning,
                ts.meta_text,
                ts.signal_at,
                COALESCE(fk.filing_count, 0) AS filing_count,
                fk.filings_json,
                COALESCE(rk.eightk_count, 0) AS eightk_count,
                COALESCE(sc.total_signals, 0) AS total_signals,
                -- Composite distress opportunity score
                (ts.signal_score * 0.6
                 + LEAST(COALESCE(fk.filing_count, 0), 5) * 0.5
                 + LEAST(COALESCE(rk.eightk_count, 0), 3) * 0.3
                ) AS composite_score
            FROM ticker_signals ts
            LEFT JOIN filing_keywords fk ON fk.ticker_id = ts.ticker_id
            LEFT JOIN recent_8k rk ON rk.ticker_id = ts.ticker_id
            LEFT JOIN signal_counts sc ON sc.symbol = ts.symbol
            ORDER BY composite_score DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

        results: list[ScreenerResult] = []
        for row in rows:
            meta = {}
            try:
                if row["meta_text"]:
                    meta = json.loads(row["meta_text"])
            except (json.JSONDecodeError, TypeError):
                pass

            results.append(
                ScreenerResult(
                    symbol=row["symbol"],
                    name=row["name"] or row["symbol"],
                    score=round(min(float(row["composite_score"]), 10.0), 1),
                    market_cap=float(row["market_cap"]) if row["market_cap"] else None,
                    sector=row["sector"],
                    signal_count=int(row["total_signals"]),
                    signals=[
                        {
                            "type": "distressed",
                            "score": float(row["signal_score"]),
                            "confidence": float(row["confidence"]),
                            "reasoning": row["reasoning"],
                        }
                    ],
                    latest_signal_type="distressed",
                    metadata={
                        "z_score": meta.get("z_score"),
                        "interest_coverage": meta.get("interest_coverage"),
                        "recent_8k_count": int(row["eightk_count"]),
                        "distress_filing_count": int(row["filing_count"]),
                    },
                )
            )

        return results

    # ------------------------------------------------------------------
    # Preset: Short Squeeze
    # ------------------------------------------------------------------

    async def run_squeeze(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScreenerResult]:
        """
        Find tickers with squeeze signals enriched with short interest data.

        Queries signals with type='squeeze' and score>=5, then enriches
        with FINRA short interest data (SI%, DTC) and technical metadata
        (RVOL, RSI).
        """
        rows = await self._pool.fetch(
            """
            WITH squeeze_signals AS (
                SELECT
                    s.symbol,
                    s.score,
                    s.confidence,
                    s.reasoning,
                    s.metadata::text AS meta_text,
                    s.created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.symbol ORDER BY s.score DESC, s.created_at DESC
                    ) AS rn
                FROM signals s
                WHERE s.signal_type = 'squeeze'
                  AND s.score >= 5.0
                  AND s.created_at >= NOW() - INTERVAL '14 days'
            ),
            short_data AS (
                SELECT DISTINCT ON (si.symbol)
                    si.symbol,
                    si.current_short_interest,
                    si.days_to_cover,
                    si.change_pct AS si_change_pct
                FROM short_interest si
                ORDER BY si.symbol, si.settlement_date DESC
            ),
            signal_counts AS (
                SELECT s.symbol, COUNT(*) AS total_signals
                FROM signals s
                WHERE s.created_at >= NOW() - INTERVAL '14 days'
                GROUP BY s.symbol
            )
            SELECT
                t.symbol,
                t.name,
                t.market_cap,
                t.sector,
                t.avg_volume,
                sq.score AS squeeze_score,
                sq.confidence,
                sq.reasoning,
                sq.meta_text,
                sq.created_at AS signal_at,
                sd.current_short_interest,
                sd.days_to_cover,
                sd.si_change_pct,
                COALESCE(sc.total_signals, 0) AS total_signals
            FROM squeeze_signals sq
            JOIN tickers t ON t.symbol = sq.symbol AND t.is_active = true
            LEFT JOIN short_data sd ON sd.symbol = t.symbol
            LEFT JOIN signal_counts sc ON sc.symbol = t.symbol
            WHERE sq.rn = 1
            ORDER BY sq.score DESC, sq.confidence DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

        results: list[ScreenerResult] = []
        for row in rows:
            meta = {}
            try:
                if row["meta_text"]:
                    meta = json.loads(row["meta_text"])
            except (json.JSONDecodeError, TypeError):
                pass

            # Compute SI% estimate (short_interest / market_cap as rough proxy)
            si_pct = None
            if row["current_short_interest"] and row["market_cap"]:
                si_pct = round(
                    (float(row["current_short_interest"]) / float(row["market_cap"])) * 100,
                    2,
                )

            results.append(
                ScreenerResult(
                    symbol=row["symbol"],
                    name=row["name"] or row["symbol"],
                    score=round(float(row["squeeze_score"]), 1),
                    market_cap=float(row["market_cap"]) if row["market_cap"] else None,
                    sector=row["sector"],
                    signal_count=int(row["total_signals"]),
                    signals=[
                        {
                            "type": "squeeze",
                            "score": float(row["squeeze_score"]),
                            "confidence": float(row["confidence"]),
                            "reasoning": row["reasoning"],
                        }
                    ],
                    latest_signal_type="squeeze",
                    metadata={
                        "si_pct": si_pct,
                        "days_to_cover": (
                            float(row["days_to_cover"])
                            if row["days_to_cover"] is not None
                            else None
                        ),
                        "si_change_pct": (
                            float(row["si_change_pct"])
                            if row["si_change_pct"] is not None
                            else None
                        ),
                        "rvol": meta.get("rvol"),
                        "rsi": meta.get("rsi"),
                        "bb_inside_kc_days": meta.get("bb_inside_kc_days"),
                    },
                )
            )

        return results

    # ------------------------------------------------------------------
    # Preset: Insider Buying Clusters
    # ------------------------------------------------------------------

    async def run_insider(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScreenerResult]:
        """
        Find tickers with cluster insider buying in the last 30 days.

        Groups insider_transactions by ticker, counts distinct insiders,
        sums purchase value.  Requires 2+ insiders buying.  Scored by
        cluster strength (more insiders + higher value = higher score).
        """
        rows = await self._pool.fetch(
            """
            WITH insider_buys AS (
                SELECT
                    t.id AS ticker_id,
                    t.symbol,
                    t.name,
                    t.market_cap,
                    t.sector,
                    it.insider_name,
                    it.insider_role,
                    it.shares,
                    it.total_value,
                    it.price_per_share,
                    it.transaction_date
                FROM insider_transactions it
                JOIN tickers t ON t.id = it.ticker_id
                WHERE it.transaction_type = 'P'
                  AND it.transaction_date >= (NOW() - INTERVAL '30 days')::date
                  AND t.is_active = true
            ),
            cluster_stats AS (
                SELECT
                    symbol,
                    name,
                    market_cap,
                    sector,
                    COUNT(DISTINCT insider_name) AS distinct_insiders,
                    SUM(total_value) AS total_purchase_value,
                    SUM(shares) AS total_shares,
                    MAX(total_value) AS max_single_purchase,
                    jsonb_agg(
                        jsonb_build_object(
                            'name', insider_name,
                            'role', insider_role,
                            'shares', shares,
                            'value', total_value,
                            'price', price_per_share,
                            'date', transaction_date
                        )
                        ORDER BY total_value DESC
                    ) AS insider_details,
                    bool_or(
                        LOWER(insider_role) LIKE '%ceo%'
                        OR LOWER(insider_role) LIKE '%chief executive%'
                    ) AS has_ceo,
                    bool_or(total_value > 100000) AS has_large_purchase
                FROM insider_buys
                GROUP BY symbol, name, market_cap, sector
                HAVING COUNT(DISTINCT insider_name) >= 2
            ),
            signal_counts AS (
                SELECT s.symbol, COUNT(*) AS total_signals
                FROM signals s
                WHERE s.created_at >= NOW() - INTERVAL '30 days'
                GROUP BY s.symbol
            )
            SELECT
                cs.*,
                COALESCE(sc.total_signals, 0) AS total_signals,
                -- Scoring: base + cluster size bonus + value bonus + role bonus
                LEAST(10.0,
                    4.0
                    + LEAST(cs.distinct_insiders, 6) * 0.8
                    + CASE WHEN cs.has_ceo THEN 0.5 ELSE 0.0 END
                    + CASE WHEN cs.has_large_purchase THEN 0.5 ELSE 0.0 END
                    + CASE
                        WHEN cs.total_purchase_value > 1000000 THEN 1.0
                        WHEN cs.total_purchase_value > 500000 THEN 0.5
                        ELSE 0.0
                      END
                ) AS cluster_score
            FROM cluster_stats cs
            LEFT JOIN signal_counts sc ON sc.symbol = cs.symbol
            ORDER BY cluster_score DESC, cs.total_purchase_value DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

        results: list[ScreenerResult] = []
        for row in rows:
            insider_details = row["insider_details"]
            if isinstance(insider_details, str):
                try:
                    insider_details = json.loads(insider_details)
                except (json.JSONDecodeError, TypeError):
                    insider_details = []

            results.append(
                ScreenerResult(
                    symbol=row["symbol"],
                    name=row["name"] or row["symbol"],
                    score=round(float(row["cluster_score"]), 1),
                    market_cap=float(row["market_cap"]) if row["market_cap"] else None,
                    sector=row["sector"],
                    signal_count=int(row["total_signals"]),
                    signals=[
                        {
                            "type": "insider",
                            "score": float(row["cluster_score"]),
                            "distinct_insiders": int(row["distinct_insiders"]),
                            "total_value": float(row["total_purchase_value"] or 0),
                        }
                    ],
                    latest_signal_type="insider",
                    metadata={
                        "distinct_insiders": int(row["distinct_insiders"]),
                        "total_purchase_value": float(row["total_purchase_value"] or 0),
                        "total_shares": float(row["total_shares"] or 0),
                        "max_single_purchase": float(row["max_single_purchase"] or 0),
                        "has_ceo_buying": bool(row["has_ceo"]),
                        "has_large_purchase": bool(row["has_large_purchase"]),
                        "insider_details": insider_details,
                    },
                )
            )

        return results

    # ------------------------------------------------------------------
    # Preset: AI Opportunity
    # ------------------------------------------------------------------

    async def run_ai_opportunity(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScreenerResult]:
        """
        Find tickers with high-conviction AI composite signals.

        Queries signals with type='ai_composite', score>=7.0, and
        confidence above the configured minimum.  Includes all
        contributing signal types in the metadata.
        """
        confidence_min = settings.ai_confidence_min

        rows = await self._pool.fetch(
            """
            WITH ai_signals AS (
                SELECT
                    s.symbol,
                    s.score,
                    s.confidence,
                    s.reasoning,
                    s.metadata::text AS meta_text,
                    s.created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.symbol ORDER BY s.score DESC, s.created_at DESC
                    ) AS rn
                FROM signals s
                WHERE s.signal_type = 'ai_composite'
                  AND s.score >= 7.0
                  AND s.confidence >= $3
                  AND s.created_at >= NOW() - INTERVAL '7 days'
            ),
            signal_counts AS (
                SELECT s.symbol, COUNT(*) AS total_signals
                FROM signals s
                WHERE s.created_at >= NOW() - INTERVAL '7 days'
                GROUP BY s.symbol
            ),
            latest_insight AS (
                SELECT DISTINCT ON (ic.ticker)
                    ic.ticker,
                    ic.title,
                    ic.score AS insight_score,
                    ic.pros,
                    ic.cons,
                    ic.recommendation,
                    ic.confidence AS insight_confidence,
                    ic.model
                FROM insight_cards ic
                ORDER BY ic.ticker, ic.created_at DESC
            )
            SELECT
                t.symbol,
                t.name,
                t.market_cap,
                t.sector,
                ai.score AS ai_score,
                ai.confidence,
                ai.reasoning,
                ai.meta_text,
                ai.created_at AS signal_at,
                COALESCE(sc.total_signals, 0) AS total_signals,
                li.title AS insight_title,
                li.insight_score,
                li.pros AS insight_pros,
                li.cons AS insight_cons,
                li.recommendation AS insight_recommendation,
                li.insight_confidence,
                li.model AS insight_model
            FROM ai_signals ai
            JOIN tickers t ON t.symbol = ai.symbol AND t.is_active = true
            LEFT JOIN signal_counts sc ON sc.symbol = t.symbol
            LEFT JOIN latest_insight li ON li.ticker = t.symbol
            WHERE ai.rn = 1
            ORDER BY ai.score DESC, ai.confidence DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
            confidence_min,
        )

        results: list[ScreenerResult] = []
        for row in rows:
            meta = {}
            try:
                if row["meta_text"]:
                    meta = json.loads(row["meta_text"])
            except (json.JSONDecodeError, TypeError):
                pass

            # Build InsightCard if available
            ai_insight = None
            if row["insight_title"]:
                try:
                    ai_insight = InsightCard(
                        title=row["insight_title"],
                        ticker=row["symbol"],
                        score=float(row["insight_score"]),
                        pros=row["insight_pros"] or [],
                        cons=row["insight_cons"] or [],
                        recommendation=row["insight_recommendation"] or "",
                        confidence=float(row["insight_confidence"]),
                        model=row["insight_model"] or "unknown",
                    )
                except Exception:
                    logger.debug(
                        "Failed to build InsightCard for %s", row["symbol"]
                    )

            # Extract contributing signal types from metadata
            signal_breakdown = meta.get("signal_breakdown", {})
            contributing_types = list(signal_breakdown.keys())

            signals_list = [
                {
                    "type": "ai_composite",
                    "score": float(row["ai_score"]),
                    "confidence": float(row["confidence"]),
                    "reasoning": row["reasoning"],
                }
            ]
            # Add individual contributing signals to the list
            for sig_type, sig_data in signal_breakdown.items():
                if isinstance(sig_data, dict):
                    signals_list.append(
                        {
                            "type": sig_type,
                            "score": sig_data.get("score", 0),
                            "confidence": sig_data.get("confidence", 0),
                        }
                    )

            results.append(
                ScreenerResult(
                    symbol=row["symbol"],
                    name=row["name"] or row["symbol"],
                    score=round(float(row["ai_score"]), 1),
                    market_cap=float(row["market_cap"]) if row["market_cap"] else None,
                    sector=row["sector"],
                    signal_count=int(row["total_signals"]),
                    signals=signals_list,
                    latest_signal_type="ai_composite",
                    metadata={
                        "contributing_signals": meta.get("contributing_signals", 0),
                        "contributing_types": contributing_types,
                        "signal_breakdown": signal_breakdown,
                        "total_weight": meta.get("total_weight"),
                        "confidence_min_threshold": confidence_min,
                    },
                    ai_insight=ai_insight,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Preset counts (for overview / dashboard badges)
    # ------------------------------------------------------------------

    async def get_preset_counts(self) -> dict[str, int]:
        """
        Return the count of tickers matching each preset.

        Uses lightweight COUNT queries rather than full preset runs.
        """
        confidence_min = settings.ai_confidence_min

        row = await self._pool.fetchrow(
            """
            SELECT
                (SELECT COUNT(DISTINCT s.symbol)
                 FROM signals s
                 WHERE s.signal_type = 'distressed'
                   AND s.score >= 4.0
                   AND s.created_at >= NOW() - INTERVAL '30 days'
                ) AS distressed_count,

                (SELECT COUNT(DISTINCT s.symbol)
                 FROM signals s
                 WHERE s.signal_type = 'squeeze'
                   AND s.score >= 5.0
                   AND s.created_at >= NOW() - INTERVAL '14 days'
                ) AS squeeze_count,

                (SELECT COUNT(DISTINCT t.symbol)
                 FROM insider_transactions it
                 JOIN tickers t ON t.id = it.ticker_id
                 WHERE it.transaction_type = 'P'
                   AND it.transaction_date >= (NOW() - INTERVAL '30 days')::date
                 GROUP BY t.symbol
                 HAVING COUNT(DISTINCT it.insider_name) >= 2
                ) AS insider_count,

                (SELECT COUNT(DISTINCT s.symbol)
                 FROM signals s
                 WHERE s.signal_type = 'ai_composite'
                   AND s.score >= 7.0
                   AND s.confidence >= $1
                   AND s.created_at >= NOW() - INTERVAL '7 days'
                ) AS ai_opportunity_count
            """,
            confidence_min,
        )

        if row is None:
            return {
                "distressed": 0,
                "squeeze": 0,
                "insider": 0,
                "ai_opportunity": 0,
            }

        return {
            "distressed": int(row["distressed_count"] or 0),
            "squeeze": int(row["squeeze_count"] or 0),
            "insider": int(row["insider_count"] or 0),
            "ai_opportunity": int(row["ai_opportunity_count"] or 0),
        }

    # ------------------------------------------------------------------
    # Static: available presets
    # ------------------------------------------------------------------

    @staticmethod
    def get_available_presets() -> list[dict]:
        """Return the list of preset definitions with descriptions."""
        return list(_PRESET_DEFS)
