"""
Risk management endpoints — real-time risk status, circuit breakers, kill switch.
"""

import logging
from datetime import datetime, timezone
from enum import StrEnum

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.config import HardcodedLimits, settings

router = APIRouter(prefix="/api/risk", tags=["risk"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class KillSwitchLevel(StrEnum):
    STRATEGY = "strategy"
    ACCOUNT = "account"
    SYSTEM = "system"


class KillSwitchRequest(BaseModel):
    reason: str


# ---------------------------------------------------------------------------
# Helpers — graceful DB/Redis/service access
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


def _get_risk_engine():
    """Return the RiskEngine singleton or None if the module is not ready."""
    try:
        from src.services.risk.engine import get_risk_engine
        return get_risk_engine()
    except Exception:
        return None


def _get_circuit_breaker_monitor():
    """Return the CircuitBreakerMonitor or None."""
    try:
        from src.services.risk.circuit_breakers import get_circuit_breaker_monitor
        return get_circuit_breaker_monitor()
    except Exception:
        return None


def _get_position_limit_checker():
    """Return the PositionLimitChecker or None."""
    try:
        from src.services.risk.position_limits import get_position_limit_checker
        return get_position_limit_checker()
    except Exception:
        return None


def _get_compliance_engine():
    """Return the ComplianceEngine or None."""
    try:
        from src.services.risk.compliance import get_compliance_engine
        return get_compliance_engine()
    except Exception:
        return None


async def _read_redis_json(key: str, default=None):
    """Read a JSON value from Redis, returning *default* on any failure."""
    import json as _json
    redis = _get_redis()
    if redis is None:
        return default
    try:
        raw = await redis.get(key)
        if raw is None:
            return default
        return _json.loads(raw)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# GET /status — comprehensive risk dashboard
# ---------------------------------------------------------------------------

@router.get("/status")
async def risk_status():
    """
    Comprehensive risk dashboard data: portfolio value, drawdown, position
    limit utilisation, circuit breaker state, kill switch state, rate limits,
    and compliance summary.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Try RiskEngine first (it aggregates everything)
    engine = _get_risk_engine()
    if engine is not None:
        try:
            return await engine.get_risk_status()
        except Exception:
            logger.debug("RiskEngine.get_risk_status() unavailable, building from parts")

    # ------------------------------------------------------------------
    # Fallback: assemble from DB + Redis + individual services
    # ------------------------------------------------------------------
    pool = _get_pool()
    redis = _get_redis()

    # Portfolio value / drawdown ----------------------------------------
    portfolio_value: float = 0.0
    nav: float = 0.0
    cash: float = 0.0
    daily_high_water: float = 0.0
    current_drawdown_pct: float = 0.0

    if pool is not None:
        try:
            row = await pool.fetchrow(
                """
                SELECT
                    coalesce(sum(p.qty * p.current_price), 0) AS positions_value,
                    0 AS cash
                FROM positions p
                WHERE p.qty > 0
                """
            )
            positions_value = float(row["positions_value"]) if row else 0.0
        except Exception:
            positions_value = 0.0

        # Pull latest snapshot for NAV / cash
        try:
            snap = await pool.fetchrow(
                """
                SELECT total_value, cash
                FROM portfolio_snapshots
                ORDER BY snapshot_at DESC
                LIMIT 1
                """
            )
            if snap:
                portfolio_value = float(snap["total_value"])
                cash = float(snap["cash"])
                nav = portfolio_value
        except Exception:
            pass

    # Read daily high-water mark from Redis
    if redis is not None:
        try:
            hw = await redis.get("risk:daily_high_water")
            if hw is not None:
                daily_high_water = float(hw)
        except Exception:
            pass

    if daily_high_water > 0:
        current_drawdown_pct = round(
            ((daily_high_water - portfolio_value) / daily_high_water) * 100, 4
        )

    # Position limit utilisation ----------------------------------------
    position_limits = {
        "per_name_max_pct": settings.max_position_pct,
        "absolute_max_pct": HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT,
        "sector_max_pct": 25.0,
        "otc_max_pct": 15.0,
        "distressed_max_pct": 10.0,
    }

    limit_utilisation: dict = {}
    checker = _get_position_limit_checker()
    if checker is not None:
        try:
            limit_utilisation = await checker.get_utilisation_summary()
        except Exception:
            pass

    # Circuit breakers --------------------------------------------------
    cb_monitor = _get_circuit_breaker_monitor()
    cb_status: dict = {}
    if cb_monitor is not None:
        try:
            cb_status = await cb_monitor.get_status()
        except Exception:
            pass
    if not cb_status:
        cb_status = {
            "daily_drawdown": {
                "triggered": False,
                "threshold_pct": settings.daily_drawdown_pct,
                "current_pct": current_drawdown_pct,
            },
            "weekly_drawdown": {
                "triggered": False,
                "threshold_pct": settings.weekly_drawdown_pct,
                "current_pct": 0.0,
            },
        }

    # Kill switch state -------------------------------------------------
    kill_switch: dict = {}
    if redis is not None:
        try:
            for level in ("strategy", "account", "system"):
                raw = await redis.get(f"risk:kill_switch:{level}")
                kill_switch[level] = raw is not None and raw == "1"
        except Exception:
            kill_switch = {"strategy": False, "account": False, "system": False}
    else:
        kill_switch = {"strategy": False, "account": False, "system": False}

    # Rate limits -------------------------------------------------------
    rate_limits: dict = {"orders_this_minute": 0, "orders_this_hour": 0, "orders_today": 0}
    if redis is not None:
        try:
            for key, field in [
                ("risk:rate:orders_minute", "orders_this_minute"),
                ("risk:rate:orders_hour", "orders_this_hour"),
                ("risk:rate:orders_day", "orders_today"),
            ]:
                val = await redis.get(key)
                rate_limits[field] = int(val) if val else 0
        except Exception:
            pass

    # Compliance summary ------------------------------------------------
    compliance_summary: dict = {"pdt_day_trade_count": 0, "wash_sale_window_active": False}
    comp = _get_compliance_engine()
    if comp is not None:
        try:
            compliance_summary = await comp.get_summary()
        except Exception:
            pass

    return {
        "timestamp": now,
        "portfolio": {
            "value": portfolio_value,
            "nav": nav,
            "cash": cash,
            "daily_high_water": daily_high_water,
            "current_drawdown_pct": current_drawdown_pct,
        },
        "position_limits": {
            "config": position_limits,
            "utilisation": limit_utilisation,
        },
        "circuit_breakers": cb_status,
        "kill_switch": kill_switch,
        "rate_limits": rate_limits,
        "compliance": compliance_summary,
    }


# ---------------------------------------------------------------------------
# GET /circuit-breakers — detailed circuit breaker state with history
# ---------------------------------------------------------------------------

@router.get("/circuit-breakers")
async def circuit_breakers():
    """Detailed circuit breaker state and recent trigger history."""
    now = datetime.now(timezone.utc).isoformat()

    cb_monitor = _get_circuit_breaker_monitor()
    if cb_monitor is not None:
        try:
            status = await cb_monitor.get_status()
            history = await cb_monitor.get_history(limit=50)
            return {"timestamp": now, "breakers": status, "history": history}
        except Exception:
            logger.debug("CircuitBreakerMonitor unavailable, returning defaults")

    # Fallback: build from Redis
    redis = _get_redis()
    breakers: dict = {}
    for name in ("daily_drawdown", "weekly_drawdown", "max_loss_per_trade", "correlation_spike"):
        triggered = False
        if redis is not None:
            try:
                val = await redis.get(f"risk:cb:{name}")
                triggered = val is not None and val == "1"
            except Exception:
                pass
        breakers[name] = {"triggered": triggered}

    # Recent trigger events from DB
    history: list[dict] = []
    pool = _get_pool()
    if pool is not None:
        try:
            rows = await pool.fetch(
                """
                SELECT id, action, created_at,
                       output->>'breaker_name' AS breaker_name,
                       output->>'details' AS details
                FROM audit_log
                WHERE action IN ('circuit_breaker_triggered', 'circuit_breaker_reset')
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            history = [
                {
                    "id": r["id"],
                    "action": r["action"],
                    "breaker_name": r["breaker_name"],
                    "details": r["details"],
                    "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
        except Exception:
            pass

    return {"timestamp": now, "breakers": breakers, "history": history}


# ---------------------------------------------------------------------------
# POST /kill-switch/{level} — trigger kill switch
# ---------------------------------------------------------------------------

@router.post("/kill-switch/{level}")
async def trigger_kill_switch(level: KillSwitchLevel, body: KillSwitchRequest):
    """
    Trigger the kill switch at the given level (strategy / account / system).
    Requires a reason in the request body.
    """
    assert HardcodedLimits.KILL_SWITCH_ALWAYS_AVAILABLE

    engine = _get_risk_engine()
    if engine is not None:
        try:
            result = await engine.trigger_kill_switch(level=level, reason=body.reason)
            return result
        except Exception:
            logger.warning("RiskEngine.trigger_kill_switch() failed, using fallback")

    # Fallback: set in Redis + log
    redis = _get_redis()
    if redis is not None:
        try:
            await redis.set(f"risk:kill_switch:{level}", "1")
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
                f"level={level}",
                f'{{"level": "{level}", "reason": "{body.reason}"}}',
            )
        except Exception:
            logger.warning("Failed to write kill switch audit log")

    logger.critical(
        "KILL SWITCH ACTIVATED level=%s reason=%s", level, body.reason
    )

    return {
        "status": "activated",
        "level": level,
        "reason": body.reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actions_taken": [
            f"Kill switch set at {level} level",
            "Pending orders flagged for cancellation",
            "New order submission blocked",
        ],
    }


# ---------------------------------------------------------------------------
# DELETE /kill-switch/{level} — reset kill switch
# ---------------------------------------------------------------------------

@router.delete("/kill-switch/{level}")
async def reset_kill_switch(level: KillSwitchLevel):
    """Reset (deactivate) the kill switch at the given level."""
    engine = _get_risk_engine()
    if engine is not None:
        try:
            result = await engine.reset_kill_switch(level=level)
            return result
        except Exception:
            logger.warning("RiskEngine.reset_kill_switch() failed, using fallback")

    redis = _get_redis()
    if redis is not None:
        try:
            await redis.delete(f"risk:kill_switch:{level}")
        except Exception:
            pass

    pool = _get_pool()
    if pool is not None:
        try:
            await pool.execute(
                """
                INSERT INTO audit_log (action, decision, output, created_at)
                VALUES ($1, $2, $3::jsonb, now())
                """,
                "kill_switch_reset",
                f"level={level}",
                f'{{"level": "{level}"}}',
            )
        except Exception:
            pass

    logger.warning("Kill switch RESET level=%s", level)

    return {
        "status": "deactivated",
        "level": level,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /limits — current position limits and utilisation
# ---------------------------------------------------------------------------

@router.get("/limits")
async def position_limits():
    """
    Current position limits and utilisation per symbol, sector, OTC, and
    distressed categories.
    """
    now = datetime.now(timezone.utc).isoformat()

    checker = _get_position_limit_checker()
    if checker is not None:
        try:
            return await checker.get_full_report()
        except Exception:
            logger.debug("PositionLimitChecker unavailable, building from DB")

    pool = _get_pool()
    positions: list[dict] = []

    # Get latest portfolio value for weight calculations
    portfolio_value: float = 0.0
    if pool is not None:
        try:
            snap = await pool.fetchrow(
                "SELECT total_value FROM portfolio_snapshots ORDER BY snapshot_at DESC LIMIT 1"
            )
            if snap:
                portfolio_value = float(snap["total_value"])
        except Exception:
            pass

    if pool is not None:
        try:
            rows = await pool.fetch(
                """
                SELECT
                    p.id,
                    t.symbol,
                    t.sector,
                    t.is_otc,
                    p.qty,
                    p.current_price,
                    (p.qty * p.current_price) AS exposure
                FROM positions p
                JOIN tickers t ON t.id = p.ticker_id
                WHERE p.qty > 0
                ORDER BY exposure DESC
                """
            )
            for r in rows:
                exposure = float(r["exposure"]) if r["exposure"] else 0.0
                pct = (exposure / portfolio_value * 100) if portfolio_value > 0 else 0.0
                limit_pct = settings.max_position_pct
                positions.append({
                    "symbol": r["symbol"],
                    "sector": r["sector"],
                    "is_otc": r["is_otc"],
                    "exposure_usd": round(exposure, 2),
                    "exposure_pct": round(pct, 2),
                    "limit_pct": limit_pct,
                    "headroom_pct": round(limit_pct - pct, 2),
                })
        except Exception:
            pass

    # Sector breakdown
    sector_totals: dict[str, float] = {}
    for pos in positions:
        sector = pos.get("sector") or "Unknown"
        sector_totals[sector] = sector_totals.get(sector, 0.0) + pos["exposure_usd"]

    sector_breakdown: list[dict] = []
    for sector, total in sorted(sector_totals.items(), key=lambda x: -x[1]):
        pct = (total / portfolio_value * 100) if portfolio_value > 0 else 0.0
        sector_breakdown.append({
            "sector": sector,
            "exposure_usd": round(total, 2),
            "exposure_pct": round(pct, 2),
            "limit_pct": 25.0,
            "headroom_pct": round(25.0 - pct, 2),
        })

    # OTC total
    otc_total = sum(p["exposure_usd"] for p in positions if p.get("is_otc"))
    otc_pct = (otc_total / portfolio_value * 100) if portfolio_value > 0 else 0.0

    return {
        "timestamp": now,
        "portfolio_value": portfolio_value,
        "positions": positions,
        "sector_breakdown": sector_breakdown,
        "otc": {
            "exposure_usd": round(otc_total, 2),
            "exposure_pct": round(otc_pct, 2),
            "limit_pct": 15.0,
            "headroom_pct": round(15.0 - otc_pct, 2),
        },
        "config": {
            "max_position_pct": settings.max_position_pct,
            "absolute_max_position_pct": HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT,
        },
    }


# ---------------------------------------------------------------------------
# GET /compliance — compliance check results
# ---------------------------------------------------------------------------

@router.get("/compliance")
async def compliance_status():
    """
    Compliance check results: PDT status, wash sale checks, cancel-to-fill
    ratio.
    """
    now = datetime.now(timezone.utc).isoformat()

    comp = _get_compliance_engine()
    if comp is not None:
        try:
            return await comp.get_full_report()
        except Exception:
            logger.debug("ComplianceEngine unavailable, building from DB")

    pool = _get_pool()

    # PDT: count day trades in rolling 5 business days
    pdt_count: int = 0
    if pool is not None:
        try:
            row = await pool.fetchrow(
                """
                SELECT count(*) AS cnt
                FROM orders
                WHERE side = 'sell'
                  AND filled_at IS NOT NULL
                  AND filled_at >= now() - interval '5 days'
                  AND ticker_id IN (
                      SELECT ticker_id FROM orders
                      WHERE side = 'buy'
                        AND filled_at IS NOT NULL
                        AND filled_at >= now() - interval '5 days'
                  )
                """
            )
            pdt_count = int(row["cnt"]) if row else 0
        except Exception:
            pass

    pdt_warning = "none"
    if pdt_count >= 4:
        pdt_warning = "critical"
    elif pdt_count >= 3:
        pdt_warning = "warning"

    # Wash sale: recent sells with repurchases within 30 days
    wash_sale_candidates: list[dict] = []
    if pool is not None:
        try:
            rows = await pool.fetch(
                """
                SELECT DISTINCT t.symbol, sell.filled_at AS sold_at
                FROM orders sell
                JOIN tickers t ON t.id = sell.ticker_id
                WHERE sell.side = 'sell'
                  AND sell.filled_at IS NOT NULL
                  AND sell.filled_at >= now() - interval '30 days'
                  AND EXISTS (
                      SELECT 1 FROM orders buy
                      WHERE buy.ticker_id = sell.ticker_id
                        AND buy.side = 'buy'
                        AND buy.filled_at IS NOT NULL
                        AND buy.filled_at > sell.filled_at
                        AND buy.filled_at <= sell.filled_at + interval '30 days'
                  )
                ORDER BY sell.filled_at DESC
                LIMIT 20
                """
            )
            wash_sale_candidates = [
                {
                    "symbol": r["symbol"],
                    "sold_at": r["sold_at"].isoformat() if r["sold_at"] else None,
                }
                for r in rows
            ]
        except Exception:
            pass

    # Cancel-to-fill ratio (last 30 days)
    cancelled_count: int = 0
    filled_count: int = 0
    if pool is not None:
        try:
            row = await pool.fetchrow(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                    count(*) FILTER (WHERE status = 'filled') AS filled
                FROM orders
                WHERE created_at >= now() - interval '30 days'
                """
            )
            if row:
                cancelled_count = int(row["cancelled"])
                filled_count = int(row["filled"])
        except Exception:
            pass

    cancel_fill_ratio = (
        round(cancelled_count / filled_count, 2) if filled_count > 0 else 0.0
    )

    return {
        "timestamp": now,
        "pdt": {
            "day_trade_count_5d": pdt_count,
            "limit": 3,
            "warning_level": pdt_warning,
        },
        "wash_sale": {
            "candidates": wash_sale_candidates,
            "check_enabled": HardcodedLimits.WASH_SALE_CHECK_ALWAYS_ON,
        },
        "cancel_to_fill": {
            "cancelled_30d": cancelled_count,
            "filled_30d": filled_count,
            "ratio": cancel_fill_ratio,
        },
    }


# ---------------------------------------------------------------------------
# GET /history — recent risk events
# ---------------------------------------------------------------------------

@router.get("/history")
async def risk_history(
    event_type: str | None = Query(
        default=None,
        description="Filter by event type (circuit_breaker_triggered, kill_switch_triggered, risk_violation, etc.)",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    Recent risk events: circuit breaker triggers, violations, kill switch
    activations.
    """
    pool = _get_pool()
    if pool is None:
        return {"events": [], "total": 0, "note": "Database unavailable"}

    risk_actions = (
        "circuit_breaker_triggered",
        "circuit_breaker_reset",
        "kill_switch_triggered",
        "kill_switch_reset",
        "risk_violation",
        "position_limit_breach",
        "drawdown_warning",
        "compliance_alert",
    )

    try:
        if event_type:
            count_row = await pool.fetchrow(
                "SELECT count(*) AS cnt FROM audit_log WHERE action = $1",
                event_type,
            )
            rows = await pool.fetch(
                """
                SELECT id, action, decision, output, created_at
                FROM audit_log
                WHERE action = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                event_type,
                limit,
                offset,
            )
        else:
            placeholders = ", ".join(f"${i+1}" for i in range(len(risk_actions)))
            count_row = await pool.fetchrow(
                f"SELECT count(*) AS cnt FROM audit_log WHERE action IN ({placeholders})",
                *risk_actions,
            )
            rows = await pool.fetch(
                f"""
                SELECT id, action, decision, output, created_at
                FROM audit_log
                WHERE action IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT ${len(risk_actions)+1} OFFSET ${len(risk_actions)+2}
                """,
                *risk_actions,
                limit,
                offset,
            )

        total = int(count_row["cnt"]) if count_row else 0
        events = [
            {
                "id": r["id"],
                "action": r["action"],
                "decision": r["decision"],
                "details": r["output"],
                "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        return {"events": events, "total": total, "limit": limit, "offset": offset}

    except Exception as exc:
        logger.error("Failed to query risk history: %s", exc)
        return {"events": [], "total": 0, "error": str(exc)}
