"""
System health monitoring worker.

Periodically checks all system components and publishes status via WebSocket.
Components: PostgreSQL, QuestDB, Redis, Ollama, Polygon WS, EDGAR, broker APIs.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from enum import StrEnum

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECK_INTERVAL_SECONDS = 30
COMPONENT_TIMEOUT_SECONDS = 5.0


class ComponentStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNAVAILABLE = "unavailable"


# Components considered critical — if any is DOWN, aggregate is DOWN.
CRITICAL_COMPONENTS = {"postgresql", "redis"}


# ---------------------------------------------------------------------------
# Individual component check results
# ---------------------------------------------------------------------------

def _result(
    name: str,
    status: ComponentStatus,
    latency_ms: float = 0.0,
    message: str = "",
) -> dict:
    """Build a standardised component health result dict."""
    return {
        "name": name,
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "last_check": datetime.now(timezone.utc).isoformat(),
        "message": message,
    }


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    """
    Periodically checks all system components and publishes status.

    Results are published to Redis ``channel:system`` for WebSocket relay and
    cached under the ``system:health`` key so API endpoints can read them
    synchronously.
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._latest_status: dict = {}
        self._http_client: httpx.AsyncClient | None = None
        # Track state transitions for alerting
        self._previous_statuses: dict[str, ComponentStatus] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the health monitoring loop."""
        self._http_client = httpx.AsyncClient(timeout=COMPONENT_TIMEOUT_SECONDS)
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="health-monitor")
        logger.info("HealthMonitor started (interval=%ds)", CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Stop the monitoring loop and clean up resources."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("HealthMonitor stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Core monitoring loop — runs checks every CHECK_INTERVAL_SECONDS."""
        while self._running:
            try:
                await self._run_checks()
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                logger.info("HealthMonitor loop cancelled")
                raise
            except Exception:
                logger.exception("HealthMonitor loop error — retrying in 10s")
                await asyncio.sleep(10)

    async def _run_checks(self) -> None:
        """Execute all component checks concurrently and publish results."""
        checks = await asyncio.gather(
            self._check_postgresql(),
            self._check_questdb(),
            self._check_redis(),
            self._check_ollama(),
            self._check_polygon_ws(),
            self._check_edgar(),
            self._check_anthropic(),
            return_exceptions=True,
        )

        components: list[dict] = []
        for result in checks:
            if isinstance(result, Exception):
                components.append(
                    _result("unknown", ComponentStatus.DOWN, message=str(result))
                )
            else:
                components.append(result)

        # Compute aggregate status
        aggregate = self._compute_aggregate(components)

        self._latest_status = {
            "status": aggregate,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": components,
        }

        # Detect state transitions and log alerts
        self._check_transitions(components)

        # Publish to Redis (best-effort)
        await self._publish_status(self._latest_status)

    # ------------------------------------------------------------------
    # Aggregate status logic
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_aggregate(components: list[dict]) -> str:
        """
        Determine overall system status from individual component results.

        - "healthy"  — all *configured* components are healthy
        - "degraded" — at least one component is degraded
        - "down"     — any critical component is down
        """
        statuses = {
            c["name"]: ComponentStatus(c["status"])
            for c in components
        }

        # If any critical component is down, system is down
        for name in CRITICAL_COMPONENTS:
            if statuses.get(name) == ComponentStatus.DOWN:
                return ComponentStatus.DOWN

        configured = [
            s for s in statuses.values() if s != ComponentStatus.UNAVAILABLE
        ]

        if any(s == ComponentStatus.DOWN for s in configured):
            return ComponentStatus.DEGRADED

        if any(s == ComponentStatus.DEGRADED for s in configured):
            return ComponentStatus.DEGRADED

        return ComponentStatus.HEALTHY

    # ------------------------------------------------------------------
    # Transition alerting
    # ------------------------------------------------------------------

    def _check_transitions(self, components: list[dict]) -> None:
        """Log warnings when a component transitions away from healthy."""
        for comp in components:
            name = comp["name"]
            current = ComponentStatus(comp["status"])
            previous = self._previous_statuses.get(name)

            if previous is not None and previous == ComponentStatus.HEALTHY and current in (
                ComponentStatus.DEGRADED,
                ComponentStatus.DOWN,
            ):
                logger.warning(
                    "Component %s transitioned from %s -> %s: %s",
                    name,
                    previous,
                    current,
                    comp.get("message", ""),
                )

            self._previous_statuses[name] = current

    # ------------------------------------------------------------------
    # Redis publishing
    # ------------------------------------------------------------------

    async def _publish_status(self, status: dict) -> None:
        """Publish health status to Redis channel + cached key."""
        try:
            from src.db import get_redis
            redis = get_redis()
            payload = json.dumps(status)

            # Cache for synchronous reads by API endpoints
            await redis.set("system:health", payload, ex=120)

            # Publish for WebSocket relay
            await redis.publish("channel:system", payload)
        except Exception:
            # Redis itself may be down — just log and continue
            logger.debug("Could not publish health status to Redis")

    # ------------------------------------------------------------------
    # Component checks
    # ------------------------------------------------------------------

    async def _check_postgresql(self) -> dict:
        """Check PostgreSQL connectivity via ``SELECT 1``."""
        name = "postgresql"
        try:
            from src.db import get_db_pool
            pool = get_db_pool()
        except RuntimeError:
            return _result(name, ComponentStatus.DOWN, message="Pool not initialised")

        t0 = time.monotonic()
        try:
            async with pool.acquire() as conn:
                await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=COMPONENT_TIMEOUT_SECONDS)
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.HEALTHY, latency_ms=latency)
        except asyncio.TimeoutError:
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.DEGRADED, latency_ms=latency, message="Query timed out")
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.DOWN, latency_ms=latency, message=str(exc))

    async def _check_questdb(self) -> dict:
        """Check QuestDB via its HTTP health endpoint."""
        name = "questdb"
        if not self._http_client:
            return _result(name, ComponentStatus.DOWN, message="HTTP client not ready")

        url = f"{settings.questdb_url}/exec"
        t0 = time.monotonic()
        try:
            resp = await self._http_client.get(url, params={"query": "SELECT 1"})
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                return _result(name, ComponentStatus.HEALTHY, latency_ms=latency)
            return _result(
                name,
                ComponentStatus.DEGRADED,
                latency_ms=latency,
                message=f"HTTP {resp.status_code}",
            )
        except httpx.ConnectError:
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.DOWN, latency_ms=latency, message="Connection refused")
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.DOWN, latency_ms=latency, message=str(exc))

    async def _check_redis(self) -> dict:
        """Check Redis via PING."""
        name = "redis"
        try:
            from src.db import get_redis
            redis = get_redis()
        except RuntimeError:
            return _result(name, ComponentStatus.DOWN, message="Redis not initialised")

        t0 = time.monotonic()
        try:
            pong = await asyncio.wait_for(redis.ping(), timeout=COMPONENT_TIMEOUT_SECONDS)
            latency = (time.monotonic() - t0) * 1000
            if pong:
                return _result(name, ComponentStatus.HEALTHY, latency_ms=latency)
            return _result(name, ComponentStatus.DEGRADED, latency_ms=latency, message="PING returned falsy")
        except asyncio.TimeoutError:
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.DEGRADED, latency_ms=latency, message="PING timed out")
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.DOWN, latency_ms=latency, message=str(exc))

    async def _check_ollama(self) -> dict:
        """
        Check Ollama local LLM service via ``GET /api/tags``.

        Returns "unavailable" if Ollama URL is not configured — this is
        intentional (the Qwen machine may not be online yet).
        """
        name = "ollama"
        if not settings.ollama_url:
            return _result(name, ComponentStatus.UNAVAILABLE, message="Ollama URL not configured")

        if not self._http_client:
            return _result(name, ComponentStatus.DOWN, message="HTTP client not ready")

        url = f"{settings.ollama_url}/api/tags"
        t0 = time.monotonic()
        try:
            resp = await self._http_client.get(url)
            latency = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                data = resp.json()
                model_count = len(data.get("models", []))
                return _result(
                    name,
                    ComponentStatus.HEALTHY,
                    latency_ms=latency,
                    message=f"{model_count} model(s) loaded",
                )
            return _result(name, ComponentStatus.DEGRADED, latency_ms=latency, message=f"HTTP {resp.status_code}")
        except httpx.ConnectError:
            latency = (time.monotonic() - t0) * 1000
            return _result(
                name,
                ComponentStatus.UNAVAILABLE,
                latency_ms=latency,
                message="Ollama not reachable — local LLM server not running",
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            return _result(name, ComponentStatus.DOWN, latency_ms=latency, message=str(exc))

    async def _check_polygon_ws(self) -> dict:
        """Check Polygon WebSocket connection status from market data worker."""
        name = "polygon_ws"
        try:
            from src.workers.market_data import health_check as md_health
            status = md_health()

            if not status.get("worker_running"):
                if not settings.polygon_api_key:
                    return _result(
                        name,
                        ComponentStatus.UNAVAILABLE,
                        message="Polygon API key not configured",
                    )
                return _result(name, ComponentStatus.DOWN, message="Market data worker not running")

            if status.get("service_active"):
                return _result(name, ComponentStatus.HEALTHY, message="WebSocket connected")

            if not status.get("market_open"):
                return _result(
                    name,
                    ComponentStatus.HEALTHY,
                    message=f"Market closed — next session pending (ET: {status.get('current_time_et', 'N/A')})",
                )

            return _result(name, ComponentStatus.DEGRADED, message="Worker running but service not active")
        except Exception as exc:
            return _result(name, ComponentStatus.DOWN, message=str(exc))

    async def _check_edgar(self) -> dict:
        """Check EDGAR worker status via its health report."""
        name = "edgar"
        try:
            from src.workers.edgar_worker import get_edgar_worker
            worker = get_edgar_worker()

            if worker is None:
                if not settings.edgar_user_agent:
                    return _result(
                        name,
                        ComponentStatus.UNAVAILABLE,
                        message="EDGAR user agent not configured",
                    )
                return _result(name, ComponentStatus.DOWN, message="EDGAR worker not started")

            health = worker.health()

            if not health.get("running"):
                return _result(name, ComponentStatus.DOWN, message="EDGAR worker stopped")

            if not health.get("healthy"):
                return _result(
                    name,
                    ComponentStatus.DEGRADED,
                    message=f"Last error: {health.get('last_error', 'unknown')}",
                )

            last_poll = health.get("last_filing_poll")
            polls = health.get("polls_completed", 0)
            return _result(
                name,
                ComponentStatus.HEALTHY,
                message=f"{polls} polls completed, last: {last_poll or 'N/A'}",
            )
        except Exception as exc:
            return _result(name, ComponentStatus.DOWN, message=str(exc))

    async def _check_anthropic(self) -> dict:
        """
        Check Anthropic API configuration.

        Verifies the API key is set. Does NOT make a live API call each cycle
        (that would be expensive). Instead, checks the last successful call
        timestamp stored in Redis.
        """
        name = "anthropic"
        if not settings.anthropic_api_key:
            return _result(
                name,
                ComponentStatus.UNAVAILABLE,
                message="Anthropic API key not configured",
            )

        # Check for recent successful API usage via Redis timestamp
        try:
            from src.db import get_redis
            redis = get_redis()
            last_call = await redis.get("ai:anthropic:last_success")
            if last_call:
                return _result(
                    name,
                    ComponentStatus.HEALTHY,
                    message=f"API key configured, last success: {last_call}",
                )
            return _result(
                name,
                ComponentStatus.HEALTHY,
                message="API key configured, no recent calls recorded",
            )
        except RuntimeError:
            # Redis not available — still report key configured
            return _result(
                name,
                ComponentStatus.HEALTHY,
                message="API key configured (Redis unavailable for usage tracking)",
            )
        except Exception as exc:
            return _result(
                name,
                ComponentStatus.DEGRADED,
                message=f"API key configured but status check failed: {exc}",
            )

    # ------------------------------------------------------------------
    # Public accessor
    # ------------------------------------------------------------------

    @property
    def latest_status(self) -> dict:
        """Return the most recently computed health status."""
        return self._latest_status


# ---------------------------------------------------------------------------
# Module-level singleton and lifecycle functions
# ---------------------------------------------------------------------------

_monitor: HealthMonitor | None = None


async def start_health_monitor() -> None:
    """Create and start the global HealthMonitor instance."""
    global _monitor
    if _monitor is not None:
        logger.warning("HealthMonitor already running")
        return

    _monitor = HealthMonitor()
    await _monitor.start()


async def stop_health_monitor() -> None:
    """Stop the global HealthMonitor instance."""
    global _monitor
    if _monitor:
        await _monitor.stop()
        _monitor = None


def get_system_health() -> dict:
    """
    Return the latest cached system health status.

    Returns an empty dict if the monitor has not yet run a check cycle.
    """
    if _monitor is None:
        return {
            "status": "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": [],
            "message": "Health monitor not started",
        }
    return _monitor.latest_status or {
        "status": "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": [],
        "message": "Health monitor started but no checks completed yet",
    }
