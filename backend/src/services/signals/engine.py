"""
Signal engine orchestrator.

Runs all signal modules on schedule, aggregates results, scores opportunities,
and generates composite AI signals. Publishes to Redis and stores in PostgreSQL.
"""

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone

from src.config import settings
from src.db import QuestDBClient, get_db_pool, get_redis
from src.models.schemas import InsightCard, SignalType
from src.services.data.finra_short import FinraShortInterest
from src.services.signals.distressed import DistressedSignal
from src.services.signals.insider import InsiderSignal
from src.services.signals.squeeze import SqueezeSignal
from src.services.signals.technical import TechnicalSignal
from src.services.signals.volume import SignalResult, VolumeSignal

logger = logging.getLogger(__name__)

# ── Composite scoring weights ───────────────────────────────────────
SIGNAL_WEIGHTS: dict[SignalType, float] = {
    SignalType.VOLUME: 1.5,
    SignalType.SQUEEZE: 2.0,
    SignalType.INSIDER: 2.0,
    SignalType.TECHNICAL: 1.0,
    SignalType.DISTRESSED: 1.5,
}

# Thresholds
PUBLISH_THRESHOLD = 6.0   # publish to Redis channel
INSIGHT_THRESHOLD = 7.0   # generate InsightCard
DEDUP_WINDOW_SECS = 3600  # 1 hour


class SignalEngine:
    """
    Central orchestrator that runs all signal modules, computes composite
    scores, persists results, and publishes actionable alerts.
    """

    def __init__(self, questdb: QuestDBClient) -> None:
        self._qdb = questdb

        # Instantiate signal modules
        self._finra = FinraShortInterest()
        self._volume = VolumeSignal(questdb)
        self._squeeze = SqueezeSignal(self._finra, self._volume, questdb)
        self._insider = InsiderSignal()
        self._technical = TechnicalSignal(questdb)
        self._distressed = DistressedSignal()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Initialise underlying clients."""
        await self._finra.init()
        logger.info("SignalEngine initialised")

    async def close(self) -> None:
        """Clean up resources."""
        await self._finra.close()
        logger.info("SignalEngine closed")

    # ------------------------------------------------------------------
    # Full scan (all modules)
    # ------------------------------------------------------------------

    async def run_scan(self, symbols: list[str]) -> dict[str, list[SignalResult]]:
        """
        Run ALL signal modules for each symbol in *symbols*.

        Returns ``{symbol: [SignalResult, ...]}``.
        """
        all_results: dict[str, list[SignalResult]] = {}
        t0 = time.monotonic()

        for sym in symbols:
            try:
                results = await self.run_single(sym)
                if results:
                    all_results[sym] = results
            except Exception:
                logger.exception("Signal scan failed for %s", sym)

        elapsed = time.monotonic() - t0
        total_signals = sum(len(v) for v in all_results.values())
        logger.info(
            "Full scan complete: %d symbols, %d signals in %.1fs",
            len(symbols),
            total_signals,
            elapsed,
        )
        return all_results

    # ------------------------------------------------------------------
    # Quick scan (volume + squeeze only)
    # ------------------------------------------------------------------

    async def run_quick_scan(
        self, symbols: list[str]
    ) -> dict[str, list[SignalResult]]:
        """
        Run only volume and squeeze modules — the fastest detectable signals.

        Used for the 5-minute intraday sweep.
        """
        all_results: dict[str, list[SignalResult]] = {}
        t0 = time.monotonic()

        for sym in symbols:
            sym_results: list[SignalResult] = []
            try:
                vol = await self._volume.analyze(sym)
                if vol:
                    sym_results.append(vol)

                sqz = await self._squeeze.analyze(sym)
                if sqz:
                    sym_results.append(sqz)

                if sym_results:
                    # Store, publish, dedup
                    for r in sym_results:
                        await self._process_result(r)
                    all_results[sym] = sym_results
            except Exception:
                logger.exception("Quick scan failed for %s", sym)

        elapsed = time.monotonic() - t0
        total = sum(len(v) for v in all_results.values())
        logger.info(
            "Quick scan complete: %d symbols, %d signals in %.1fs",
            len(symbols),
            total,
            elapsed,
        )
        return all_results

    # ------------------------------------------------------------------
    # Single-symbol (all modules)
    # ------------------------------------------------------------------

    async def run_single(self, symbol: str) -> list[SignalResult]:
        """
        Run all signal modules for a single *symbol*, compute composite
        score, store and publish results.

        Returns the list of individual + composite ``SignalResult`` objects.
        """
        sym = symbol.upper()
        results: list[SignalResult] = []

        # Run each module, collecting results
        modules: list[tuple[str, object]] = [
            ("volume", self._volume),
            ("squeeze", self._squeeze),
            ("insider", self._insider),
            ("technical", self._technical),
            ("distressed", self._distressed),
        ]

        for name, module in modules:
            try:
                result = await module.analyze(sym)
                if result:
                    results.append(result)
            except Exception:
                logger.exception("Module %s failed for %s", name, sym)

        if not results:
            return []

        # Process each individual signal
        for r in results:
            await self._process_result(r)

        # Compute composite
        composite = self._compute_composite(sym, results)
        if composite:
            await self._process_result(composite)
            results.append(composite)

        return results

    # ------------------------------------------------------------------
    # Composite scoring
    # ------------------------------------------------------------------

    def _compute_composite(
        self, symbol: str, signals: list[SignalResult]
    ) -> SignalResult | None:
        """
        Compute a weighted composite score from individual signal results.

        Weights: volume=1.5, squeeze=2.0, insider=2.0, technical=1.0, distressed=1.5.
        Composite score capped at 10.  Composite confidence = weighted average.
        """
        if not signals:
            return None

        weighted_score_sum = 0.0
        weighted_conf_sum = 0.0
        total_weight = 0.0
        contributing: list[str] = []

        for sig in signals:
            weight = SIGNAL_WEIGHTS.get(sig.signal_type, 1.0)
            weighted_score_sum += sig.score * weight
            weighted_conf_sum += sig.confidence * weight
            total_weight += weight
            contributing.append(
                f"{sig.signal_type.value}={sig.score:.1f}"
            )

        if total_weight == 0:
            return None

        raw_score = weighted_score_sum / total_weight
        composite_score = round(min(raw_score, 10.0), 1)
        composite_confidence = round(weighted_conf_sum / total_weight, 2)

        reasoning = (
            f"Composite from {len(signals)} signals: "
            + ", ".join(contributing)
        )

        return SignalResult(
            symbol=symbol,
            signal_type=SignalType.AI_COMPOSITE,
            score=composite_score,
            confidence=composite_confidence,
            reasoning=reasoning,
            metadata={
                "contributing_signals": len(signals),
                "signal_breakdown": {
                    s.signal_type.value: {
                        "score": s.score,
                        "confidence": s.confidence,
                    }
                    for s in signals
                },
                "total_weight": round(total_weight, 2),
            },
        )

    # ------------------------------------------------------------------
    # Process a single result: dedup, store, publish, insight
    # ------------------------------------------------------------------

    async def _process_result(self, result: SignalResult) -> None:
        """Store, publish, and optionally generate an InsightCard for a result."""
        # Dedup check
        if await self._is_duplicate(result):
            logger.debug(
                "Duplicate signal %s/%s — skipping",
                result.symbol,
                result.signal_type.value,
            )
            return

        # Persist
        await self._store_signal(result)

        # Mark as seen for dedup
        await self._mark_seen(result)

        # Publish high-scoring signals
        if result.score >= PUBLISH_THRESHOLD:
            await self._publish_signal(result)

        # Generate InsightCard for very high signals
        if result.score >= INSIGHT_THRESHOLD:
            card = self._generate_insight_card(result)
            await self._store_insight_card(card)

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    async def _is_duplicate(self, result: SignalResult) -> bool:
        """Check whether we already emitted this signal type for this ticker recently."""
        redis = get_redis()
        key = f"signal:dedup:{result.symbol}:{result.signal_type.value}"
        return await redis.exists(key) > 0

    async def _mark_seen(self, result: SignalResult) -> None:
        """Record the signal in Redis with a TTL for dedup."""
        redis = get_redis()
        key = f"signal:dedup:{result.symbol}:{result.signal_type.value}"
        await redis.setex(key, DEDUP_WINDOW_SECS, "1")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _store_signal(self, result: SignalResult) -> None:
        """Insert the signal into the PostgreSQL ``signals`` table."""
        pool = get_db_pool()
        try:
            await pool.execute(
                """
                INSERT INTO signals (
                    symbol, signal_type, score, confidence,
                    reasoning, metadata, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
                """,
                result.symbol,
                result.signal_type.value,
                result.score,
                result.confidence,
                result.reasoning,
                json.dumps(result.metadata),
            )
        except Exception:
            logger.exception("Failed to store signal for %s", result.symbol)

    # ------------------------------------------------------------------
    # Redis publishing
    # ------------------------------------------------------------------

    async def _publish_signal(self, result: SignalResult) -> None:
        """Publish a high-scoring signal to the ``channel:signals`` Redis channel."""
        redis = get_redis()
        payload = {
            "symbol": result.symbol,
            "signal_type": result.signal_type.value,
            "score": result.score,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "metadata": result.metadata,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis.publish("channel:signals", json.dumps(payload))
        logger.info(
            "Published signal %s/%s (score %.1f) to channel:signals",
            result.symbol,
            result.signal_type.value,
            result.score,
        )

    # ------------------------------------------------------------------
    # InsightCard generation
    # ------------------------------------------------------------------

    def _generate_insight_card(self, result: SignalResult) -> InsightCard:
        """Generate an InsightCard for a high-scoring signal."""
        # Build pros/cons from the signal metadata
        pros: list[str] = []
        cons: list[str] = []

        # Parse reasoning into pros
        for part in result.reasoning.split(". "):
            part = part.strip()
            if not part:
                continue
            # Heuristic: negative words go to cons
            lower = part.lower()
            if any(w in lower for w in ("caution", "avoid", "overbought", "below", "no positive")):
                cons.append(part)
            else:
                pros.append(part)

        # Add metadata-driven observations
        meta = result.metadata
        if meta.get("early_signal"):
            pros.append("Volume spike before price move (early entry)")
        if meta.get("insider_buying"):
            pros.append("Insider buying confirms conviction")
        if meta.get("z_zone") == "distress" and meta.get("positive_catalysts", 0) == 0:
            cons.append("Distressed with no turnaround catalyst")

        if result.confidence < settings.ai_confidence_min:
            recommendation = "Monitor — confidence below threshold"
        elif result.score >= 8.0:
            recommendation = "Strong opportunity — consider position sizing"
        elif result.score >= 7.0:
            recommendation = "Emerging opportunity — add to watchlist and monitor"
        else:
            recommendation = "Notable signal — watch for confirmation"

        return InsightCard(
            title=f"{result.signal_type.value.replace('_', ' ').title()} signal: {result.symbol}",
            ticker=result.symbol,
            score=result.score,
            pros=pros[:5],
            cons=cons[:3],
            recommendation=recommendation,
            confidence=result.confidence,
            model="signal_engine_v1",
        )

    async def _store_insight_card(self, card: InsightCard) -> None:
        """Persist an InsightCard to PostgreSQL."""
        pool = get_db_pool()
        try:
            await pool.execute(
                """
                INSERT INTO insight_cards (
                    title, ticker, score, pros, cons,
                    recommendation, confidence, model, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                card.title,
                card.ticker,
                card.score,
                card.pros,
                card.cons,
                card.recommendation,
                card.confidence,
                card.model,
            )
            logger.info("Stored InsightCard for %s (score %.1f)", card.ticker, card.score)
        except Exception:
            logger.exception("Failed to store InsightCard for %s", card.ticker)
