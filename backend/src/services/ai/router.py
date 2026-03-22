"""
AI analysis router -- confidence-based routing between local (Qwen) and cloud (Claude).

Routes tasks based on type and confidence thresholds:

- **Tier 1 (Local):** Sentiment, NER, headlines, alerts -> Qwen 122B (Claude Haiku fallback)
- **Tier 2 (Hybrid):** Filing analysis, earnings -> Qwen first, Claude Sonnet if low confidence
- **Tier 3 (Cloud):** Distressed eval, restructuring, novel situations -> Claude Opus always
- **5% spot-check:** Random local outputs verified by Opus for quality monitoring

All calls are audit-logged to PostgreSQL with model_id, prompt hash, input/output,
and routing decision.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from enum import StrEnum

from src.config import settings
from src.models.schemas import InsightCard
from src.services.ai.claude_client import ClaudeClient, HAIKU, SONNET, OPUS
from src.services.ai.ollama_client import OllamaClient
from src.services.ai.prompts import (
    SENTIMENT_SYSTEM,
    FILING_ANALYSIS_SYSTEM,
    DISTRESSED_EVAL_SYSTEM,
    INSIGHT_CARD_SYSTEM,
    EARNINGS_ANALYSIS_SYSTEM,
    SPOT_CHECK_SYSTEM,
    build_filing_prompt,
    build_insight_prompt,
    build_distressed_prompt,
    build_earnings_prompt,
    build_sentiment_prompt,
    build_spot_check_prompt,
)

# Re-export SignalResult for callers that import from the router.
from src.services.signals.volume import SignalResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AnalysisTask(StrEnum):
    """Types of analysis tasks the router can handle."""

    SENTIMENT = "sentiment"
    NER = "ner"
    HEADLINE = "headline"
    ALERT = "alert"
    FILING_ANALYSIS = "filing_analysis"
    EARNINGS = "earnings"
    REPORT = "report"
    DISTRESSED_EVAL = "distressed_eval"
    RESTRUCTURING = "restructuring"
    NOVEL_SITUATION = "novel_situation"


class AnalysisTier(StrEnum):
    """Routing tiers that determine which model handles the task."""

    TIER_1_LOCAL = "tier_1_local"
    TIER_2_HYBRID = "tier_2_hybrid"
    TIER_3_CLOUD = "tier_3_cloud"


# ---------------------------------------------------------------------------
# Task -> Tier mapping
# ---------------------------------------------------------------------------

TASK_TIER_MAP: dict[AnalysisTask, AnalysisTier] = {
    # Tier 1: Fast local tasks -- Qwen first, Haiku fallback
    AnalysisTask.SENTIMENT: AnalysisTier.TIER_1_LOCAL,
    AnalysisTask.NER: AnalysisTier.TIER_1_LOCAL,
    AnalysisTask.HEADLINE: AnalysisTier.TIER_1_LOCAL,
    AnalysisTask.ALERT: AnalysisTier.TIER_1_LOCAL,
    # Tier 2: Hybrid -- Qwen first, Sonnet if confidence < 0.65
    AnalysisTask.FILING_ANALYSIS: AnalysisTier.TIER_2_HYBRID,
    AnalysisTask.EARNINGS: AnalysisTier.TIER_2_HYBRID,
    AnalysisTask.REPORT: AnalysisTier.TIER_2_HYBRID,
    # Tier 3: Always cloud (Opus)
    AnalysisTask.DISTRESSED_EVAL: AnalysisTier.TIER_3_CLOUD,
    AnalysisTask.RESTRUCTURING: AnalysisTier.TIER_3_CLOUD,
    AnalysisTask.NOVEL_SITUATION: AnalysisTier.TIER_3_CLOUD,
}

# System prompts per task type
_TASK_SYSTEM_PROMPTS: dict[AnalysisTask, str] = {
    AnalysisTask.SENTIMENT: SENTIMENT_SYSTEM,
    AnalysisTask.NER: SENTIMENT_SYSTEM,  # NER uses same JSON structure
    AnalysisTask.HEADLINE: SENTIMENT_SYSTEM,
    AnalysisTask.ALERT: SENTIMENT_SYSTEM,
    AnalysisTask.FILING_ANALYSIS: FILING_ANALYSIS_SYSTEM,
    AnalysisTask.EARNINGS: EARNINGS_ANALYSIS_SYSTEM,
    AnalysisTask.REPORT: EARNINGS_ANALYSIS_SYSTEM,
    AnalysisTask.DISTRESSED_EVAL: DISTRESSED_EVAL_SYSTEM,
    AnalysisTask.RESTRUCTURING: DISTRESSED_EVAL_SYSTEM,
    AnalysisTask.NOVEL_SITUATION: DISTRESSED_EVAL_SYSTEM,
}

# Confidence threshold for Tier 2 escalation from local to cloud
_TIER2_ESCALATION_THRESHOLD = 0.65

# Spot-check probability (5%)
_SPOT_CHECK_RATE = 0.05

# Timeout for Tier 1 local calls (seconds)
_TIER1_LOCAL_TIMEOUT = 30.0

# Timeout for Tier 2 local calls (seconds)
_TIER2_LOCAL_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------


@dataclass
class AIResponse:
    """Unified response from the AI routing layer."""

    content: str
    confidence: float
    model: str
    tier: str
    reasoning: str
    structured_data: dict | None = None
    spot_checked: bool = False
    spot_check_agreed: bool | None = None
    latency_ms: float = 0.0
    escalated: bool = False
    escalation_reason: str | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class AIRouter:
    """
    Main AI routing engine.

    Dispatches analysis tasks to the appropriate model tier, handles
    confidence-based escalation, runs periodic spot-checks, and audit-logs
    every decision.

    Parameters
    ----------
    ollama_client:
        Client for local Qwen inference via Ollama.
    claude_client:
        Client for Claude API (Haiku / Sonnet / Opus).
    """

    def __init__(self, ollama_client: OllamaClient, claude_client: ClaudeClient) -> None:
        self._ollama = ollama_client
        self._claude = claude_client

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def analyze(
        self,
        task: AnalysisTask,
        content: str,
        context: dict | None = None,
    ) -> AIResponse:
        """
        Route an analysis task to the appropriate model tier.

        Parameters
        ----------
        task:
            The type of analysis to perform.
        content:
            The text or data to analyze.
        context:
            Optional additional context (symbol, filing_type, etc.).

        Returns
        -------
        AIResponse
            Unified response with routing metadata.
        """
        tier = TASK_TIER_MAP.get(task, AnalysisTier.TIER_3_CLOUD)
        system_prompt = _TASK_SYSTEM_PROMPTS.get(task, SENTIMENT_SYSTEM)
        context = context or {}

        t0 = time.monotonic()

        if tier == AnalysisTier.TIER_1_LOCAL:
            response = await self._route_tier1(task, content, system_prompt, context)
        elif tier == AnalysisTier.TIER_2_HYBRID:
            response = await self._route_tier2(task, content, system_prompt, context)
        else:
            response = await self._route_tier3(task, content, system_prompt, context)

        response.latency_ms = round((time.monotonic() - t0) * 1000, 1)

        # Spot-check Tier 1 and Tier 2 local results
        if (
            tier in (AnalysisTier.TIER_1_LOCAL, AnalysisTier.TIER_2_HYBRID)
            and not response.escalated
            and random.random() < _SPOT_CHECK_RATE
        ):
            response = await self._spot_check(response, content, task)

        # Audit log
        await self._audit_log(task, tier, content, response, context)

        return response

    # ------------------------------------------------------------------
    # Tier routing
    # ------------------------------------------------------------------

    async def _route_tier1(
        self,
        task: AnalysisTask,
        content: str,
        system_prompt: str,
        context: dict,
    ) -> AIResponse:
        """
        Tier 1: Try Qwen locally, fall back to Claude Haiku if unavailable.
        """
        # Try local Qwen first
        local_result = await self._ollama.generate(
            prompt=content,
            system=system_prompt,
            timeout_seconds=_TIER1_LOCAL_TIMEOUT,
        )

        if local_result is not None:
            confidence = self._ollama.extract_confidence(local_result.content)
            structured = self._try_parse_json(local_result.content)
            return AIResponse(
                content=local_result.content,
                confidence=confidence,
                model=local_result.model,
                tier=AnalysisTier.TIER_1_LOCAL,
                reasoning=f"Tier 1 local: {task.value} handled by Qwen ({local_result.tokens_per_second:.0f} tok/s)",
                structured_data=structured,
            )

        # Qwen unavailable -- fall back to Haiku
        logger.info("Tier 1 fallback: Qwen unavailable for %s, using Claude Haiku", task.value)
        claude_resp = await self._claude.analyze(
            prompt=content,
            model=HAIKU,
            system=system_prompt,
            max_tokens=2048,
        )
        structured = self._try_parse_json(claude_resp.content)
        return AIResponse(
            content=claude_resp.content,
            confidence=claude_resp.confidence,
            model=claude_resp.model,
            tier=AnalysisTier.TIER_1_LOCAL,
            reasoning=f"Tier 1 fallback: Qwen unavailable, used Haiku (${claude_resp.cost_estimate:.4f})",
            structured_data=structured,
            escalated=True,
            escalation_reason="qwen_unavailable",
        )

    async def _route_tier2(
        self,
        task: AnalysisTask,
        content: str,
        system_prompt: str,
        context: dict,
    ) -> AIResponse:
        """
        Tier 2: Try Qwen first, escalate to Claude Sonnet if confidence < 0.65.
        """
        # Try local Qwen first
        local_result = await self._ollama.generate(
            prompt=content,
            system=system_prompt,
            timeout_seconds=_TIER2_LOCAL_TIMEOUT,
        )

        if local_result is not None:
            confidence = self._ollama.extract_confidence(local_result.content)
            structured = self._try_parse_json(local_result.content)

            if confidence >= _TIER2_ESCALATION_THRESHOLD:
                return AIResponse(
                    content=local_result.content,
                    confidence=confidence,
                    model=local_result.model,
                    tier=AnalysisTier.TIER_2_HYBRID,
                    reasoning=(
                        f"Tier 2 local: {task.value} handled by Qwen "
                        f"(confidence {confidence:.2f} >= {_TIER2_ESCALATION_THRESHOLD})"
                    ),
                    structured_data=structured,
                )

            # Confidence too low -- escalate to Sonnet
            logger.info(
                "Tier 2 escalation: %s Qwen confidence %.2f < %.2f, escalating to Sonnet",
                task.value, confidence, _TIER2_ESCALATION_THRESHOLD,
            )

        # Either Qwen unavailable or confidence too low -- use Sonnet
        escalation_reason = "qwen_unavailable" if local_result is None else "low_confidence"
        claude_resp = await self._claude.analyze(
            prompt=content,
            model=SONNET,
            system=system_prompt,
            max_tokens=4096,
        )
        structured = self._try_parse_json(claude_resp.content)
        return AIResponse(
            content=claude_resp.content,
            confidence=claude_resp.confidence,
            model=claude_resp.model,
            tier=AnalysisTier.TIER_2_HYBRID,
            reasoning=(
                f"Tier 2 cloud: {task.value} escalated to Sonnet "
                f"({escalation_reason}, ${claude_resp.cost_estimate:.4f})"
            ),
            structured_data=structured,
            escalated=True,
            escalation_reason=escalation_reason,
        )

    async def _route_tier3(
        self,
        task: AnalysisTask,
        content: str,
        system_prompt: str,
        context: dict,
    ) -> AIResponse:
        """
        Tier 3: Always Claude Opus.
        """
        claude_resp = await self._claude.analyze(
            prompt=content,
            model=OPUS,
            system=system_prompt,
            max_tokens=8192,
            temperature=0.2,
        )
        structured = self._try_parse_json(claude_resp.content)
        return AIResponse(
            content=claude_resp.content,
            confidence=claude_resp.confidence,
            model=claude_resp.model,
            tier=AnalysisTier.TIER_3_CLOUD,
            reasoning=f"Tier 3 cloud: {task.value} handled by Opus (${claude_resp.cost_estimate:.4f})",
            structured_data=structured,
        )

    # ------------------------------------------------------------------
    # Spot-checking
    # ------------------------------------------------------------------

    async def _spot_check(
        self,
        original: AIResponse,
        original_input: str,
        task: AnalysisTask,
    ) -> AIResponse:
        """
        Run a 5% spot-check: re-analyze with Opus and compare.

        Modifies the original response in-place with spot-check metadata.
        """
        logger.info("Spot-checking %s result from %s", task.value, original.model)

        try:
            prompt = build_spot_check_prompt(original_input, original.content, task.value)
            check_resp = await self._claude.analyze(
                prompt=prompt,
                model=OPUS,
                system=SPOT_CHECK_SYSTEM,
                max_tokens=2048,
            )

            check_data = self._try_parse_json(check_resp.content)
            agreed = True
            if check_data:
                agreed = check_data.get("agrees", True)
                issues = check_data.get("issues", [])
                critical_issues = [i for i in issues if i.get("severity") == "critical"]
                if critical_issues:
                    logger.warning(
                        "Spot-check found %d critical issues in %s analysis: %s",
                        len(critical_issues), task.value,
                        [i.get("issue") for i in critical_issues],
                    )

            original.spot_checked = True
            original.spot_check_agreed = agreed
            return original

        except Exception:
            logger.exception("Spot-check failed for %s", task.value)
            original.spot_checked = True
            original.spot_check_agreed = None  # Inconclusive
            return original

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def generate_insight_card(
        self,
        symbol: str,
        signals: list[SignalResult],
        market_data: dict,
    ) -> InsightCard:
        """
        Synthesize multiple signals into a structured InsightCard.

        Uses Tier 2 routing: Qwen first, Sonnet if confidence is low.
        """
        signal_dicts = [
            {
                "signal_type": s.signal_type.value,
                "score": s.score,
                "confidence": s.confidence,
                "reasoning": s.reasoning,
            }
            for s in signals
        ]
        prompt = build_insight_prompt(symbol, signal_dicts, market_data)

        # Try via general router for tier-based routing
        response = await self.analyze(AnalysisTask.REPORT, prompt, context={"symbol": symbol})

        # Parse into InsightCard
        if response.structured_data:
            data = response.structured_data
            return InsightCard(
                title=data.get("title", f"Analysis for {symbol}"),
                ticker=symbol,
                score=max(0.0, min(10.0, float(data.get("score", 5.0)))),
                pros=data.get("pros", []),
                cons=data.get("cons", []),
                recommendation=data.get("recommendation", "hold"),
                confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                model=response.model,
            )

        # Fallback: use Claude directly if parsing failed
        logger.warning("InsightCard parsing failed for %s, falling back to direct Claude call", symbol)
        return await self._claude.generate_insight(symbol, prompt)

    async def analyze_filing(
        self,
        filing_text: str,
        filing_type: str,
        symbol: str,
    ) -> AIResponse:
        """
        Specialized filing analysis.

        Builds a filing-specific prompt and routes through the standard
        Tier 2 pipeline (Qwen first, Sonnet on low confidence).
        """
        prompt = build_filing_prompt(filing_text, filing_type, symbol)
        return await self.analyze(
            AnalysisTask.FILING_ANALYSIS,
            prompt,
            context={"symbol": symbol, "filing_type": filing_type},
        )

    async def assess_distressed(
        self,
        symbol: str,
        financial_data: dict,
        filing_data: dict,
    ) -> AIResponse:
        """
        Deep distressed evaluation -- always Tier 3 (Opus).

        Parameters
        ----------
        symbol:
            Ticker symbol.
        financial_data:
            Dict of financial metrics (cash, debt, revenue, etc.).
        filing_data:
            Dict with filing summaries and any Z-score data.
        """
        z_score = filing_data.get("z_score")
        filing_summaries = filing_data.get("summaries", [])
        insider_data = filing_data.get("insider_data")

        prompt = build_distressed_prompt(
            symbol,
            z_score=z_score,
            financials=financial_data,
            filings=filing_summaries,
            insider_data=insider_data,
        )

        return await self.analyze(
            AnalysisTask.DISTRESSED_EVAL,
            prompt,
            context={
                "symbol": symbol,
                "z_score": z_score,
            },
        )

    async def analyze_earnings(
        self,
        symbol: str,
        earnings_text: str,
        prior_quarter: dict | None = None,
        consensus: dict | None = None,
    ) -> AIResponse:
        """
        Earnings analysis via Tier 2 routing.
        """
        prompt = build_earnings_prompt(symbol, earnings_text, prior_quarter, consensus)
        return await self.analyze(
            AnalysisTask.EARNINGS,
            prompt,
            context={"symbol": symbol},
        )

    async def analyze_sentiment(
        self,
        text: str,
        symbol: str | None = None,
    ) -> AIResponse:
        """
        Sentiment classification via Tier 1 routing (Qwen, Haiku fallback).
        """
        prompt = build_sentiment_prompt(text, symbol)
        return await self.analyze(
            AnalysisTask.SENTIMENT,
            prompt,
            context={"symbol": symbol} if symbol else None,
        )

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    async def _audit_log(
        self,
        task: AnalysisTask,
        tier: AnalysisTier,
        content: str,
        response: AIResponse,
        context: dict,
    ) -> None:
        """
        Write an audit log entry to PostgreSQL.

        Non-blocking: logs errors but never raises to the caller.
        """
        try:
            from src.db import get_db_pool

            pool = get_db_pool()
            prompt_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            # Build a compact input snapshot (truncate large content)
            input_snapshot = {
                "task": task.value,
                "tier": tier.value,
                "content_length": len(content),
                "content_preview": content[:500] if len(content) > 500 else content,
                "context": context,
            }
            output_snapshot = {
                "confidence": response.confidence,
                "model": response.model,
                "escalated": response.escalated,
                "escalation_reason": response.escalation_reason,
                "spot_checked": response.spot_checked,
                "spot_check_agreed": response.spot_check_agreed,
                "latency_ms": response.latency_ms,
                "content_preview": response.content[:500] if len(response.content) > 500 else response.content,
            }

            decision = (
                f"{tier.value}:{response.model}"
                + (f" (escalated: {response.escalation_reason})" if response.escalated else "")
            )

            await pool.execute(
                """
                INSERT INTO audit_log (action, model_id, prompt_hash, input_snapshot, output, decision)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6)
                """,
                f"ai:{task.value}",
                response.model,
                prompt_hash,
                json.dumps(input_snapshot),
                json.dumps(output_snapshot),
                decision,
            )

        except Exception:
            # Audit logging must never break the analysis pipeline.
            logger.debug("Failed to write AI audit log", exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """Attempt to parse a string as JSON.  Returns None on failure."""
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None
