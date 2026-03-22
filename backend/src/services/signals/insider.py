"""
Insider cluster buying detection.

Academic research shows 4-6% annual alpha from cluster buying signals.
Cluster = 3+ distinct insiders buying open-market within 10 days.
Most predictive in small caps where information asymmetry is highest.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.db import get_db_pool
from src.models.schemas import SignalType
from src.services.signals.volume import SignalResult

logger = logging.getLogger(__name__)

# Titles that carry the most informational weight
_C_SUITE_TITLES = frozenset({
    "ceo",
    "chief executive officer",
    "cfo",
    "chief financial officer",
    "coo",
    "chief operating officer",
    "president",
    "chairman",
})

# Minimum dollar amounts that indicate conviction
_SIGNIFICANT_PURCHASE_THRESHOLD = 100_000


class InsiderSignal:
    """
    Detect insider cluster buying patterns from Form 4 filings.

    A *cluster* is defined as 3 or more distinct insiders making open-market
    purchases (transaction_type ``'P'``) within a rolling 10-day window.
    """

    # ------------------------------------------------------------------
    # Single-symbol analysis
    # ------------------------------------------------------------------

    async def analyze(self, symbol: str) -> SignalResult | None:
        """
        Evaluate insider buying for *symbol* over the last 30 days.

        Scoring:
          - 3 distinct insiders buying in 10 days  => 6
          - 4 insiders                             => 7
          - 5+ insiders                            => 8
          - CEO / CFO buying                       => +1
          - Each purchase > $100K                  => +0.5 (capped contribution 2)
          - Total capped at 10
        """
        sym = symbol.upper()
        pool = get_db_pool()

        # Fetch recent insider purchases
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        rows = await pool.fetch(
            """
            SELECT
                insider_name,
                insider_title,
                transaction_type,
                shares,
                price_per_share,
                total_value,
                transaction_date,
                filed_at
            FROM insider_transactions
            WHERE symbol = $1
              AND transaction_type = 'P'
              AND transaction_date >= $2
            ORDER BY transaction_date DESC
            """,
            sym,
            cutoff,
        )

        if not rows:
            return None

        # ---- Identify clusters (3+ distinct insiders in any 10-day window) ----
        # Group by insider name
        insider_dates: dict[str, list[datetime]] = {}
        insider_titles: dict[str, str] = {}
        insider_values: dict[str, float] = {}

        for row in rows:
            name = row["insider_name"]
            if name not in insider_dates:
                insider_dates[name] = []
                insider_titles[name] = (row["insider_title"] or "").lower()
                insider_values[name] = 0.0

            txn_date = row["transaction_date"]
            if isinstance(txn_date, datetime):
                insider_dates[name].append(txn_date)
            insider_values[name] += float(row["total_value"] or 0)

        if len(insider_dates) < 2:
            # Need at least 2 insiders to start looking for a cluster
            return None

        # Find the best 10-day cluster
        cluster_size, cluster_window = self._find_best_cluster(insider_dates)

        if cluster_size < 3:
            # Not a cluster — but still worth a low signal if 2 insiders bought
            if len(insider_dates) >= 2:
                return SignalResult(
                    symbol=sym,
                    signal_type=SignalType.INSIDER,
                    score=3.0,
                    confidence=0.5,
                    reasoning=(
                        f"{len(insider_dates)} insiders bought in last 30d "
                        f"(below cluster threshold of 3)"
                    ),
                    metadata={
                        "distinct_insiders": len(insider_dates),
                        "cluster_size": 0,
                        "total_transactions": len(rows),
                    },
                )
            return None

        # ---- Score the cluster ----
        score = 0.0
        reasons: list[str] = []

        # Base score from cluster size
        if cluster_size >= 5:
            score = 8.0
            reasons.append(f"Strong cluster: {cluster_size} insiders buying in 10 days")
        elif cluster_size == 4:
            score = 7.0
            reasons.append(f"Cluster: {cluster_size} insiders buying in 10 days")
        else:  # 3
            score = 6.0
            reasons.append(f"Cluster: {cluster_size} insiders buying in 10 days")

        # C-suite bonus
        c_suite_buyers = [
            name
            for name, title in insider_titles.items()
            if any(t in title for t in _C_SUITE_TITLES)
        ]
        if c_suite_buyers:
            score += 1.0
            reasons.append(
                f"C-suite buying: {', '.join(c_suite_buyers[:3])}"
            )

        # Significant purchase bonus (capped at +2)
        sig_count = sum(
            1
            for val in insider_values.values()
            if val >= _SIGNIFICANT_PURCHASE_THRESHOLD
        )
        sig_bonus = min(sig_count * 0.5, 2.0)
        if sig_bonus > 0:
            score += sig_bonus
            reasons.append(
                f"{sig_count} purchase(s) > ${_SIGNIFICANT_PURCHASE_THRESHOLD:,}"
            )

        score = min(round(score, 1), 10.0)

        # ---- Confidence ----
        # Higher with more data and recency
        freshness = self._freshness_score(rows)
        confidence = round(min(0.55 + (cluster_size / 10) + freshness * 0.15, 0.95), 2)

        total_value = sum(insider_values.values())

        return SignalResult(
            symbol=sym,
            signal_type=SignalType.INSIDER,
            score=score,
            confidence=confidence,
            reasoning=". ".join(reasons),
            metadata={
                "distinct_insiders": len(insider_dates),
                "cluster_size": cluster_size,
                "cluster_window_start": (
                    cluster_window[0].isoformat() if cluster_window else None
                ),
                "cluster_window_end": (
                    cluster_window[1].isoformat() if cluster_window else None
                ),
                "total_transactions": len(rows),
                "total_value": round(total_value, 2),
                "c_suite_buyers": c_suite_buyers,
                "significant_purchases": sig_count,
            },
        )

    # ------------------------------------------------------------------
    # Batch scan
    # ------------------------------------------------------------------

    async def scan(self, symbols: list[str]) -> list[SignalResult]:
        """Run insider analysis on a batch of symbols, return scored results."""
        results: list[SignalResult] = []
        for sym in symbols:
            try:
                result = await self.analyze(sym)
                if result:
                    results.append(result)
            except Exception:
                logger.exception("Insider analysis failed for %s", sym)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_best_cluster(
        insider_dates: dict[str, list[datetime]],
        window_days: int = 10,
    ) -> tuple[int, tuple[datetime, datetime] | None]:
        """
        Find the densest cluster of distinct insiders within a rolling window.

        Returns ``(cluster_size, (window_start, window_end))`` or
        ``(0, None)`` if no cluster found.
        """
        # Collect all transaction dates with their insider name
        all_events: list[tuple[datetime, str]] = []
        for name, dates in insider_dates.items():
            for dt in dates:
                all_events.append((dt, name))

        if not all_events:
            return 0, None

        all_events.sort(key=lambda x: x[0])

        best_count = 0
        best_window: tuple[datetime, datetime] | None = None

        for i, (start_dt, _) in enumerate(all_events):
            end_dt = start_dt + timedelta(days=window_days)
            insiders_in_window = {
                name
                for dt, name in all_events
                if start_dt <= dt <= end_dt
            }
            if len(insiders_in_window) > best_count:
                best_count = len(insiders_in_window)
                best_window = (start_dt, end_dt)

        return best_count, best_window

    @staticmethod
    def _freshness_score(rows: list) -> float:
        """
        Score 0-1 based on how recent the most recent transaction is.

        Same day = 1.0, 7 days ago = 0.5, 30+ days = 0.1.
        """
        if not rows:
            return 0.0
        most_recent = rows[0]["transaction_date"]
        if not isinstance(most_recent, datetime):
            return 0.5
        days_ago = (datetime.now(timezone.utc) - most_recent).days
        if days_ago <= 1:
            return 1.0
        if days_ago <= 7:
            return 0.7
        if days_ago <= 14:
            return 0.5
        if days_ago <= 30:
            return 0.3
        return 0.1
