"""
Distressed asset signal detection.

Altman Z-Score < 1.81 = distress zone (80-90% accurate 1yr ahead).
Combined with interest coverage < 1.5x, going concern opinions,
and covenant violations for comprehensive distress detection.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.db import get_db_pool
from src.models.schemas import SignalType
from src.services.signals.volume import SignalResult

logger = logging.getLogger(__name__)

# Altman Z-Score thresholds
Z_DISTRESS = 1.81
Z_GREY = 2.99

# Going concern / covenant keywords to search in filings
_GOING_CONCERN_KEYWORDS = [
    "going concern",
    "substantial doubt",
    "ability to continue as a going concern",
    "raise substantial doubt",
]
_COVENANT_KEYWORDS = [
    "covenant violation",
    "covenant breach",
    "non-compliance with",
    "waiver of covenant",
    "default under",
    "failed to maintain",
]


@dataclass
class AltmanZScore:
    """Altman Z-Score components and result."""

    z_score: float
    zone: str  # "distress", "grey", "safe"
    working_capital_ta: float
    retained_earnings_ta: float
    ebit_ta: float
    market_cap_tl: float
    revenue_ta: float


class DistressedSignal:
    """
    Detect distressed-but-recoverable situations that present asymmetric
    upside opportunities.

    This is an *opportunity* signal: pure distress with no positive catalyst
    scores low (avoid), while distress + insider buying + turnaround catalyst
    scores high (contrarian opportunity).
    """

    # ------------------------------------------------------------------
    # Single-symbol analysis
    # ------------------------------------------------------------------

    async def analyze(self, symbol: str) -> SignalResult | None:
        """
        Run distressed-asset analysis for *symbol*.

        Scoring (opportunity score, not risk score):
          - Z < 1.81                                => base 4
          - + Recent 8-K with positive catalyst     => +2
          - + Insider buying despite distress        => +2
          - + New management announcement            => +1
          - + Interest coverage improving            => +1
          - Pure distress, no positive signals       => score 2 (avoid)
        """
        sym = symbol.upper()
        pool = get_db_pool()

        # ---- Altman Z-Score ----
        z_data = await self._compute_z_score(sym)
        if z_data is None:
            logger.debug("Insufficient financial data for Z-Score on %s", sym)
            return None

        if z_data.zone == "safe":
            return None  # Not distressed — not relevant for this signal

        score = 0.0
        reasons: list[str] = []
        positive_catalysts = 0

        # Base score from distress level
        if z_data.zone == "distress":
            score = 4.0
            reasons.append(f"Altman Z-Score {z_data.z_score:.2f} (distress zone)")
        else:  # grey zone
            score = 2.0
            reasons.append(f"Altman Z-Score {z_data.z_score:.2f} (grey zone)")

        # ---- Interest coverage ----
        interest_coverage = await self._get_interest_coverage(sym)
        ic_improving = False
        if interest_coverage is not None:
            if interest_coverage < 1.5:
                reasons.append(
                    f"Interest coverage {interest_coverage:.2f}x (below 1.5x threshold)"
                )
            else:
                ic_improving = True
                score += 1.0
                positive_catalysts += 1
                reasons.append(
                    f"Interest coverage {interest_coverage:.2f}x (improving)"
                )

        # ---- Going concern opinions ----
        has_going_concern = await self._check_filing_keywords(
            sym, _GOING_CONCERN_KEYWORDS
        )
        if has_going_concern:
            reasons.append("Going concern language in recent filings")

        # ---- Covenant violations ----
        has_covenant_issue = await self._check_filing_keywords(
            sym, _COVENANT_KEYWORDS
        )
        if has_covenant_issue:
            reasons.append("Covenant violation/waiver in recent filings")

        # ---- Positive catalysts ----

        # Recent 8-K with potential positive catalyst
        has_positive_8k = await self._check_positive_8k(sym)
        if has_positive_8k:
            score += 2.0
            positive_catalysts += 1
            reasons.append("Recent 8-K with potential positive catalyst")

        # Insider buying despite distress
        insider_buying = await self._check_insider_buying(sym)
        if insider_buying:
            score += 2.0
            positive_catalysts += 1
            reasons.append("Insider buying despite distressed fundamentals")

        # New management
        has_new_mgmt = await self._check_management_change(sym)
        if has_new_mgmt:
            score += 1.0
            positive_catalysts += 1
            reasons.append("New management announcement (turnaround potential)")

        # ---- Adjust for pure distress (no catalysts) ----
        if positive_catalysts == 0:
            score = min(score, 2.0)
            reasons.append("No positive catalysts detected — avoid")

        score = min(round(score, 1), 10.0)

        if score < 1.0:
            return None

        # ---- Confidence ----
        data_completeness = self._data_completeness_score(
            z_data, interest_coverage, has_going_concern, insider_buying
        )
        confidence = round(min(0.4 + data_completeness * 0.4, 0.90), 2)

        return SignalResult(
            symbol=sym,
            signal_type=SignalType.DISTRESSED,
            score=score,
            confidence=confidence,
            reasoning=". ".join(reasons),
            metadata={
                "z_score": round(z_data.z_score, 2),
                "z_zone": z_data.zone,
                "interest_coverage": (
                    round(interest_coverage, 2) if interest_coverage else None
                ),
                "interest_coverage_improving": ic_improving,
                "going_concern": has_going_concern,
                "covenant_issue": has_covenant_issue,
                "positive_8k": has_positive_8k,
                "insider_buying": insider_buying,
                "new_management": has_new_mgmt,
                "positive_catalysts": positive_catalysts,
                "z_components": {
                    "wc_ta": round(z_data.working_capital_ta, 4),
                    "re_ta": round(z_data.retained_earnings_ta, 4),
                    "ebit_ta": round(z_data.ebit_ta, 4),
                    "mc_tl": round(z_data.market_cap_tl, 4),
                    "rev_ta": round(z_data.revenue_ta, 4),
                },
            },
        )

    # ------------------------------------------------------------------
    # Batch scan
    # ------------------------------------------------------------------

    async def scan(self, symbols: list[str]) -> list[SignalResult]:
        """Run distressed analysis on a batch of symbols, return scored results."""
        results: list[SignalResult] = []
        for sym in symbols:
            try:
                result = await self.analyze(sym)
                if result:
                    results.append(result)
            except Exception:
                logger.exception("Distressed analysis failed for %s", sym)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Altman Z-Score
    # ------------------------------------------------------------------

    async def _compute_z_score(self, symbol: str) -> AltmanZScore | None:
        """
        Compute the Altman Z-Score from XBRL financial data.

        Z = 1.2*(WC/TA) + 1.4*(RE/TA) + 3.3*(EBIT/TA)
            + 0.6*(MarketCap/TL) + 1.0*(Revenue/TA)
        """
        pool = get_db_pool()

        row = await pool.fetchrow(
            """
            SELECT
                total_assets,
                current_assets,
                current_liabilities,
                total_liabilities,
                retained_earnings,
                ebit,
                revenue,
                market_cap
            FROM financials
            WHERE symbol = $1
            ORDER BY period_end DESC
            LIMIT 1
            """,
            symbol,
        )

        if not row:
            return None

        ta = float(row["total_assets"] or 0)
        if ta == 0:
            return None

        ca = float(row["current_assets"] or 0)
        cl = float(row["current_liabilities"] or 0)
        tl = float(row["total_liabilities"] or 0)
        re = float(row["retained_earnings"] or 0)
        ebit = float(row["ebit"] or 0)
        rev = float(row["revenue"] or 0)
        mc = float(row["market_cap"] or 0)

        wc_ta = (ca - cl) / ta
        re_ta = re / ta
        ebit_ta = ebit / ta
        mc_tl = mc / tl if tl > 0 else 10.0  # no debt = very safe
        rev_ta = rev / ta

        z = 1.2 * wc_ta + 1.4 * re_ta + 3.3 * ebit_ta + 0.6 * mc_tl + 1.0 * rev_ta

        if z < Z_DISTRESS:
            zone = "distress"
        elif z < Z_GREY:
            zone = "grey"
        else:
            zone = "safe"

        return AltmanZScore(
            z_score=z,
            zone=zone,
            working_capital_ta=wc_ta,
            retained_earnings_ta=re_ta,
            ebit_ta=ebit_ta,
            market_cap_tl=mc_tl,
            revenue_ta=rev_ta,
        )

    # ------------------------------------------------------------------
    # Supporting data checks
    # ------------------------------------------------------------------

    async def _get_interest_coverage(self, symbol: str) -> float | None:
        """Fetch the latest interest coverage ratio (EBIT / InterestExpense)."""
        pool = get_db_pool()
        row = await pool.fetchrow(
            """
            SELECT ebit, interest_expense
            FROM financials
            WHERE symbol = $1 AND interest_expense IS NOT NULL AND interest_expense > 0
            ORDER BY period_end DESC
            LIMIT 1
            """,
            symbol,
        )
        if not row:
            return None
        ebit = float(row["ebit"] or 0)
        ie = float(row["interest_expense"])
        return ebit / ie if ie > 0 else None

    async def _check_filing_keywords(
        self, symbol: str, keywords: list[str]
    ) -> bool:
        """Check recent filings for keyword matches."""
        pool = get_db_pool()
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)

        # Build ILIKE conditions
        conditions = " OR ".join(
            f"content ILIKE '%{kw}%'" for kw in keywords
        )

        count = await pool.fetchval(
            f"""
            SELECT COUNT(*)
            FROM filings
            WHERE symbol = $1
              AND filed_at >= $2
              AND ({conditions})
            """,
            symbol,
            cutoff,
        )
        return (count or 0) > 0

    async def _check_positive_8k(self, symbol: str) -> bool:
        """Check for recent 8-K filings that may contain positive catalysts."""
        pool = get_db_pool()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        positive_keywords = [
            "strategic partnership",
            "acquisition",
            "contract award",
            "patent",
            "FDA approval",
            "debt restructuring",
            "refinancing",
            "new credit facility",
        ]
        conditions = " OR ".join(
            f"content ILIKE '%{kw}%'" for kw in positive_keywords
        )

        count = await pool.fetchval(
            f"""
            SELECT COUNT(*)
            FROM filings
            WHERE symbol = $1
              AND filing_type = '8-K'
              AND filed_at >= $2
              AND ({conditions})
            """,
            symbol,
            cutoff,
        )
        return (count or 0) > 0

    async def _check_insider_buying(self, symbol: str) -> bool:
        """Check for insider purchases in last 30 days."""
        pool = get_db_pool()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        count = await pool.fetchval(
            """
            SELECT COUNT(DISTINCT insider_name)
            FROM insider_transactions
            WHERE symbol = $1
              AND transaction_type = 'P'
              AND transaction_date >= $2
            """,
            symbol,
            cutoff,
        )
        return (count or 0) >= 1

    async def _check_management_change(self, symbol: str) -> bool:
        """Check for recent management change announcements (8-K items 5.02)."""
        pool = get_db_pool()
        cutoff = datetime.now(timezone.utc) - timedelta(days=60)

        mgmt_keywords = [
            "appointment of",
            "named chief executive",
            "named ceo",
            "new management",
            "management change",
            "officer appointment",
        ]
        conditions = " OR ".join(
            f"content ILIKE '%{kw}%'" for kw in mgmt_keywords
        )

        count = await pool.fetchval(
            f"""
            SELECT COUNT(*)
            FROM filings
            WHERE symbol = $1
              AND filed_at >= $2
              AND ({conditions})
            """,
            symbol,
            cutoff,
        )
        return (count or 0) > 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _data_completeness_score(
        z_data: AltmanZScore | None,
        interest_coverage: float | None,
        has_going_concern: bool,
        insider_buying: bool,
    ) -> float:
        """
        Score 0-1 based on how many data sources were available.

        More data = higher confidence in the signal.
        """
        available = 0
        total = 4
        if z_data is not None:
            available += 1
        if interest_coverage is not None:
            available += 1
        if has_going_concern is not None:  # always True/False, so always available
            available += 1
        if insider_buying is not None:
            available += 1
        return available / total
