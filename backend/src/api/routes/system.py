"""
System endpoints — health, status, and emergency controls.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from src.config import HardcodedLimits, settings

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger(__name__)

# Module-level kill switch state
_kill_switch_active = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
async def system_health():
    """Detailed system health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": {
            "api": "ok",
            "database": "unknown",  # Will be checked against actual pool
            "redis": "unknown",
            "questdb": "unknown",
        },
        "kill_switch_active": _kill_switch_active,
    }


@router.get("/status")
async def system_status():
    """System status including data feeds, AI models, and resource usage."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kill_switch_active": _kill_switch_active,
        "mode": {
            "paper": settings.paper_mode,
            "shadow": settings.shadow_mode,
            "limit_orders_only": settings.limit_orders_only,
        },
        "guardrails": {
            "absolute_max_position_pct": HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT,
            "absolute_max_drawdown_pct": HardcodedLimits.ABSOLUTE_MAX_DRAWDOWN_PCT,
            "absolute_max_order_value": HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE,
            "max_position_pct": settings.max_position_pct,
            "daily_drawdown_pct": settings.daily_drawdown_pct,
            "human_approval_above_usd": settings.human_approval_above_usd,
        },
        "data_feeds": {
            "polygon": "disconnected",
            "edgar": "disconnected",
            "insider_api": "disconnected",
        },
        "ai_models": {
            "claude": "not_configured" if not settings.anthropic_api_key else "ready",
            "ollama": "disconnected",
        },
        "note": "Placeholder — will report real-time component status",
    }


@router.post("/kill-switch")
async def activate_kill_switch():
    """
    Emergency halt: cancel all pending orders and prevent new order submission.

    This is always available per Tier 1 hardcoded limits.
    """
    global _kill_switch_active

    assert HardcodedLimits.KILL_SWITCH_ALWAYS_AVAILABLE

    _kill_switch_active = True
    logger.critical("KILL SWITCH ACTIVATED — all trading halted")

    return {
        "status": "activated",
        "message": "Kill switch engaged — all pending orders will be cancelled, no new orders accepted",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actions_taken": [
            "Marked kill switch active",
            "Placeholder: cancel all pending orders",
            "Placeholder: close all WebSocket price feeds",
        ],
    }
