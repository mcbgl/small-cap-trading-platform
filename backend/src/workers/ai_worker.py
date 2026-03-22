"""
Background worker for AI analysis tasks.

Processes queued filing analyses, generates insight cards from high-scoring
signals, and runs periodic quality spot-checks on AI outputs.
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import date, datetime, timezone

from src.config import settings
from src.models.schemas import InsightCard, SignalType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUEUE_NAME = "queue:ai_analysis"
DEAD_LETTER_QUEUE = "queue:ai_dead_letter"
MAX_RETRIES = 3
RATE_LIMIT_PER_MINUTE = 10
QUEUE_POLL_INTERVAL = 2.0  # seconds between queue polls when empty


# ---------------------------------------------------------------------------
# AIWorker
# ---------------------------------------------------------------------------

class AIWorker:
    """
    Background worker that processes AI analysis tasks from a Redis queue.

    Task types
    ----------
    - ``filing_analysis``   : Analyse a queued SEC filing (from EDGAR worker).
    - ``insight_generation`` : Generate an InsightCard from recent high-scoring signals.
    - ``spot_check``         : QA-compare local model output against Claude Opus.

    Each task payload is a JSON dict with at least::

        {
            "type": "filing_analysis",
            "payload": { ... },
            "priority": 1,
            "queued_at": "2026-03-21T12:00:00Z"
        }
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._task: asyncio.Task | None = None

        # Rate-limiting state
        self._call_timestamps: list[float] = []

        # Metrics
        self._tasks_processed: int = 0
        self._tasks_failed: int = 0
        self._total_cost_usd: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the AI worker processing loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="ai-worker")
        logger.info("AIWorker started")

    async def stop(self) -> None:
        """Gracefully stop the AI worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(
            "AIWorker stopped (processed=%d, failed=%d, cost=$%.4f)",
            self._tasks_processed,
            self._tasks_failed,
            self._total_cost_usd,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Pop tasks from the Redis queue and route to the appropriate handler."""
        from src.db import get_redis

        logger.info("AI worker processing loop started")

        while self._running:
            try:
                redis = get_redis()

                # BLPOP with a short timeout so we can check _running periodically
                result = await redis.blpop(QUEUE_NAME, timeout=int(QUEUE_POLL_INTERVAL))
                if result is None:
                    # No task available — loop back
                    continue

                _queue_key, raw_task = result
                try:
                    task = json.loads(raw_task)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in AI queue: %s", raw_task[:200])
                    continue

                await self._process_task(task)

            except asyncio.CancelledError:
                logger.info("AI worker loop cancelled")
                raise
            except RuntimeError as exc:
                # Redis not initialised — back off
                logger.warning("AI worker: %s — sleeping 10s", exc)
                await asyncio.sleep(10)
            except Exception:
                logger.exception("AI worker loop error — sleeping 5s")
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Task routing
    # ------------------------------------------------------------------

    async def _process_task(self, task: dict) -> None:
        """Route a task to its handler, with retry and dead-letter logic."""
        task_type = task.get("type", "unknown")
        retries = task.get("_retries", 0)

        logger.info(
            "Processing AI task: type=%s, priority=%s, retries=%d",
            task_type,
            task.get("priority", "N/A"),
            retries,
        )

        try:
            # Rate-limit
            await self._wait_for_rate_limit()

            if task_type == "filing_analysis":
                await self._handle_filing_analysis(task.get("payload", {}))
            elif task_type == "insight_generation":
                await self._handle_insight_generation(task.get("payload", {}))
            elif task_type == "spot_check":
                await self._handle_spot_check(task.get("payload", {}))
            else:
                logger.warning("Unknown AI task type: %s", task_type)
                return

            self._tasks_processed += 1

        except Exception as exc:
            self._tasks_failed += 1
            logger.error("AI task failed (type=%s): %s", task_type, exc, exc_info=True)

            if retries + 1 >= MAX_RETRIES:
                logger.warning(
                    "Task exceeded %d retries — moving to dead letter queue: %s",
                    MAX_RETRIES,
                    task_type,
                )
                await self._send_to_dead_letter(task, str(exc))
            else:
                # Re-enqueue with incremented retry count
                task["_retries"] = retries + 1
                await self._re_enqueue(task)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _wait_for_rate_limit(self) -> None:
        """
        Enforce a maximum of RATE_LIMIT_PER_MINUTE AI calls per minute.

        If the limit is reached, sleep until the oldest call in the window
        expires.
        """
        now = time.monotonic()

        # Prune timestamps older than 60 seconds
        self._call_timestamps = [
            ts for ts in self._call_timestamps if now - ts < 60.0
        ]

        if len(self._call_timestamps) >= RATE_LIMIT_PER_MINUTE:
            oldest = self._call_timestamps[0]
            wait_time = 60.0 - (now - oldest) + 0.1
            if wait_time > 0:
                logger.debug("Rate-limited — waiting %.1fs", wait_time)
                await asyncio.sleep(wait_time)

        self._call_timestamps.append(time.monotonic())

    # ------------------------------------------------------------------
    # Cost tracking
    # ------------------------------------------------------------------

    async def _track_cost(self, cost_usd: float) -> None:
        """
        Accumulate API cost in the local counter and in Redis daily key.

        Redis key format: ``ai:costs:daily:2026-03-21``
        """
        self._total_cost_usd += cost_usd
        try:
            from src.db import get_redis
            redis = get_redis()
            key = f"ai:costs:daily:{date.today().isoformat()}"
            await redis.incrbyfloat(key, cost_usd)
            # Expire after 90 days
            await redis.expire(key, 90 * 86400)
        except Exception:
            logger.debug("Could not track AI cost in Redis")

    # ------------------------------------------------------------------
    # Dead letter / re-enqueue
    # ------------------------------------------------------------------

    async def _send_to_dead_letter(self, task: dict, error: str) -> None:
        """Push a failed task to the dead letter queue for manual inspection."""
        task["_dead_letter_reason"] = error
        task["_dead_letter_at"] = datetime.now(timezone.utc).isoformat()
        try:
            from src.db import get_redis
            redis = get_redis()
            await redis.rpush(DEAD_LETTER_QUEUE, json.dumps(task))
        except Exception:
            logger.error("Failed to push task to dead letter queue")

    async def _re_enqueue(self, task: dict) -> None:
        """Re-enqueue a task for retry (appended to the end of the queue)."""
        try:
            from src.db import get_redis
            redis = get_redis()
            await redis.rpush(QUEUE_NAME, json.dumps(task))
        except Exception:
            logger.error("Failed to re-enqueue task for retry")

    # ------------------------------------------------------------------
    # Task handlers
    # ------------------------------------------------------------------

    async def _handle_filing_analysis(self, payload: dict) -> None:
        """
        Analyse an SEC filing using the AI router.

        Expected payload keys:
            - filing_id (int): ID in the filings table.
            - ticker_id (int): Associated ticker ID.
            - symbol (str): Ticker symbol.
            - form_type (str): e.g. "8-K", "10-Q".
            - text (str): Raw filing text (or URL to fetch).

        Stores ``ai_summary`` and ``ai_score`` back into the filings table.
        """
        filing_id = payload.get("filing_id")
        symbol = payload.get("symbol", "UNKNOWN")
        form_type = payload.get("form_type", "")
        text = payload.get("text", "")

        if not text:
            logger.warning("Filing analysis task missing text — skipping filing_id=%s", filing_id)
            return

        logger.info("Analysing filing: %s %s (id=%s)", symbol, form_type, filing_id)

        # Truncate text to a reasonable context window
        max_chars = 50_000
        truncated = text[:max_chars] if len(text) > max_chars else text

        # Call AI for analysis
        analysis = await self._call_ai_for_filing(symbol, form_type, truncated)
        if analysis is None:
            raise RuntimeError(f"AI filing analysis returned None for filing_id={filing_id}")

        summary = analysis.get("summary", "")
        score = analysis.get("score", 0.0)
        cost = analysis.get("_cost_usd", 0.0)

        # Track cost
        if cost > 0:
            await self._track_cost(cost)

        # Store result in PostgreSQL
        try:
            from src.db import get_db_pool
            pool = get_db_pool()
            await pool.execute(
                """
                UPDATE filings
                SET ai_summary = $1, ai_score = $2, updated_at = NOW()
                WHERE id = $3
                """,
                summary,
                score,
                filing_id,
            )
            logger.info(
                "Stored filing analysis: filing_id=%s, score=%.1f, cost=$%.4f",
                filing_id,
                score,
                cost,
            )
        except Exception:
            logger.exception("Failed to store filing analysis for filing_id=%s", filing_id)
            raise

        # Record successful Anthropic call timestamp
        await self._record_anthropic_success()

    async def _handle_insight_generation(self, payload: dict) -> None:
        """
        Generate an InsightCard by synthesising recent signals for a symbol.

        Expected payload keys:
            - symbol (str): Ticker symbol.
            - ticker_id (int): Ticker ID.
            - signal_ids (list[int]): Recent high-scoring signal IDs to include.
        """
        symbol = payload.get("symbol", "UNKNOWN")
        ticker_id = payload.get("ticker_id")
        signal_ids = payload.get("signal_ids", [])

        logger.info("Generating insight card for %s (%d signals)", symbol, len(signal_ids))

        # Fetch signal data from DB
        signals_data = await self._fetch_signals(signal_ids)
        if not signals_data:
            logger.warning("No signal data found for insight generation: %s", symbol)
            return

        # Call AI to synthesise
        insight_raw = await self._call_ai_for_insight(symbol, signals_data)
        if insight_raw is None:
            raise RuntimeError(f"AI insight generation returned None for {symbol}")

        cost = insight_raw.pop("_cost_usd", 0.0)
        if cost > 0:
            await self._track_cost(cost)

        # Parse into InsightCard
        try:
            card = InsightCard(
                title=insight_raw.get("title", f"{symbol} Analysis"),
                ticker=symbol,
                score=float(insight_raw.get("score", 5.0)),
                pros=insight_raw.get("pros", []),
                cons=insight_raw.get("cons", []),
                recommendation=insight_raw.get("recommendation", "Hold"),
                confidence=float(insight_raw.get("confidence", 0.5)),
                model=insight_raw.get("model", "unknown"),
            )
        except Exception as exc:
            logger.error("Failed to parse InsightCard: %s", exc)
            raise

        # Store the insight card
        try:
            from src.db import get_db_pool
            pool = get_db_pool()
            await pool.execute(
                """
                INSERT INTO insight_cards (ticker_id, symbol, title, score, pros, cons,
                                           recommendation, confidence, model, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                """,
                ticker_id,
                card.ticker,
                card.title,
                card.score,
                card.pros,
                card.cons,
                card.recommendation,
                card.confidence,
                card.model,
            )
            logger.info("Stored InsightCard for %s (score=%.1f)", symbol, card.score)
        except Exception:
            logger.exception("Failed to store InsightCard for %s", symbol)
            raise

        # Publish to Redis for real-time alert
        try:
            from src.db import get_redis
            redis = get_redis()
            await redis.publish(
                "channel:signals",
                json.dumps({
                    "type": "insight_card",
                    "symbol": symbol,
                    "score": card.score,
                    "recommendation": card.recommendation,
                    "title": card.title,
                }),
            )
        except Exception:
            logger.debug("Could not publish insight card to Redis channel")

        await self._record_anthropic_success()

    async def _handle_spot_check(self, payload: dict) -> None:
        """
        QA spot-check: compare a local model output against Claude Opus.

        Expected payload keys:
            - original_task_type (str): The task type of the original analysis.
            - original_input (str): The input that was given to the local model.
            - local_output (str): The local model's output.
            - reference_id (str): An identifier for the original analysis.
        """
        ref_id = payload.get("reference_id", "unknown")
        original_input = payload.get("original_input", "")
        local_output = payload.get("local_output", "")

        if not original_input or not local_output:
            logger.warning("Spot check missing input or output — skipping ref=%s", ref_id)
            return

        logger.info("Running spot check for ref=%s", ref_id)

        # Call Claude to evaluate the local model's output
        evaluation = await self._call_ai_for_spot_check(original_input, local_output)
        if evaluation is None:
            raise RuntimeError(f"Spot check AI call returned None for ref={ref_id}")

        cost = evaluation.get("_cost_usd", 0.0)
        if cost > 0:
            await self._track_cost(cost)

        agreement = evaluation.get("agreement", False)
        reasoning = evaluation.get("reasoning", "")
        quality_score = evaluation.get("quality_score", 0.0)

        # Log the result
        level = logging.INFO if agreement else logging.WARNING
        logger.log(
            level,
            "Spot check ref=%s: agreement=%s, quality=%.1f — %s",
            ref_id,
            agreement,
            quality_score,
            reasoning[:200],
        )

        # Store spot check result in Redis for dashboard review
        try:
            from src.db import get_redis
            redis = get_redis()
            result = {
                "reference_id": ref_id,
                "agreement": agreement,
                "quality_score": quality_score,
                "reasoning": reasoning,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            await redis.lpush("ai:spot_checks", json.dumps(result))
            # Keep only last 100 spot checks
            await redis.ltrim("ai:spot_checks", 0, 99)
        except Exception:
            logger.debug("Could not store spot check result in Redis")

        await self._record_anthropic_success()

    # ------------------------------------------------------------------
    # AI call stubs — these call the AI router / Anthropic client
    # ------------------------------------------------------------------

    async def _call_ai_for_filing(self, symbol: str, form_type: str, text: str) -> dict | None:
        """
        Call the AI model to analyse a filing.

        Returns a dict with ``summary``, ``score``, and ``_cost_usd``.
        """
        if not settings.anthropic_api_key:
            logger.warning("Anthropic API key not set — using placeholder filing analysis")
            return {
                "summary": f"Automated analysis unavailable for {symbol} {form_type}",
                "score": 0.0,
                "_cost_usd": 0.0,
            }

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            prompt = (
                f"Analyse the following SEC {form_type} filing for {symbol}. "
                f"Provide a concise summary (max 3 paragraphs) and a risk/opportunity "
                f"score from 0.0 (very negative) to 10.0 (very positive) for small-cap "
                f"trading.\n\n--- FILING TEXT ---\n{text}\n--- END ---\n\n"
                f"Respond with JSON: {{\"summary\": \"...\", \"score\": 5.0}}"
            )

            message = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            # Estimate cost: ~$3/M input, ~$15/M output for Sonnet
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

            response_text = message.content[0].text
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from the response
                import re
                match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    result = {"summary": response_text, "score": 5.0}

            result["_cost_usd"] = cost
            return result

        except ImportError:
            logger.warning("anthropic package not installed — skipping filing analysis")
            return {"summary": "Anthropic SDK not available", "score": 0.0, "_cost_usd": 0.0}
        except Exception as exc:
            logger.error("Anthropic API call failed for filing analysis: %s", exc)
            raise

    async def _call_ai_for_insight(self, symbol: str, signals_data: list[dict]) -> dict | None:
        """
        Call the AI model to synthesise signals into an InsightCard.

        Returns a dict matching InsightCard fields plus ``_cost_usd``.
        """
        if not settings.anthropic_api_key:
            logger.warning("Anthropic API key not set — using placeholder insight")
            return {
                "title": f"{symbol} Signal Summary",
                "score": 5.0,
                "pros": ["Multiple signals detected"],
                "cons": ["AI analysis unavailable"],
                "recommendation": "Review manually",
                "confidence": 0.3,
                "model": "placeholder",
                "_cost_usd": 0.0,
            }

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            signals_summary = json.dumps(signals_data, indent=2, default=str)
            prompt = (
                f"You are a small-cap stock analyst. Synthesise the following signals "
                f"for {symbol} into a trading insight card.\n\n"
                f"Signals:\n{signals_summary}\n\n"
                f"Respond with JSON matching this schema:\n"
                f'{{"title": "...", "score": 7.5, "pros": ["..."], "cons": ["..."], '
                f'"recommendation": "Buy/Hold/Sell/Avoid", "confidence": 0.75, '
                f'"model": "claude-sonnet-4-20250514"}}'
            )

            message = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

            response_text = message.content[0].text
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError:
                import re
                match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    raise RuntimeError("Could not parse insight JSON from AI response")

            result["_cost_usd"] = cost
            return result

        except ImportError:
            logger.warning("anthropic package not installed — skipping insight generation")
            return {
                "title": f"{symbol} Analysis",
                "score": 5.0,
                "pros": [],
                "cons": ["SDK not available"],
                "recommendation": "Hold",
                "confidence": 0.1,
                "model": "placeholder",
                "_cost_usd": 0.0,
            }
        except Exception as exc:
            logger.error("Anthropic API call failed for insight generation: %s", exc)
            raise

    async def _call_ai_for_spot_check(self, original_input: str, local_output: str) -> dict | None:
        """
        Call Claude Opus to QA-check a local model's output.

        Returns ``{agreement: bool, reasoning: str, quality_score: float, _cost_usd: float}``.
        """
        if not settings.anthropic_api_key:
            logger.warning("Anthropic API key not set — skipping spot check")
            return {
                "agreement": True,
                "reasoning": "Spot check skipped — no API key",
                "quality_score": 0.0,
                "_cost_usd": 0.0,
            }

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            prompt = (
                "You are a quality assurance reviewer for an AI-driven trading platform. "
                "A local model produced the following analysis. Evaluate its accuracy, "
                "completeness, and whether you agree with its conclusions.\n\n"
                f"--- ORIGINAL INPUT ---\n{original_input[:10_000]}\n--- END INPUT ---\n\n"
                f"--- LOCAL MODEL OUTPUT ---\n{local_output[:5_000]}\n--- END OUTPUT ---\n\n"
                "Respond with JSON: "
                '{"agreement": true/false, "reasoning": "...", "quality_score": 0.0-10.0}'
            )

            message = await client.messages.create(
                model="claude-opus-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # Opus pricing: ~$15/M input, ~$75/M output
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cost = (input_tokens * 15.0 / 1_000_000) + (output_tokens * 75.0 / 1_000_000)

            response_text = message.content[0].text
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError:
                import re
                match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    result = {
                        "agreement": False,
                        "reasoning": f"Could not parse QA response: {response_text[:500]}",
                        "quality_score": 0.0,
                    }

            result["_cost_usd"] = cost
            return result

        except ImportError:
            logger.warning("anthropic package not installed — skipping spot check")
            return {
                "agreement": True,
                "reasoning": "SDK not available",
                "quality_score": 0.0,
                "_cost_usd": 0.0,
            }
        except Exception as exc:
            logger.error("Anthropic API call failed for spot check: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_signals(self, signal_ids: list[int]) -> list[dict]:
        """Fetch signal records from PostgreSQL by ID."""
        if not signal_ids:
            return []
        try:
            from src.db import get_db_pool
            pool = get_db_pool()
            rows = await pool.fetch(
                """
                SELECT s.id, s.ticker_id, t.symbol, s.signal_type, s.score,
                       s.confidence, s.reasoning, s.metadata, s.created_at
                FROM signals s
                JOIN tickers t ON t.id = s.ticker_id
                WHERE s.id = ANY($1)
                ORDER BY s.created_at DESC
                """,
                signal_ids,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error("Failed to fetch signals: %s", exc)
            return []

    async def _record_anthropic_success(self) -> None:
        """Record the timestamp of a successful Anthropic API call in Redis."""
        try:
            from src.db import get_redis
            redis = get_redis()
            await redis.set(
                "ai:anthropic:last_success",
                datetime.now(timezone.utc).isoformat(),
                ex=86400 * 7,  # expire after 7 days
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """Return health information for the AI worker."""
        return {
            "running": self._running,
            "tasks_processed": self._tasks_processed,
            "tasks_failed": self._tasks_failed,
            "total_cost_usd": round(self._total_cost_usd, 4),
            "rate_limit_calls_in_window": len(self._call_timestamps),
        }


# ---------------------------------------------------------------------------
# Module-level singleton and lifecycle functions
# ---------------------------------------------------------------------------

_worker: AIWorker | None = None


async def start_ai_worker() -> None:
    """Create and start the global AI worker."""
    global _worker
    if _worker is not None:
        logger.warning("AI worker already running")
        return

    _worker = AIWorker()
    await _worker.start()


async def stop_ai_worker() -> None:
    """Stop the global AI worker."""
    global _worker
    if _worker:
        await _worker.stop()
        _worker = None


def get_ai_worker() -> AIWorker | None:
    """Return the current AI worker instance (or None if not started)."""
    return _worker


async def queue_analysis(
    task_type: str,
    payload: dict,
    priority: int = 5,
) -> None:
    """
    Enqueue an AI analysis task.

    Parameters
    ----------
    task_type:
        One of ``"filing_analysis"``, ``"insight_generation"``, ``"spot_check"``.
    payload:
        Task-specific data dict.
    priority:
        1 (highest) to 10 (lowest). Currently used for logging; future
        implementation may support priority queues.
    """
    task = {
        "type": task_type,
        "payload": payload,
        "priority": priority,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from src.db import get_redis
        redis = get_redis()
        await redis.rpush(QUEUE_NAME, json.dumps(task))
        logger.info("Queued AI task: type=%s, priority=%d", task_type, priority)
    except Exception as exc:
        logger.error("Failed to enqueue AI task: %s", exc)
        raise
