"""
Claude API client for cloud AI analysis.

Uses the Anthropic SDK for structured JSON output with retry and exponential
backoff.  Three model tiers are available:

- **Haiku** -- fast and inexpensive, used as fallback for Tier 1 local tasks.
- **Sonnet** -- balanced cost/quality, used for Tier 2 hybrid escalation.
- **Opus** -- highest quality, used for Tier 3 deep analysis and spot-checks.

Cost tracking is performed per-call and accumulated monthly in Redis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import anthropic

from src.config import settings
from src.models.schemas import InsightCard

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model constants  (updated to latest production model IDs)
# ---------------------------------------------------------------------------

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6-20250131"
OPUS = "claude-opus-4-6-20250115"

# ---------------------------------------------------------------------------
# Pricing per 1 M tokens  (USD, as of early 2026)
# ---------------------------------------------------------------------------

_PRICING: dict[str, dict[str, float]] = {
    HAIKU:  {"input": 0.80,  "output": 4.00},
    SONNET: {"input": 3.00,  "output": 15.00},
    OPUS:   {"input": 15.00, "output": 75.00},
}

# Retry parameters
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubles each attempt


@dataclass
class ClaudeResponse:
    """Structured response from a Claude API call."""

    content: str
    model: str
    confidence: float
    input_tokens: int
    output_tokens: int
    cost_estimate: float


class ClaudeClient:
    """
    Async client for the Anthropic Messages API.

    Provides convenience methods for common analysis tasks, automatic retry
    with exponential backoff, structured JSON output, and per-call cost
    tracking with monthly accumulation in Redis.
    """

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            logger.warning("No Anthropic API key configured -- ClaudeClient will be non-functional")
        self._client = anthropic.AsyncAnthropic(api_key=key) if key else None
        self._redis = None  # Lazy-initialised on first cost write

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the client has a valid API key configured."""
        return self._client is not None

    async def _get_redis(self):
        """Lazy-load Redis for cost tracking.  Never raises."""
        if self._redis is None:
            try:
                from src.db import get_redis
                self._redis = get_redis()
            except Exception:
                logger.debug("Redis not available for cost tracking")
        return self._redis

    # ------------------------------------------------------------------
    # Core API call with retry
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        *,
        model: str,
        system: str | None,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> anthropic.types.Message:
        """
        Low-level Messages API call with exponential-backoff retry.

        Retries on rate-limit (429), overloaded (529), and transient 5xx
        errors.  Raises on non-retryable errors.
        """
        if not self._client:
            raise RuntimeError("ClaudeClient has no API key -- cannot make requests")

        messages = [{"role": "user", "content": user_prompt}]
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(**kwargs)
                return response

            except anthropic.RateLimitError as exc:
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Claude rate-limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)

            except anthropic.InternalServerError as exc:
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Claude server error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _MAX_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)

            except anthropic.APIStatusError as exc:
                if exc.status_code == 529:  # Overloaded
                    last_exc = exc
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Claude overloaded (attempt %d/%d), retrying in %.1fs",
                        attempt + 1, _MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Cost estimation & tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost for a single API call."""
        pricing = _PRICING.get(model, _PRICING[SONNET])
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
        return round(cost, 6)

    async def _track_cost(self, model: str, cost: float) -> None:
        """Accumulate cost in Redis under a monthly key.  Never raises."""
        try:
            redis = await self._get_redis()
            if redis is None:
                return
            month_key = f"ai:cost:{datetime.now(timezone.utc).strftime('%Y-%m')}"
            model_key = f"ai:cost:{model}:{datetime.now(timezone.utc).strftime('%Y-%m')}"
            await redis.incrbyfloat(month_key, cost)
            await redis.incrbyfloat(model_key, cost)
            # Expire after 90 days so old months don't pile up.
            await redis.expire(month_key, 90 * 86400)
            await redis.expire(model_key, 90 * 86400)
        except Exception:
            logger.debug("Failed to track AI cost in Redis", exc_info=True)

    async def get_monthly_cost(self, month: str | None = None) -> dict:
        """
        Return accumulated cost for the given month (``YYYY-MM``).

        Returns a dict like ``{"total": 12.34, "by_model": {"claude-sonnet-...": 8.0, ...}}``.
        """
        month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        result: dict = {"month": month, "total": 0.0, "by_model": {}}
        try:
            redis = await self._get_redis()
            if redis is None:
                return result
            total = await redis.get(f"ai:cost:{month}")
            result["total"] = round(float(total), 4) if total else 0.0
            for model_id in (HAIKU, SONNET, OPUS):
                val = await redis.get(f"ai:cost:{model_id}:{month}")
                if val:
                    result["by_model"][model_id] = round(float(val), 4)
        except Exception:
            logger.debug("Failed to read AI cost from Redis", exc_info=True)
        return result

    # ------------------------------------------------------------------
    # High-level analysis methods
    # ------------------------------------------------------------------

    async def analyze(
        self,
        prompt: str,
        *,
        model: str = SONNET,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> ClaudeResponse:
        """
        General-purpose analysis call.

        The system prompt should instruct the model to return JSON with a
        ``confidence`` field.  If the response is valid JSON with a
        ``confidence`` key, it is extracted automatically; otherwise
        confidence defaults to 0.0.
        """
        t0 = time.monotonic()
        response = await self._call_api(
            model=model,
            system=system,
            user_prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        elapsed = time.monotonic() - t0

        content = response.content[0].text if response.content else ""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = self._estimate_cost(model, input_tokens, output_tokens)

        # Extract confidence from JSON response
        confidence = 0.0
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "confidence" in parsed:
                confidence = max(0.0, min(1.0, float(parsed["confidence"])))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        logger.info(
            "Claude %s completed in %.1fs — %d in / %d out tokens — $%.4f",
            model.split("-")[1] if "-" in model else model,
            elapsed, input_tokens, output_tokens, cost,
        )

        await self._track_cost(model, cost)

        return ClaudeResponse(
            content=content,
            model=model,
            confidence=confidence,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=cost,
        )

    async def analyze_structured(
        self,
        prompt: str,
        response_schema: dict,
        *,
        model: str = SONNET,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> dict:
        """
        Force structured JSON output matching the given schema.

        Wraps the schema description into the system prompt so the model is
        instructed to respond with JSON conforming to the expected structure.
        Parses the response and returns a dict.

        Raises ``ValueError`` if the response is not valid JSON.
        """
        schema_instruction = (
            "You MUST respond with valid JSON matching this schema:\n"
            f"{json.dumps(response_schema, indent=2)}\n\n"
            "Do NOT include any text outside the JSON object."
        )
        full_system = f"{system}\n\n{schema_instruction}" if system else schema_instruction

        resp = await self.analyze(
            prompt,
            model=model,
            system=full_system,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        try:
            parsed = json.loads(resp.content)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
        except json.JSONDecodeError as exc:
            logger.warning("Claude returned non-JSON response: %s", resp.content[:200])
            raise ValueError(f"Claude response is not valid JSON: {exc}") from exc

    async def generate_insight(
        self,
        symbol: str,
        context: str,
        *,
        model: str = SONNET,
    ) -> InsightCard:
        """
        Generate an InsightCard for a ticker using AI analysis.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        context:
            Pre-formatted context string (signals, market data, etc.).
        model:
            Claude model to use.

        Returns
        -------
        InsightCard
            Validated Pydantic model.
        """
        from src.services.ai.prompts import INSIGHT_CARD_SYSTEM

        resp = await self.analyze(
            context,
            model=model,
            system=INSIGHT_CARD_SYSTEM,
            max_tokens=2048,
        )

        try:
            data = json.loads(resp.content)
        except json.JSONDecodeError:
            logger.warning("Insight generation returned non-JSON for %s", symbol)
            # Return a minimal card instead of crashing.
            return InsightCard(
                title=f"Analysis for {symbol}",
                ticker=symbol,
                score=5.0,
                pros=["AI analysis completed"],
                cons=["Could not parse structured output"],
                recommendation="hold",
                confidence=0.3,
                model=model,
            )

        return InsightCard(
            title=data.get("title", f"Analysis for {symbol}"),
            ticker=symbol,
            score=max(0.0, min(10.0, float(data.get("score", 5.0)))),
            pros=data.get("pros", []),
            cons=data.get("cons", []),
            recommendation=data.get("recommendation", "hold"),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
            model=model,
        )

    async def assess_filing(
        self,
        text: str,
        filing_type: str,
        symbol: str,
        *,
        model: str = SONNET,
    ) -> ClaudeResponse:
        """
        Analyze an SEC filing with a filing-specific system prompt.

        Parameters
        ----------
        text:
            Filing text or excerpt.
        filing_type:
            SEC form type (10-K, 10-Q, 8-K, etc.).
        symbol:
            Ticker symbol.
        model:
            Claude model to use.

        Returns
        -------
        ClaudeResponse
        """
        from src.services.ai.prompts import FILING_ANALYSIS_SYSTEM, build_filing_prompt

        prompt = build_filing_prompt(text, filing_type, symbol)
        return await self.analyze(
            prompt,
            model=model,
            system=FILING_ANALYSIS_SYSTEM,
            max_tokens=4096,
        )

    async def deep_distressed_eval(
        self,
        symbol: str,
        financial_data: dict,
        filing_summaries: list[dict],
        *,
        z_score: float | None = None,
        insider_data: dict | None = None,
    ) -> ClaudeResponse:
        """
        Comprehensive distressed-asset evaluation.  Always uses Opus.

        Parameters
        ----------
        symbol:
            Ticker symbol.
        financial_data:
            Dict of financial metrics.
        filing_summaries:
            List of recent filing summary dicts.
        z_score:
            Altman Z-Score, if computed.
        insider_data:
            Insider transaction summary, if available.

        Returns
        -------
        ClaudeResponse
        """
        from src.services.ai.prompts import DISTRESSED_EVAL_SYSTEM, build_distressed_prompt

        prompt = build_distressed_prompt(
            symbol,
            z_score=z_score,
            financials=financial_data,
            filings=filing_summaries,
            insider_data=insider_data,
        )
        return await self.analyze(
            prompt,
            model=OPUS,
            system=DISTRESSED_EVAL_SYSTEM,
            max_tokens=8192,
            temperature=0.2,
        )
