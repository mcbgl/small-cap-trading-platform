"""
Drawdown circuit breakers.

Monitors portfolio drawdown at multiple timeframes and triggers trading halts.
Velocity trigger: -1.5% in 10 minutes = immediate halt.

Breaker levels:
  - Intraday: -3%  -> flatten all, halt. Manual reset.
  - Weekly:   -5%  -> halt rest of week. Monday reset.
  - Monthly:  -8%  -> halt, full review. Owner reset.
  - All-time: -15% -> complete shutdown, formal audit.
  - Velocity: -1.5% in 10 min -> immediate halt.

All thresholds are enforced independently.  The most severe triggered breaker
determines the overall status.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Threshold constants
# ---------------------------------------------------------------------------

INTRADAY_DRAWDOWN_PCT = 3.0
WEEKLY_DRAWDOWN_PCT = 5.0
MONTHLY_DRAWDOWN_PCT = 8.0
ALL_TIME_DRAWDOWN_PCT = 15.0
VELOCITY_DRAWDOWN_PCT = 1.5
VELOCITY_WINDOW_SECONDS = 600  # 10 minutes

# Severity ordering (higher = more severe)
SEVERITY_ORDER: dict[str, int] = {
    "velocity": 1,
    "intraday": 2,
    "weekly": 3,
    "monthly": 4,
    "all_time": 5,
}

# Actions for each breaker level
BREAKER_ACTIONS: dict[str, str] = {
    "velocity": "immediate_halt",
    "intraday": "flatten_and_halt",
    "weekly": "halt_rest_of_week",
    "monthly": "halt_pending_review",
    "all_time": "complete_shutdown",
}

# Redis keys
REDIS_PNL_SNAPSHOTS = "pnl:snapshots"
REDIS_BREAKER_PREFIX = "circuit_breaker:"
REDIS_BREAKER_ACTIVE = "circuit_breaker:active"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Breaker:
    """A single circuit breaker that has been triggered."""

    level: str
    threshold_pct: float
    current_drawdown_pct: float
    action: str
    triggered_at: datetime

    @property
    def severity(self) -> int:
        return SEVERITY_ORDER.get(self.level, 0)


@dataclass(slots=True)
class CircuitBreakerStatus:
    """Aggregate status of all circuit breakers."""

    breakers_triggered: list[Breaker] = field(default_factory=list)
    trading_allowed: bool = True
    most_severe: str | None = None

    # Reference values used for evaluation
    current_value: float = 0.0
    day_start_value: float = 0.0
    week_start_value: float = 0.0
    month_start_value: float = 0.0
    peak_value: float = 0.0

    def add_breaker(self, breaker: Breaker) -> None:
        """Add a triggered breaker and update aggregate status."""
        self.breakers_triggered.append(breaker)
        self.trading_allowed = False

        if self.most_severe is None:
            self.most_severe = breaker.level
        else:
            current_severity = SEVERITY_ORDER.get(self.most_severe, 0)
            if breaker.severity > current_severity:
                self.most_severe = breaker.level


# ---------------------------------------------------------------------------
# Circuit Breaker Monitor
# ---------------------------------------------------------------------------

class CircuitBreakerMonitor:
    """
    Monitors portfolio drawdown and triggers circuit breakers.

    Tracks P&L snapshots in a Redis sorted set keyed by timestamp.
    Each check compares the current portfolio value against the relevant
    reference value (day start, week start, month start, all-time peak).

    Triggered breakers are persisted to both Redis (for fast runtime checks)
    and PostgreSQL (for audit trail and persistence across restarts).
    """

    def __init__(self, db_pool: asyncpg.Pool, redis: aioredis.Redis) -> None:
        self._db = db_pool
        self._redis = redis

    # ------------------------------------------------------------------
    # Snapshot recording
    # ------------------------------------------------------------------

    async def record_snapshot(self, portfolio_value: float) -> None:
        """
        Store a portfolio value snapshot with the current timestamp.

        Snapshots are stored in a Redis sorted set where:
          - score = Unix timestamp (float)
          - member = "ts:{timestamp}:{value}"

        Old snapshots (> 24h) are pruned on each write to bound memory usage.
        """
        now = time.time()
        member = f"ts:{now:.6f}:{portfolio_value:.2f}"
        await self._redis.zadd(REDIS_PNL_SNAPSHOTS, {member: now})

        # Prune entries older than 24 hours
        cutoff = now - 86_400
        await self._redis.zremrangebyscore(REDIS_PNL_SNAPSHOTS, "-inf", cutoff)

        logger.debug(
            "Recorded portfolio snapshot: $%.2f at %.0f",
            portfolio_value,
            now,
        )

    async def _persist_snapshot_to_db(
        self,
        portfolio_value: float,
        cash: float,
        invested: float,
        unrealized_pnl: float,
        realized_pnl: float,
        day_start_value: float,
        week_start_value: float,
        month_start_value: float,
        peak_value: float,
    ) -> None:
        """Persist a full snapshot to the portfolio_snapshots table for audit."""
        try:
            await self._db.execute(
                """
                INSERT INTO portfolio_snapshots (
                    portfolio_value, cash, invested, unrealized_pnl, realized_pnl,
                    day_start_value, week_start_value, month_start_value, peak_value
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                portfolio_value,
                cash,
                invested,
                unrealized_pnl,
                realized_pnl,
                day_start_value,
                week_start_value,
                month_start_value,
                peak_value,
            )
        except Exception:
            logger.exception("Failed to persist portfolio snapshot to DB")

    # ------------------------------------------------------------------
    # Individual breaker checks
    # ------------------------------------------------------------------

    def check_intraday(
        self,
        current_value: float,
        day_start_value: float,
    ) -> Breaker | None:
        """
        Intraday drawdown check: -3% from day start.

        Action: flatten all positions, halt trading.  Manual reset required.
        """
        if day_start_value <= 0:
            return None

        drawdown_pct = ((day_start_value - current_value) / day_start_value) * 100.0

        if drawdown_pct >= INTRADAY_DRAWDOWN_PCT:
            logger.critical(
                "INTRADAY CIRCUIT BREAKER TRIGGERED: %.2f%% drawdown "
                "(threshold: %.1f%%)",
                drawdown_pct,
                INTRADAY_DRAWDOWN_PCT,
            )
            return Breaker(
                level="intraday",
                threshold_pct=INTRADAY_DRAWDOWN_PCT,
                current_drawdown_pct=round(drawdown_pct, 4),
                action=BREAKER_ACTIONS["intraday"],
                triggered_at=datetime.now(timezone.utc),
            )

        return None

    def check_weekly(
        self,
        current_value: float,
        week_start_value: float,
    ) -> Breaker | None:
        """
        Weekly drawdown check: -5% from week start.

        Action: halt trading for rest of week.  Auto-resets Monday.
        """
        if week_start_value <= 0:
            return None

        drawdown_pct = ((week_start_value - current_value) / week_start_value) * 100.0

        if drawdown_pct >= WEEKLY_DRAWDOWN_PCT:
            logger.critical(
                "WEEKLY CIRCUIT BREAKER TRIGGERED: %.2f%% drawdown "
                "(threshold: %.1f%%)",
                drawdown_pct,
                WEEKLY_DRAWDOWN_PCT,
            )
            return Breaker(
                level="weekly",
                threshold_pct=WEEKLY_DRAWDOWN_PCT,
                current_drawdown_pct=round(drawdown_pct, 4),
                action=BREAKER_ACTIONS["weekly"],
                triggered_at=datetime.now(timezone.utc),
            )

        return None

    def check_monthly(
        self,
        current_value: float,
        month_start_value: float,
    ) -> Breaker | None:
        """
        Monthly drawdown check: -8% from month start.

        Action: halt trading, full review required.  Owner must reset.
        """
        if month_start_value <= 0:
            return None

        drawdown_pct = ((month_start_value - current_value) / month_start_value) * 100.0

        if drawdown_pct >= MONTHLY_DRAWDOWN_PCT:
            logger.critical(
                "MONTHLY CIRCUIT BREAKER TRIGGERED: %.2f%% drawdown "
                "(threshold: %.1f%%)",
                drawdown_pct,
                MONTHLY_DRAWDOWN_PCT,
            )
            return Breaker(
                level="monthly",
                threshold_pct=MONTHLY_DRAWDOWN_PCT,
                current_drawdown_pct=round(drawdown_pct, 4),
                action=BREAKER_ACTIONS["monthly"],
                triggered_at=datetime.now(timezone.utc),
            )

        return None

    def check_all_time(
        self,
        current_value: float,
        peak_value: float,
    ) -> Breaker | None:
        """
        All-time peak drawdown check: -15% from all-time high.

        Action: complete shutdown.  Formal audit required.
        """
        if peak_value <= 0:
            return None

        drawdown_pct = ((peak_value - current_value) / peak_value) * 100.0

        if drawdown_pct >= ALL_TIME_DRAWDOWN_PCT:
            logger.critical(
                "ALL-TIME CIRCUIT BREAKER TRIGGERED: %.2f%% drawdown from peak "
                "(threshold: %.1f%%)",
                drawdown_pct,
                ALL_TIME_DRAWDOWN_PCT,
            )
            return Breaker(
                level="all_time",
                threshold_pct=ALL_TIME_DRAWDOWN_PCT,
                current_drawdown_pct=round(drawdown_pct, 4),
                action=BREAKER_ACTIONS["all_time"],
                triggered_at=datetime.now(timezone.utc),
            )

        return None

    async def check_velocity(self) -> Breaker | None:
        """
        Velocity drawdown check: -1.5% in the last 10 minutes.

        Reads recent P&L snapshots from Redis and computes the maximum
        drawdown within the velocity window.

        Action: immediate halt.
        """
        now = time.time()
        window_start = now - VELOCITY_WINDOW_SECONDS

        # Fetch all snapshots in the 10-minute window
        members = await self._redis.zrangebyscore(
            REDIS_PNL_SNAPSHOTS,
            min=window_start,
            max=now,
        )

        if len(members) < 2:
            return None

        # Parse snapshot values
        values: list[tuple[float, float]] = []
        for member in members:
            try:
                parts = member.split(":")
                ts = float(parts[1])
                val = float(parts[2])
                values.append((ts, val))
            except (IndexError, ValueError):
                continue

        if len(values) < 2:
            return None

        # Find the peak value in the window and the current (latest) value
        peak_in_window = max(v for _, v in values)
        current_value = values[-1][1]

        if peak_in_window <= 0:
            return None

        drawdown_pct = ((peak_in_window - current_value) / peak_in_window) * 100.0

        if drawdown_pct >= VELOCITY_DRAWDOWN_PCT:
            logger.critical(
                "VELOCITY CIRCUIT BREAKER TRIGGERED: %.2f%% drawdown in %d-second window "
                "(threshold: %.1f%%)",
                drawdown_pct,
                VELOCITY_WINDOW_SECONDS,
                VELOCITY_DRAWDOWN_PCT,
            )
            return Breaker(
                level="velocity",
                threshold_pct=VELOCITY_DRAWDOWN_PCT,
                current_drawdown_pct=round(drawdown_pct, 4),
                action=BREAKER_ACTIONS["velocity"],
                triggered_at=datetime.now(timezone.utc),
            )

        return None

    # ------------------------------------------------------------------
    # Aggregate check
    # ------------------------------------------------------------------

    async def check_all(
        self,
        current_value: float,
        day_start_value: float,
        week_start_value: float,
        month_start_value: float,
        peak_value: float,
    ) -> CircuitBreakerStatus:
        """
        Run all circuit breaker checks and return aggregate status.

        Checks run in order of increasing severity.  All are evaluated
        independently (a velocity trigger does not prevent checking the
        monthly breaker).
        """
        status = CircuitBreakerStatus(
            current_value=current_value,
            day_start_value=day_start_value,
            week_start_value=week_start_value,
            month_start_value=month_start_value,
            peak_value=peak_value,
        )

        # Check each breaker independently
        checks: list[Breaker | None] = [
            await self.check_velocity(),
            self.check_intraday(current_value, day_start_value),
            self.check_weekly(current_value, week_start_value),
            self.check_monthly(current_value, month_start_value),
            self.check_all_time(current_value, peak_value),
        ]

        for breaker in checks:
            if breaker is not None:
                status.add_breaker(breaker)
                await self._persist_breaker_event(breaker)
                await self._set_redis_breaker(breaker)

        if status.breakers_triggered:
            logger.warning(
                "Circuit breaker status: %d breakers triggered, "
                "most severe = %s, trading_allowed = %s",
                len(status.breakers_triggered),
                status.most_severe,
                status.trading_allowed,
            )

        return status

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_breaker_event(self, breaker: Breaker) -> None:
        """Record a circuit breaker event in the database for audit trail."""
        try:
            await self._db.execute(
                """
                INSERT INTO circuit_breaker_events (
                    breaker_level, threshold_pct, drawdown_pct,
                    action, triggered_at
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                breaker.level,
                breaker.threshold_pct,
                breaker.current_drawdown_pct,
                breaker.action,
                breaker.triggered_at,
            )
        except Exception:
            logger.exception(
                "Failed to persist circuit breaker event: %s",
                breaker.level,
            )

    async def _set_redis_breaker(self, breaker: Breaker) -> None:
        """Set a circuit breaker flag in Redis for fast runtime lookups."""
        key = f"{REDIS_BREAKER_PREFIX}{breaker.level}"
        data = {
            "level": breaker.level,
            "threshold_pct": str(breaker.threshold_pct),
            "drawdown_pct": str(breaker.current_drawdown_pct),
            "action": breaker.action,
            "triggered_at": breaker.triggered_at.isoformat(),
        }
        await self._redis.hset(key, mapping=data)
        # Add to the set of active breakers
        await self._redis.sadd(REDIS_BREAKER_ACTIVE, breaker.level)

    async def is_any_breaker_active(self) -> bool:
        """Check if any circuit breaker is currently active."""
        members = await self._redis.smembers(REDIS_BREAKER_ACTIVE)
        return len(members) > 0

    async def get_active_breakers(self) -> list[str]:
        """Return list of currently active breaker levels."""
        members = await self._redis.smembers(REDIS_BREAKER_ACTIVE)
        return sorted(members, key=lambda x: SEVERITY_ORDER.get(x, 0))

    async def reset_breaker(self, level: str, reset_by: str) -> bool:
        """
        Reset (deactivate) a specific circuit breaker.

        Records the reset in the database and removes the Redis flag.
        Returns True if the breaker was active and is now reset.
        """
        key = f"{REDIS_BREAKER_PREFIX}{level}"
        existed = await self._redis.exists(key)

        if not existed:
            logger.warning("Attempted to reset inactive breaker: %s", level)
            return False

        # Remove from Redis
        await self._redis.delete(key)
        await self._redis.srem(REDIS_BREAKER_ACTIVE, level)

        # Record the reset in DB
        try:
            await self._db.execute(
                """
                UPDATE circuit_breaker_events
                SET reset_at = NOW(), reset_by = $1
                WHERE breaker_level = $2
                  AND reset_at IS NULL
                """,
                reset_by,
                level,
            )
        except Exception:
            logger.exception("Failed to record breaker reset in DB: %s", level)

        logger.info(
            "Circuit breaker '%s' reset by %s",
            level,
            reset_by,
        )
        return True

    # ------------------------------------------------------------------
    # Dashboard status
    # ------------------------------------------------------------------

    async def get_status(self) -> dict:
        """
        Return current circuit breaker status for the dashboard.

        Includes all breaker states, reference values, and whether
        trading is allowed.
        """
        active_levels = await self.get_active_breakers()
        breaker_details: list[dict] = []

        for level in active_levels:
            key = f"{REDIS_BREAKER_PREFIX}{level}"
            data = await self._redis.hgetall(key)
            if data:
                breaker_details.append(data)

        # Fetch latest snapshot from Redis
        latest_members = await self._redis.zrevrangebyscore(
            REDIS_PNL_SNAPSHOTS,
            max="+inf",
            min="-inf",
            start=0,
            num=1,
        )

        latest_value = None
        if latest_members:
            try:
                latest_value = float(latest_members[0].split(":")[2])
            except (IndexError, ValueError):
                pass

        return {
            "trading_allowed": len(active_levels) == 0,
            "active_breakers": active_levels,
            "breaker_details": breaker_details,
            "latest_portfolio_value": latest_value,
            "severity_order": SEVERITY_ORDER,
        }
