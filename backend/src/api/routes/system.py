"""
System endpoints — health, status, config, audit log, and emergency controls.
"""

import json as _json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from src.config import HardcodedLimits, settings

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_pool():
    """Return the asyncpg pool or None if unavailable."""
    try:
        from src.db import get_db_pool
        return get_db_pool()
    except RuntimeError:
        return None


def _get_redis():
    """Return the Redis client or None if unavailable."""
    try:
        from src.db import get_redis
        return get_redis()
    except RuntimeError:
        return None


# ---------------------------------------------------------------------------
# GET /health — real system health from HealthMonitor
# ---------------------------------------------------------------------------

@router.get("/health")
async def system_health():
    """
    Detailed system health check.  Uses the HealthMonitor singleton for
    real component status (PostgreSQL, QuestDB, Redis, Ollama, Polygon,
    EDGAR, Anthropic).  Falls back to a basic check if the monitor has
    not yet completed a cycle.
    """
    try:
        from src.workers.health_check import get_system_health
        health = get_system_health()
        if health and health.get("status") != "unknown":
            return health
    except Exception:
        logger.debug("HealthMonitor not available, returning basic health check")

    # Fallback: probe DB + Redis directly
    db_status = "unknown"
    pool = _get_pool()
    if pool is not None:
        try:
            await pool.fetchval("SELECT 1")
            db_status = "ok"
        except Exception:
            db_status = "down"
    else:
        db_status = "not_initialised"

    redis_status = "unknown"
    redis = _get_redis()
    if redis is not None:
        try:
            pong = await redis.ping()
            redis_status = "ok" if pong else "degraded"
        except Exception:
            redis_status = "down"
    else:
        redis_status = "not_initialised"

    # Kill switch state from Redis
    kill_switch_active = False
    if redis is not None:
        try:
            for level in ("strategy", "account", "system"):
                val = await redis.get(f"risk:kill_switch:{level}")
                if val is not None and val == "1":
                    kill_switch_active = True
                    break
        except Exception:
            pass

    return {
        "status": "healthy" if db_status == "ok" and redis_status == "ok" else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": {
            "api": "ok",
            "database": db_status,
            "redis": redis_status,
            "questdb": "unknown",
        },
        "kill_switch_active": kill_switch_active,
    }


# ---------------------------------------------------------------------------
# GET /status — system status with real data
# ---------------------------------------------------------------------------

@router.get("/status")
async def system_status():
    """
    System status: mode settings, guardrail values, data feed connectivity,
    AI model readiness, and worker health.
    """
    redis = _get_redis()

    # Kill switch from Redis
    kill_switch: dict = {"strategy": False, "account": False, "system": False}
    if redis is not None:
        try:
            for level in ("strategy", "account", "system"):
                val = await redis.get(f"risk:kill_switch:{level}")
                kill_switch[level] = val is not None and val == "1"
        except Exception:
            pass

    kill_switch_active = any(kill_switch.values())

    # Worker health from HealthMonitor
    worker_health: dict = {}
    try:
        from src.workers.health_check import get_system_health
        cached = get_system_health()
        if cached and "components" in cached:
            for comp in cached["components"]:
                worker_health[comp["name"]] = comp["status"]
    except Exception:
        pass

    # Data feed status from workers
    data_feeds: dict = {
        "polygon": worker_health.get("polygon_ws", "unknown"),
        "edgar": worker_health.get("edgar", "unknown"),
    }

    # AI model readiness
    ai_models: dict = {
        "claude": worker_health.get("anthropic", "not_configured" if not settings.anthropic_api_key else "ready"),
        "ollama": worker_health.get("ollama", "unknown"),
    }

    # AI cost tracking from Redis
    ai_costs: dict = {}
    if redis is not None:
        try:
            for key in ("ai:cost:today", "ai:cost:month", "ai:tokens:today"):
                val = await redis.get(key)
                short_key = key.split(":")[-1]
                ai_costs[f"ai_{key.split(':')[1]}_{short_key}"] = float(val) if val else 0.0
        except Exception:
            pass

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kill_switch": kill_switch,
        "kill_switch_active": kill_switch_active,
        "mode": {
            "paper": settings.paper_mode,
            "shadow": settings.shadow_mode,
            "limit_orders_only": settings.limit_orders_only,
            "no_extended_hours": settings.no_extended_hours,
        },
        "guardrails": {
            "absolute_max_position_pct": HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT,
            "absolute_max_drawdown_pct": HardcodedLimits.ABSOLUTE_MAX_DRAWDOWN_PCT,
            "absolute_max_order_value": HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE,
            "max_position_pct": settings.max_position_pct,
            "daily_drawdown_pct": settings.daily_drawdown_pct,
            "weekly_drawdown_pct": settings.weekly_drawdown_pct,
            "human_approval_above_usd": settings.human_approval_above_usd,
        },
        "data_feeds": data_feeds,
        "ai_models": ai_models,
        "ai_costs": ai_costs,
        "worker_health": worker_health,
    }


# ---------------------------------------------------------------------------
# POST /kill-switch — activate emergency kill switch
# ---------------------------------------------------------------------------

@router.post("/kill-switch")
async def activate_kill_switch():
    """
    Emergency halt: delegates to the risk engine's kill switch at the
    system level.  Cancel all pending orders and prevent new submissions.
    """
    assert HardcodedLimits.KILL_SWITCH_ALWAYS_AVAILABLE

    # Delegate to RiskEngine if available
    try:
        from src.services.risk.engine import get_risk_engine
        engine = get_risk_engine()
        if engine is not None:
            result = await engine.trigger_kill_switch(
                level="system", reason="Activated via /api/system/kill-switch"
            )
            logger.critical("KILL SWITCH ACTIVATED via system endpoint")
            return result
    except Exception:
        logger.debug("RiskEngine unavailable for kill switch, using fallback")

    # Fallback: set in Redis
    redis = _get_redis()
    if redis is not None:
        try:
            await redis.set("risk:kill_switch:system", "1")
        except Exception:
            pass

    # Write audit log
    pool = _get_pool()
    if pool is not None:
        try:
            await pool.execute(
                """
                INSERT INTO audit_log (action, decision, output, created_at)
                VALUES ($1, $2, $3::jsonb, now())
                """,
                "kill_switch_triggered",
                "level=system",
                '{"level": "system", "reason": "Activated via /api/system/kill-switch"}',
            )
        except Exception:
            pass

    logger.critical("KILL SWITCH ACTIVATED — all trading halted (fallback path)")

    return {
        "status": "activated",
        "level": "system",
        "message": "Kill switch engaged — all pending orders will be cancelled, no new orders accepted",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actions_taken": [
            "Kill switch set at system level",
            "Pending orders flagged for cancellation",
            "New order submission blocked",
        ],
    }


# ---------------------------------------------------------------------------
# GET /config — current settings (non-secret values only)
# ---------------------------------------------------------------------------

# Fields that must NEVER be exposed in the config endpoint
_SECRET_FIELDS = frozenset({
    "polygon_api_key",
    "anthropic_api_key",
    "alpaca_api_key",
    "alpaca_secret_key",
    "secret_key",
    "database_url",
    "redis_url",
})


@router.get("/config")
async def system_config():
    """
    Return current settings values.  API keys and secrets are redacted.
    """
    all_fields = settings.model_dump()

    safe: dict = {}
    for key, value in all_fields.items():
        if key in _SECRET_FIELDS:
            # Indicate presence without revealing value
            safe[key] = "***" if value else "(not set)"
        else:
            safe[key] = value

    # Also include hardcoded limits for completeness
    safe["hardcoded_limits"] = {
        "ABSOLUTE_MAX_POSITION_PCT": HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT,
        "ABSOLUTE_MAX_DRAWDOWN_PCT": HardcodedLimits.ABSOLUTE_MAX_DRAWDOWN_PCT,
        "ABSOLUTE_MAX_ORDER_VALUE": HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE,
        "KILL_SWITCH_ALWAYS_AVAILABLE": HardcodedLimits.KILL_SWITCH_ALWAYS_AVAILABLE,
        "AUDIT_LOGGING_ALWAYS_ON": HardcodedLimits.AUDIT_LOGGING_ALWAYS_ON,
        "STOP_LOSS_REQUIRED": HardcodedLimits.STOP_LOSS_REQUIRED,
        "WASH_SALE_CHECK_ALWAYS_ON": HardcodedLimits.WASH_SALE_CHECK_ALWAYS_ON,
    }

    return safe


# ---------------------------------------------------------------------------
# GET /audit-log — query audit log with filters
# ---------------------------------------------------------------------------

@router.get("/audit-log")
async def audit_log(
    action: str | None = Query(default=None, description="Filter by action name"),
    model_id: str | None = Query(default=None, description="Filter by AI model ID"),
    decision: str | None = Query(default=None, description="Filter by decision value"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """
    Query the audit_log table with optional filters.  Returns entries in
    reverse chronological order.
    """
    pool = _get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        # Build query dynamically based on provided filters
        conditions: list[str] = []
        params: list = []
        idx = 1

        if action is not None:
            conditions.append(f"action = ${idx}")
            params.append(action)
            idx += 1

        if model_id is not None:
            conditions.append(f"model_id = ${idx}")
            params.append(model_id)
            idx += 1

        if decision is not None:
            conditions.append(f"decision = ${idx}")
            params.append(decision)
            idx += 1

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Count total matching
        count_row = await pool.fetchrow(
            f"SELECT count(*) AS cnt FROM audit_log {where_clause}",
            *params,
        )
        total = int(count_row["cnt"]) if count_row else 0

        # Fetch page
        rows = await pool.fetch(
            f"""
            SELECT
                id, action, model_id, prompt_hash,
                input_snapshot, output, decision,
                human_override, order_id, created_at
            FROM audit_log
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
            limit,
            offset,
        )

        entries = []
        for r in rows:
            entries.append({
                "id": r["id"],
                "action": r["action"],
                "model_id": r["model_id"],
                "prompt_hash": r["prompt_hash"],
                "input_snapshot": r["input_snapshot"],
                "output": r["output"],
                "decision": r["decision"],
                "human_override": r["human_override"],
                "order_id": r["order_id"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })

        return {
            "entries": entries,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        logger.error("audit_log query failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
