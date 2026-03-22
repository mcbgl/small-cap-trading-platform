"""
Technical analysis convergence detection.

Bollinger Band squeeze + RSI oversold + MACD bullish crossover = high-confidence long.
Band squeeze (narrow bandwidth) precedes explosive small-cap moves.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.db import QuestDBClient
from src.models.schemas import SignalType
from src.services.signals.volume import SignalResult

logger = logging.getLogger(__name__)


# =====================================================================
# Indicator calculations
# =====================================================================

def calc_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder-smoothed RSI.

    Returns a Series of RSI values (0-100).
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def calc_bollinger(
    close: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    Returns ``(middle, upper, lower, bandwidth)``.
    Bandwidth = (upper - lower) / middle.
    """
    middle = calc_sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    bandwidth = (upper - lower) / middle.replace(0, np.nan)
    return middle, upper, lower, bandwidth


def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD indicator.

    Returns ``(macd_line, signal_line, histogram)``.
    """
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# =====================================================================
# TechnicalSignal class
# =====================================================================

class TechnicalSignal:
    """
    Detect technical convergence patterns that precede explosive moves.

    Combines Bollinger Band squeeze, RSI oversold, MACD bullish crossover,
    and SMA crossover into a single composite score.
    """

    # Minimum bars needed for reliable analysis
    _MIN_BARS = 60

    def __init__(self, questdb: QuestDBClient) -> None:
        self._qdb = questdb

    # ------------------------------------------------------------------
    # Single-symbol analysis
    # ------------------------------------------------------------------

    async def analyze(self, symbol: str) -> SignalResult | None:
        """
        Run technical convergence analysis for *symbol*.

        Scoring breakdown:
          - Bollinger squeeze              => base 3
          - + RSI < 30                     => +2
          - + MACD bullish crossover       => +2
          - + SMA 20 > SMA 50             => +1
          - + Price near lower Bollinger   => +1
          - + Volume confirmation RVOL>1.5 => +1
        """
        sym = symbol.upper()

        # ---- Fetch OHLCV data from QuestDB ----
        df = await self._fetch_ohlcv(sym, days=90)
        if df is None or len(df) < self._MIN_BARS:
            logger.debug(
                "Insufficient OHLCV data for %s (%d bars)",
                sym,
                len(df) if df is not None else 0,
            )
            return None

        close = df["close"]
        volume = df["volume"]

        # ---- Compute indicators ----
        bb_mid, bb_upper, bb_lower, bb_bandwidth = calc_bollinger(close)
        rsi = calc_rsi(close)
        macd_line, signal_line, macd_hist = calc_macd(close)
        sma_20 = calc_sma(close, 20)
        sma_50 = calc_sma(close, 50)

        # Current (latest) values
        latest = len(df) - 1
        prev = latest - 1

        current_close = close.iloc[latest]
        current_rsi = rsi.iloc[latest]
        current_bandwidth = bb_bandwidth.iloc[latest]
        current_bb_lower = bb_lower.iloc[latest]
        current_bb_upper = bb_upper.iloc[latest]
        current_bb_mid = bb_mid.iloc[latest]
        current_macd = macd_line.iloc[latest]
        current_signal = signal_line.iloc[latest]
        prev_macd = macd_line.iloc[prev]
        prev_signal = signal_line.iloc[prev]
        current_sma20 = sma_20.iloc[latest]
        current_sma50 = sma_50.iloc[latest]

        # Average bandwidth for squeeze detection
        avg_bandwidth = bb_bandwidth.iloc[-20:].mean()

        # Volume RVOL (simple 20d average ratio)
        avg_vol_20d = volume.iloc[-20:].mean()
        current_vol = volume.iloc[latest]
        rvol = current_vol / avg_vol_20d if avg_vol_20d > 0 else 0.0

        # ---- Score ----
        score = 0.0
        reasons: list[str] = []
        indicators: dict[str, object] = {}

        # Bollinger squeeze
        is_squeeze = (
            not np.isnan(current_bandwidth)
            and not np.isnan(avg_bandwidth)
            and current_bandwidth < avg_bandwidth * 0.8
        )
        indicators["bollinger_squeeze"] = is_squeeze
        if is_squeeze:
            score += 3.0
            reasons.append(
                f"Bollinger squeeze (BW {current_bandwidth:.4f} vs avg {avg_bandwidth:.4f})"
            )

        # RSI oversold
        indicators["rsi"] = round(float(current_rsi), 2) if not np.isnan(current_rsi) else None
        if not np.isnan(current_rsi) and current_rsi < 30:
            score += 2.0
            reasons.append(f"RSI oversold at {current_rsi:.1f}")

        # MACD bullish crossover
        macd_crossover = (
            not np.isnan(current_macd)
            and not np.isnan(prev_macd)
            and prev_macd <= prev_signal
            and current_macd > current_signal
        )
        indicators["macd_crossover"] = macd_crossover
        if macd_crossover:
            score += 2.0
            reasons.append("MACD bullish crossover")

        # SMA crossover (20 > 50)
        sma_bullish = (
            not np.isnan(current_sma20)
            and not np.isnan(current_sma50)
            and current_sma20 > current_sma50
        )
        indicators["sma_20_above_50"] = sma_bullish
        if sma_bullish:
            score += 1.0
            reasons.append(
                f"SMA 20 ({current_sma20:.2f}) > SMA 50 ({current_sma50:.2f})"
            )

        # Price near lower Bollinger (within 5%)
        near_lower = False
        if not np.isnan(current_bb_lower) and current_bb_lower > 0:
            dist_pct = (current_close - current_bb_lower) / current_bb_lower * 100
            near_lower = dist_pct < 5.0
            indicators["pct_from_lower_bb"] = round(dist_pct, 2)
        if near_lower:
            score += 1.0
            reasons.append("Price near lower Bollinger band")

        # Volume confirmation
        indicators["rvol"] = round(rvol, 2)
        if rvol >= 1.5:
            score += 1.0
            reasons.append(f"Volume confirmation (RVOL {rvol:.1f}x)")

        if score == 0:
            return None

        score = min(round(score, 1), 10.0)

        # ---- Confidence ----
        # More confirming indicators = higher confidence
        confirming = sum(
            1
            for v in [is_squeeze, macd_crossover, sma_bullish, near_lower]
            if v
        )
        data_quality = min(len(df) / 90, 1.0)  # 90 bars = full quality
        confidence = round(
            min(0.4 + confirming * 0.1 + data_quality * 0.15, 0.95), 2
        )

        return SignalResult(
            symbol=sym,
            signal_type=SignalType.TECHNICAL,
            score=score,
            confidence=confidence,
            reasoning=". ".join(reasons),
            metadata={
                "close": round(float(current_close), 4),
                "rsi": indicators.get("rsi"),
                "bollinger_squeeze": is_squeeze,
                "bollinger_bandwidth": (
                    round(float(current_bandwidth), 4)
                    if not np.isnan(current_bandwidth)
                    else None
                ),
                "macd_crossover": macd_crossover,
                "sma_20_above_50": sma_bullish,
                "near_lower_bb": near_lower,
                "rvol": round(rvol, 2),
                "bars_available": len(df),
            },
        )

    # ------------------------------------------------------------------
    # Batch scan
    # ------------------------------------------------------------------

    async def scan(self, symbols: list[str]) -> list[SignalResult]:
        """Run technical analysis on a batch of symbols, return scored results."""
        results: list[SignalResult] = []
        for sym in symbols:
            try:
                result = await self.analyze(sym)
                if result:
                    results.append(result)
            except Exception:
                logger.exception("Technical analysis failed for %s", sym)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    async def _fetch_ohlcv(self, symbol: str, days: int = 90) -> pd.DataFrame | None:
        """
        Fetch daily OHLCV data from QuestDB for the last *days* trading days.

        Returns a DataFrame with columns: ``timestamp, open, high, low, close, volume``
        sorted by timestamp ascending.  Returns ``None`` on failure or empty data.
        """
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM ohlcv_1d
            WHERE symbol = '{symbol}'
            ORDER BY timestamp DESC
            LIMIT {days}
        """
        try:
            resp = await self._qdb.query(query)
        except Exception:
            logger.exception("QuestDB OHLCV query failed for %s", symbol)
            return None

        columns_meta = resp.get("columns", [])
        dataset = resp.get("dataset", [])

        if not dataset:
            return None

        col_names = [c["name"] for c in columns_meta]
        df = pd.DataFrame(dataset, columns=col_names)

        # Ensure numeric types
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Sort ascending by time
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp").reset_index(drop=True)

        return df
