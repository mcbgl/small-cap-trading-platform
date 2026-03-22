"""
Relative Volume (RVOL) anomaly detection.

RVOL > 2x 20-day average is actionable. Volume precedes price in most
small-cap moves -- this is often the earliest detectable signal.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from src.db import QuestDBClient, get_db_pool
from src.models.schemas import SignalType

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """Standardised output from every signal module."""

    symbol: str
    signal_type: SignalType
    score: float  # 0-10
    confidence: float  # 0-1
    reasoning: str
    metadata: dict = field(default_factory=dict)


# ── Score thresholds for RVOL ────────────────────────────────────────
_RVOL_SCORES: list[tuple[float, float]] = [
    # (min_rvol, score)
    (10.0, 9.0),
    (5.0, 8.0),
    (3.0, 7.0),
    (2.0, 5.0),
    (1.5, 3.0),
]


def _rvol_to_score(rvol: float) -> float:
    """Map a relative-volume ratio to a 0-10 score."""
    for threshold, score in _RVOL_SCORES:
        if rvol >= threshold:
            return score
    return 0.0


class VolumeSignal:
    """
    Detect anomalous volume spikes via Relative Volume (RVOL).

    RVOL is the ratio of current volume to the average volume over the
    same 30-minute time-of-day window across the last 20 trading days.
    """

    def __init__(self, questdb: QuestDBClient) -> None:
        self._qdb = questdb

    # ------------------------------------------------------------------
    # Single-symbol analysis
    # ------------------------------------------------------------------

    async def analyze(self, symbol: str) -> SignalResult | None:
        """
        Run RVOL analysis for *symbol*.

        Queries QuestDB for intraday volume bars, computes a time-of-day
        adjusted RVOL, and scores the result.
        """
        sym = symbol.upper()
        now = datetime.now(timezone.utc)

        # Current 30-min window bounds (floored to the half-hour)
        window_minute = (now.hour * 60 + now.minute) // 30 * 30
        window_start_min = window_minute
        window_end_min = window_minute + 30

        # ----- Fetch today's cumulative volume so far -----
        today_query = f"""
            SELECT sum(volume) AS total_vol
            FROM trades
            WHERE symbol = '{sym}'
              AND timestamp >= today()
        """
        today_resp = await self._qdb.query(today_query)
        today_vol = self._extract_scalar(today_resp)
        if today_vol is None or today_vol == 0:
            return None  # no volume data today

        # ----- Fetch historical same-window volumes (last 20 days) -----
        hist_query = f"""
            SELECT dateadd('d', 0, timestamp) AS day,
                   sum(volume) AS day_vol
            FROM trades
            WHERE symbol = '{sym}'
              AND timestamp >= dateadd('d', -30, now())
              AND timestamp < today()
              AND ((hour(timestamp) * 60 + minute(timestamp)) >= {window_start_min})
              AND ((hour(timestamp) * 60 + minute(timestamp)) < {window_end_min})
            SAMPLE BY 1d
            LIMIT 20
        """
        hist_resp = await self._qdb.query(hist_query)
        hist_vols = self._extract_column(hist_resp, "day_vol")

        if len(hist_vols) < 5:
            logger.debug(
                "Insufficient historical volume data for %s (%d days)",
                sym,
                len(hist_vols),
            )
            return None

        avg_window_vol = float(np.mean(hist_vols))
        if avg_window_vol == 0:
            return None

        rvol = today_vol / avg_window_vol
        score = _rvol_to_score(rvol)

        if score == 0:
            return None  # below actionable threshold

        # ----- Confidence based on data quality -----
        data_days = len(hist_vols)
        confidence = min(0.5 + (data_days / 20) * 0.4, 0.9)

        # ----- Check if price hasn't moved yet (early signal) -----
        price_query = f"""
            SELECT first(price) AS open_px, last(price) AS last_px
            FROM trades
            WHERE symbol = '{sym}'
              AND timestamp >= today()
        """
        price_resp = await self._qdb.query(price_query)
        open_px = self._extract_value(price_resp, "open_px")
        last_px = self._extract_value(price_resp, "last_px")

        price_move_pct = 0.0
        early_signal = False
        if open_px and last_px and open_px > 0:
            price_move_pct = ((last_px - open_px) / open_px) * 100
            # Volume spike without proportional price move => very early signal
            if rvol >= 2.0 and abs(price_move_pct) < 1.0:
                early_signal = True
                score = min(score + 1.0, 10.0)
                confidence = min(confidence + 0.05, 0.95)

        reasoning_parts = [
            f"RVOL {rvol:.1f}x (today {today_vol:,.0f} vs 20d avg {avg_window_vol:,.0f})",
        ]
        if early_signal:
            reasoning_parts.append(
                f"Volume spike without price move ({price_move_pct:+.1f}%) -- early signal"
            )
        reasoning = ". ".join(reasoning_parts)

        return SignalResult(
            symbol=sym,
            signal_type=SignalType.VOLUME,
            score=round(min(score, 10.0), 1),
            confidence=round(confidence, 2),
            reasoning=reasoning,
            metadata={
                "rvol": round(rvol, 2),
                "today_volume": today_vol,
                "avg_window_volume": round(avg_window_vol, 0),
                "data_days": data_days,
                "price_move_pct": round(price_move_pct, 2),
                "early_signal": early_signal,
            },
        )

    # ------------------------------------------------------------------
    # Batch scan
    # ------------------------------------------------------------------

    async def scan(self, symbols: list[str]) -> list[SignalResult]:
        """Run volume analysis on a batch of symbols, return scored results."""
        results: list[SignalResult] = []
        for sym in symbols:
            try:
                result = await self.analyze(sym)
                if result:
                    results.append(result)
            except Exception:
                logger.exception("Volume analysis failed for %s", sym)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # QuestDB helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_scalar(resp: dict) -> float | None:
        """Pull a single numeric value from QuestDB /exec response."""
        try:
            dataset = resp.get("dataset", [])
            if dataset and dataset[0]:
                val = dataset[0][0]
                return float(val) if val is not None else None
        except (IndexError, TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _extract_column(resp: dict, col_name: str) -> list[float]:
        """Extract a named column as a list of floats from QuestDB response."""
        columns = resp.get("columns", [])
        col_idx = None
        for i, col in enumerate(columns):
            if col.get("name") == col_name:
                col_idx = i
                break
        if col_idx is None:
            return []
        values: list[float] = []
        for row in resp.get("dataset", []):
            try:
                val = row[col_idx]
                if val is not None:
                    values.append(float(val))
            except (IndexError, TypeError, ValueError):
                continue
        return values

    @staticmethod
    def _extract_value(resp: dict, col_name: str) -> float | None:
        """Extract a single named value from the first row of a QuestDB response."""
        columns = resp.get("columns", [])
        col_idx = None
        for i, col in enumerate(columns):
            if col.get("name") == col_name:
                col_idx = i
                break
        if col_idx is None:
            return None
        try:
            dataset = resp.get("dataset", [])
            if dataset and dataset[0]:
                val = dataset[0][col_idx]
                return float(val) if val is not None else None
        except (IndexError, TypeError, ValueError):
            pass
        return None
