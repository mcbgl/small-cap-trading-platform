"""
Short squeeze setup detection.

Criteria: SI% > 20%, Days to Cover > 5, rising volume, RSI oversold.
Combined with cost-to-borrow rising = squeeze pressure building.
"""

import logging
from dataclasses import dataclass, field

from src.db import QuestDBClient, get_db_pool, get_redis
from src.models.schemas import SignalType
from src.services.data.finra_short import FinraShortInterest, ShortInterestMetrics
from src.services.signals.volume import SignalResult, VolumeSignal

logger = logging.getLogger(__name__)


class SqueezeSignal:
    """
    Detect short-squeeze setups by combining short interest, volume, and
    technical data into a single composite squeeze score.
    """

    def __init__(
        self,
        finra: FinraShortInterest,
        volume_signal: VolumeSignal,
        questdb: QuestDBClient,
    ) -> None:
        self._finra = finra
        self._volume = volume_signal
        self._qdb = questdb

    # ------------------------------------------------------------------
    # Single-symbol analysis
    # ------------------------------------------------------------------

    async def analyze(self, symbol: str) -> SignalResult | None:
        """
        Evaluate squeeze potential for *symbol*.

        Scoring breakdown:
          - SI% > 20% AND DTC > 5  => base score 5
          - + RVOL > 2x            => +2
          - + RSI < 30             => +1
          - + price > 20d SMA      => +1 (squeeze already starting)
          - + SI% trend rising     => +1
        """
        sym = symbol.upper()

        # ---- Short interest data ----
        si_metrics = await self._get_si_metrics(sym)
        if si_metrics is None:
            logger.debug("No SI data for %s — skipping squeeze analysis", sym)
            return None

        si_pct = si_metrics.si_pct
        dtc = si_metrics.days_to_cover
        si_trend = si_metrics.si_trend

        # Base qualification gate
        if si_pct < 10.0:
            return None  # not enough short interest to be interesting

        # ---- Base score ----
        score = 0.0
        reasons: list[str] = []

        if si_pct >= 20.0 and dtc >= 5.0:
            score = 5.0
            reasons.append(
                f"High SI {si_pct:.1f}% with DTC {dtc:.1f} days"
            )
        elif si_pct >= 15.0 and dtc >= 3.0:
            score = 3.0
            reasons.append(
                f"Moderate SI {si_pct:.1f}% with DTC {dtc:.1f} days"
            )
        elif si_pct >= 10.0:
            score = 2.0
            reasons.append(f"SI {si_pct:.1f}% — elevated but not extreme")
        else:
            return None

        confidence_components: list[float] = [0.6]  # base confidence with SI data

        # ---- RVOL boost ----
        vol_result = await self._volume.analyze(sym)
        rvol = 0.0
        if vol_result and vol_result.metadata.get("rvol"):
            rvol = vol_result.metadata["rvol"]
            if rvol >= 2.0:
                score += 2.0
                reasons.append(f"Volume spike RVOL {rvol:.1f}x")
                confidence_components.append(0.75)
            elif rvol >= 1.5:
                score += 1.0
                reasons.append(f"Elevated volume RVOL {rvol:.1f}x")
                confidence_components.append(0.6)

        # ---- RSI check ----
        rsi = await self._get_rsi(sym)
        if rsi is not None:
            if rsi < 30:
                score += 1.0
                reasons.append(f"RSI oversold at {rsi:.1f}")
                confidence_components.append(0.7)
            elif rsi > 70:
                # Overbought — squeeze may be exhausting
                reasons.append(f"RSI overbought at {rsi:.1f} — caution")
                confidence_components.append(0.5)

        # ---- Price vs 20d SMA (squeeze already starting?) ----
        above_sma = await self._price_above_sma(sym, period=20)
        if above_sma is True:
            score += 1.0
            reasons.append("Price above 20d SMA — squeeze underway")
            confidence_components.append(0.65)
        elif above_sma is False:
            reasons.append("Price below 20d SMA — setup building")

        # ---- SI trend ----
        if si_trend == "rising":
            score += 1.0
            reasons.append(
                f"SI trend rising ({si_metrics.si_change_pct:+.1f}%)"
            )
            confidence_components.append(0.7)

        # Cap and compute
        score = min(round(score, 1), 10.0)
        confidence = round(
            sum(confidence_components) / len(confidence_components), 2
        )

        if score < 2.0:
            return None

        return SignalResult(
            symbol=sym,
            signal_type=SignalType.SQUEEZE,
            score=score,
            confidence=confidence,
            reasoning=". ".join(reasons),
            metadata={
                "si_pct": si_pct,
                "days_to_cover": dtc,
                "si_trend": si_trend,
                "si_change_pct": si_metrics.si_change_pct,
                "rvol": round(rvol, 2),
                "rsi": rsi,
                "above_20d_sma": above_sma,
                "settlement_date": si_metrics.settlement_date,
            },
        )

    # ------------------------------------------------------------------
    # Batch scan
    # ------------------------------------------------------------------

    async def scan(self, symbols: list[str]) -> list[SignalResult]:
        """
        Batch-scan *symbols* for squeeze setups.

        Returns results sorted by score (descending).
        """
        results: list[SignalResult] = []
        for sym in symbols:
            try:
                result = await self.analyze(sym)
                if result:
                    results.append(result)
            except Exception:
                logger.exception("Squeeze analysis failed for %s", sym)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    async def _get_si_metrics(self, symbol: str) -> ShortInterestMetrics | None:
        """Fetch SI metrics from FINRA client, using cached/stored data."""
        pool = get_db_pool()
        row = await pool.fetchrow(
            """
            SELECT avg_volume, market_cap
            FROM tickers
            WHERE symbol = $1 AND is_active = true
            """,
            symbol,
        )
        if not row or not row["market_cap"]:
            return None

        avg_vol = float(row["avg_volume"] or 0)
        shares_out = float(row["market_cap"])  # refine with fundamentals

        return await self._finra.compute_metrics(symbol, avg_vol, shares_out)

    async def _get_rsi(self, symbol: str, period: int = 14) -> float | None:
        """
        Compute RSI from QuestDB price data.

        Uses the classic Wilder smoothed RSI over *period* bars.
        """
        query = f"""
            SELECT close
            FROM ohlcv_1d
            WHERE symbol = '{symbol}'
            ORDER BY timestamp DESC
            LIMIT {period + 5}
        """
        resp = await self._qdb.query(query)
        closes = self._extract_column(resp, "close")

        if len(closes) < period + 1:
            return None

        # Reverse so oldest first
        closes = list(reversed(closes))
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        # Wilder smoothing for remaining bars
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)

    async def _price_above_sma(
        self, symbol: str, period: int = 20
    ) -> bool | None:
        """Check whether the current price is above the N-day SMA."""
        query = f"""
            SELECT close
            FROM ohlcv_1d
            WHERE symbol = '{symbol}'
            ORDER BY timestamp DESC
            LIMIT {period + 1}
        """
        resp = await self._qdb.query(query)
        closes = self._extract_column(resp, "close")

        if len(closes) < period:
            return None

        current = closes[0]  # most recent
        sma = sum(closes[:period]) / period
        return current > sma

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
