"""
Ollama client for local Qwen 3.5 122B inference.

Connects to Ollama API at localhost:11434. Gracefully handles unavailability --
when the Qwen machine is not connected, all methods return None and the router
falls back to Claude.

The client caches availability status for 60 seconds to avoid hammering the
health endpoint on every request.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

# Default model for local inference
DEFAULT_MODEL = "qwen3.5:122b"

# Availability cache TTL in seconds
_AVAILABILITY_CACHE_TTL = 60


@dataclass
class OllamaResponse:
    """Structured response from an Ollama inference call."""

    content: str
    model: str
    total_duration_ns: int
    eval_count: int
    tokens_per_second: float


class OllamaClient:
    """
    Async HTTP client for the Ollama REST API.

    Designed for complete functionality -- all endpoints are implemented and
    work correctly when Ollama is running.  When Ollama is unavailable (the
    typical state until the Qwen machine is connected), every public method
    returns ``None`` instead of raising, allowing the AI router to fall back
    to Claude seamlessly.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.ollama_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._available: bool | None = None  # None = never checked
        self._available_checked_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Create the underlying HTTP client.  Safe to call multiple times."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            )
        # Pre-check availability on init so first request is fast.
        await self.is_available()

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._available = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """Return the HTTP client, creating one lazily if needed."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            )
        return self._client

    # ------------------------------------------------------------------
    # Health / availability
    # ------------------------------------------------------------------

    async def is_available(self) -> bool:
        """
        Check whether Ollama is reachable.

        Pings ``GET /api/tags`` and caches the result for 60 s.  Returns
        ``False`` (never raises) if the server is down or unreachable.
        """
        now = time.monotonic()
        if self._available is not None and (now - self._available_checked_at) < _AVAILABILITY_CACHE_TTL:
            return self._available

        client = self._ensure_client()
        try:
            resp = await client.get("/api/tags", timeout=5.0)
            self._available = resp.status_code == 200
            if self._available:
                models = resp.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                logger.info("Ollama available at %s — models: %s", self._base_url, model_names)
            else:
                logger.warning("Ollama returned status %d", resp.status_code)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError, OSError) as exc:
            self._available = False
            logger.info("Ollama unavailable at %s: %s", self._base_url, exc)
        except Exception:
            self._available = False
            logger.exception("Unexpected error checking Ollama availability")

        self._available_checked_at = now
        return self._available

    async def health_check(self) -> dict:
        """
        Return a health-check dict suitable for the system status page.

        Returns something like::

            {"status": "healthy", "url": "...", "models": [...]}
            {"status": "unavailable", "url": "...", "error": "..."}
        """
        client = self._ensure_client()
        try:
            resp = await client.get("/api/tags", timeout=5.0)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                return {"status": "healthy", "url": self._base_url, "models": models}
            return {"status": "unhealthy", "url": self._base_url, "http_status": resp.status_code}
        except Exception as exc:
            return {"status": "unavailable", "url": self._base_url, "error": str(exc)}

    # ------------------------------------------------------------------
    # Core inference
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_MODEL,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: float | None = None,
    ) -> OllamaResponse | None:
        """
        Single-turn generation via ``POST /api/generate``.

        Parameters
        ----------
        prompt:
            The user prompt.
        model:
            Ollama model tag (default: ``qwen3.5:122b``).
        system:
            Optional system prompt.
        temperature:
            Sampling temperature.
        max_tokens:
            Maximum tokens to generate (``num_predict`` in Ollama).
        timeout_seconds:
            Per-request timeout override.  ``None`` uses the client default
            (120 s read timeout).  Tier 1 callers may pass 30.

        Returns
        -------
        OllamaResponse | None
            Parsed response, or ``None`` if Ollama is unavailable or the
            request fails.
        """
        if not await self.is_available():
            return None

        client = self._ensure_client()

        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system

        req_timeout = timeout_seconds if timeout_seconds else None

        try:
            resp = await client.post(
                "/api/generate",
                json=payload,
                timeout=req_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._parse_generate_response(data, model)

        except httpx.TimeoutException:
            logger.warning("Ollama generate timed out for model %s (%.0fs)", model, timeout_seconds or 120)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("Ollama generate HTTP error: %s", exc)
            return None
        except (httpx.ConnectError, OSError) as exc:
            # Server went down between availability check and request.
            logger.warning("Ollama connection lost during generate: %s", exc)
            self._available = False
            self._available_checked_at = time.monotonic()
            return None
        except Exception:
            logger.exception("Unexpected error during Ollama generate")
            return None

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: float | None = None,
    ) -> OllamaResponse | None:
        """
        Multi-turn chat via ``POST /api/chat``.

        Parameters
        ----------
        messages:
            List of ``{"role": "system"|"user"|"assistant", "content": "..."}`` dicts.
        model:
            Ollama model tag.
        temperature:
            Sampling temperature.
        max_tokens:
            Maximum tokens to generate.
        timeout_seconds:
            Per-request timeout override.

        Returns
        -------
        OllamaResponse | None
            Parsed response, or ``None`` if unavailable.
        """
        if not await self.is_available():
            return None

        client = self._ensure_client()

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        req_timeout = timeout_seconds if timeout_seconds else None

        try:
            resp = await client.post(
                "/api/chat",
                json=payload,
                timeout=req_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._parse_chat_response(data, model)

        except httpx.TimeoutException:
            logger.warning("Ollama chat timed out for model %s", model)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("Ollama chat HTTP error: %s", exc)
            return None
        except (httpx.ConnectError, OSError) as exc:
            logger.warning("Ollama connection lost during chat: %s", exc)
            self._available = False
            self._available_checked_at = time.monotonic()
            return None
        except Exception:
            logger.exception("Unexpected error during Ollama chat")
            return None

    # ------------------------------------------------------------------
    # Confidence extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_confidence(response_text: str) -> float:
        """
        Parse a confidence score from a structured JSON response.

        Looks for a top-level ``"confidence"`` key in the response text.
        Returns 0.0 if parsing fails.
        """
        try:
            data = json.loads(response_text)
            conf = data.get("confidence")
            if conf is not None:
                return max(0.0, min(1.0, float(conf)))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Fallback: regex-style search for confidence pattern
        import re
        match = re.search(r'"confidence"\s*:\s*([\d.]+)', response_text)
        if match:
            try:
                return max(0.0, min(1.0, float(match.group(1))))
            except ValueError:
                pass

        return 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_generate_response(data: dict, model: str) -> OllamaResponse:
        """Parse the JSON body from ``/api/generate`` into an OllamaResponse."""
        content = data.get("response", "")
        total_duration = data.get("total_duration", 0)
        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 1)  # avoid div-by-zero
        tps = (eval_count / eval_duration * 1_000_000_000) if eval_duration > 0 else 0.0

        return OllamaResponse(
            content=content,
            model=data.get("model", model),
            total_duration_ns=total_duration,
            eval_count=eval_count,
            tokens_per_second=round(tps, 1),
        )

    @staticmethod
    def _parse_chat_response(data: dict, model: str) -> OllamaResponse:
        """Parse the JSON body from ``/api/chat`` into an OllamaResponse."""
        message = data.get("message", {})
        content = message.get("content", "")
        total_duration = data.get("total_duration", 0)
        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 1)
        tps = (eval_count / eval_duration * 1_000_000_000) if eval_duration > 0 else 0.0

        return OllamaResponse(
            content=content,
            model=data.get("model", model),
            total_duration_ns=total_duration,
            eval_count=eval_count,
            tokens_per_second=round(tps, 1),
        )
