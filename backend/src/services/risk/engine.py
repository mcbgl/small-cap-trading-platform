"""
Pre-trade risk engine.

Runs all risk checks before order submission. Returns pass/fail with detailed
reasons. Enforces hardcoded limits that can never be overridden.

Check sequence (all run, all violations collected):
  1. Kill switch / circuit breaker — is trading halted?
  2. Stop-loss required (hardcoded, non-overridable)
  3. Max order value ($500K hardcoded, $50K configurable)
  4. Position sizing (2% per trade, 5% per name)
  5. Sector concentration (15%)
  6. OTC / distressed limits
  7. Portfolio utilization (50% default)
  8. Fat finger (price deviation, max shares, max notional)
  9. Duplicate detection (same ticker+side+size in 5s)
  10. Rate limiting (orders/min, hour, day; cancels/min)
  11. Liquidity check (% of ADV, min ADV, max spread)
  12. Market hours (no market orders in extended hours)
  13. Compliance (wash sale, PDT, manipulation)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from src.config import HardcodedLimits, settings
from src.services.risk.circuit_breakers import (
    CircuitBreakerMonitor,
    CircuitBreakerStatus,
)
from src.services.risk.compliance import (
    ComplianceEngine,
    ComplianceViolation,
    ComplianceWarning,
)
from src.services.risk.position_limits import (
    AccountState,
    OrderCandidate,
    PositionLimitChecker,
    RiskViolation,
    RiskWarning,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RiskCheckResult:
    """Aggregate result of all pre-trade risk checks."""

    passed: bool = True
    violations: list[RiskViolation] = field(default_factory=list)
    warnings: list[RiskWarning] = field(default_factory=list)
    compliance_violations: list[ComplianceViolation] = field(default_factory=list)
    compliance_warnings: list[ComplianceWarning] = field(default_factory=list)
    circuit_breaker_status: CircuitBreakerStatus | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0

    @property
    def all_violations_count(self) -> int:
        return len(self.violations) + len(self.compliance_violations)

    @property
    def all_warnings_count(self) -> int:
        return len(self.warnings) + len(self.compliance_warnings)

    def to_dict(self) -> dict:
        """Serialize for API responses and audit logging."""
        return {
            "passed": self.passed,
            "violations": [asdict(v) for v in self.violations],
            "warnings": [asdict(w) for w in self.warnings],
            "compliance_violations": [asdict(v) for v in self.compliance_violations],
            "compliance_warnings": [asdict(w) for w in self.compliance_warnings],
            "violation_count": self.all_violations_count,
            "warning_count": self.all_warnings_count,
            "checked_at": self.checked_at.isoformat(),
            "duration_ms": round(self.duration_ms, 2),
        }


# ---------------------------------------------------------------------------
# Fat Finger thresholds
# ---------------------------------------------------------------------------

FAT_FINGER_PRICE_LAST_TRADE_PCT = 10.0  # >10% from last trade -> reject
FAT_FINGER_PRICE_VWAP_PCT = 15.0  # >15% from VWAP -> reject
FAT_FINGER_MAX_ORDER_VALUE = 50_000.0  # $50K per order (configurable)
FAT_FINGER_MAX_SHARES = 100_000  # 100K shares per order
FAT_FINGER_MAX_NOTIONAL_PER_MINUTE = 200_000.0  # $200K/minute

# Duplicate detection
DUPLICATE_WINDOW_SECONDS = 5

# Rate limits
RATE_LIMIT_ORDERS_PER_MINUTE = 10
RATE_LIMIT_ORDERS_PER_HOUR = 60
RATE_LIMIT_ORDERS_PER_DAY = 200  # also in settings.orders_per_day
RATE_LIMIT_CANCELS_PER_MINUTE = 20

# Liquidity
LIQUIDITY_MAX_ADV_PCT = 5.0  # max 5% of 20-day ADV per order
LIQUIDITY_MIN_ADV_SHARES = 10_000  # minimum 10K shares ADV
LIQUIDITY_MIN_ADV_DOLLAR = 50_000.0  # minimum $50K dollar volume ADV
LIQUIDITY_MAX_SPREAD_PCT = 5.0  # max 5% of mid price

# Redis key prefixes
REDIS_KILL_SWITCH_PREFIX = "kill_switch:"
REDIS_RATE_LIMIT_PREFIX = "rate_limit:"
REDIS_DUPLICATE_PREFIX = "order:dedup:"
REDIS_NOTIONAL_RATE_PREFIX = "notional:minute:"


# ---------------------------------------------------------------------------
# Risk Engine
# ---------------------------------------------------------------------------

class RiskEngine:
    """
    Central pre-trade risk engine.

    Orchestrates all risk checks:  position limits, compliance, circuit
    breakers, fat-finger protection, rate limiting, liquidity checks,
    and kill switch state.

    All checks run to completion — even if an early check fails, the
    remaining checks still execute so the caller gets a complete picture
    of all violations.
    """

    def __init__(self, db_pool: asyncpg.Pool, redis: aioredis.Redis) -> None:
        self._db = db_pool
        self._redis = redis
        self._position_checker = PositionLimitChecker(db_pool)
        self._compliance = ComplianceEngine(db_pool)
        self._circuit_breakers = CircuitBreakerMonitor(db_pool, redis)

    # ------------------------------------------------------------------
    # Pre-trade check (main entry point)
    # ------------------------------------------------------------------

    async def pre_trade_check(
        self,
        order: OrderCandidate,
        account: AccountState,
    ) -> RiskCheckResult:
        """
        Run ALL risk checks before order submission.

        Every check runs regardless of earlier failures so the caller
        receives a complete list of all violations and warnings.

        Returns a RiskCheckResult where passed=True only if zero
        blocking violations were found.
        """
        t0 = time.monotonic()
        result = RiskCheckResult()

        # --- 1. Kill switch / trading halt check ---
        halted, halt_reason = await self.is_trading_halted()
        if halted:
            result.violations.append(
                RiskViolation(
                    check_name="kill_switch",
                    message=f"Trading is halted: {halt_reason}",
                    severity="block",
                    current_value=0.0,
                    limit_value=0.0,
                )
            )

        # --- 2. Circuit breaker check ---
        cb_status = await self.check_circuit_breakers()
        result.circuit_breaker_status = cb_status
        if not cb_status.trading_allowed:
            breaker_names = ", ".join(
                b.level for b in cb_status.breakers_triggered
            )
            result.violations.append(
                RiskViolation(
                    check_name="circuit_breaker",
                    message=(
                        f"Circuit breaker(s) triggered: {breaker_names}. "
                        f"Most severe: {cb_status.most_severe}"
                    ),
                    severity="block",
                    current_value=0.0,
                    limit_value=0.0,
                )
            )

        # --- 3. Stop-loss required (hardcoded, non-overridable) ---
        if order.side == "buy":
            sl_check = self._compliance.check_stop_loss_required(order.stop_loss)
            if sl_check:
                result.compliance_violations.append(sl_check)

        # --- 4. Max order value (hardcoded absolute + configurable) ---
        notional = order.notional_value
        if notional > HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE:
            result.violations.append(
                RiskViolation(
                    check_name="max_order_value_absolute",
                    message=(
                        f"Order value ${notional:,.2f} exceeds absolute maximum "
                        f"${HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE:,.2f} "
                        f"(hardcoded, non-overridable)"
                    ),
                    severity="block",
                    current_value=notional,
                    limit_value=HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE,
                )
            )
        elif notional > FAT_FINGER_MAX_ORDER_VALUE:
            result.violations.append(
                RiskViolation(
                    check_name="max_order_value",
                    message=(
                        f"Order value ${notional:,.2f} exceeds configurable maximum "
                        f"${FAT_FINGER_MAX_ORDER_VALUE:,.2f}"
                    ),
                    severity="block",
                    current_value=notional,
                    limit_value=FAT_FINGER_MAX_ORDER_VALUE,
                )
            )

        # --- 5-7. Position limits (size, concentration, OTC, distressed, utilization) ---
        position_results = await self._position_checker.run_all(order, account)
        for check in position_results:
            if isinstance(check, RiskViolation):
                result.violations.append(check)
            elif isinstance(check, RiskWarning):
                result.warnings.append(check)

        # --- 8. Fat finger protection ---
        fat_finger_results = self._check_fat_finger(order)
        for check in fat_finger_results:
            if isinstance(check, RiskViolation):
                result.violations.append(check)
            elif isinstance(check, RiskWarning):
                result.warnings.append(check)

        # --- 9. Duplicate detection ---
        dup_check = await self._check_duplicate(order)
        if dup_check:
            result.violations.append(dup_check)

        # --- 10. Rate limiting ---
        rate_results = await self._check_rate_limits()
        for check in rate_results:
            if isinstance(check, RiskViolation):
                result.violations.append(check)
            elif isinstance(check, RiskWarning):
                result.warnings.append(check)

        # --- 11. Liquidity check ---
        liquidity_results = self._check_liquidity(order)
        for check in liquidity_results:
            if isinstance(check, RiskViolation):
                result.violations.append(check)
            elif isinstance(check, RiskWarning):
                result.warnings.append(check)

        # --- 12. Market hours check ---
        market_check = self._check_market_hours(order)
        if market_check:
            result.violations.append(market_check)

        # --- 13. Compliance checks (wash sale, PDT, manipulation) ---
        compliance_results = await self._compliance.run_all(
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            ticker_id=order.ticker_id,
            stop_loss_price=order.stop_loss,
            account_equity=account.nav,
        )
        for check in compliance_results:
            if isinstance(check, ComplianceViolation):
                # Avoid double-counting stop_loss_required (already checked above)
                if check.rule != "stop_loss_required":
                    result.compliance_violations.append(check)
            elif isinstance(check, ComplianceWarning):
                result.compliance_warnings.append(check)

        # --- Determine pass/fail ---
        result.passed = (
            len(result.violations) == 0
            and len(result.compliance_violations) == 0
        )

        result.duration_ms = (time.monotonic() - t0) * 1000.0

        # Log outcome
        if result.passed:
            logger.info(
                "Risk check PASSED for %s %s %s ($%.2f) in %.1fms — %d warnings",
                order.side.upper(),
                order.symbol,
                f"qty={order.qty}",
                notional,
                result.duration_ms,
                result.all_warnings_count,
            )
        else:
            logger.warning(
                "Risk check FAILED for %s %s %s ($%.2f) in %.1fms — "
                "%d violations, %d warnings",
                order.side.upper(),
                order.symbol,
                f"qty={order.qty}",
                notional,
                result.duration_ms,
                result.all_violations_count,
                result.all_warnings_count,
            )

        # Audit log
        await self._audit_risk_check(order, result)

        return result

    # ------------------------------------------------------------------
    # Fat finger protection
    # ------------------------------------------------------------------

    def _check_fat_finger(
        self,
        order: OrderCandidate,
    ) -> list[RiskViolation | RiskWarning]:
        """
        Fat finger protection checks.

        - Price: >10% from last trade or >15% from VWAP -> reject
        - Size: Max 100K shares per order
        - Notional: Max $50K per order (checked separately in pre_trade_check)
        """
        results: list[RiskViolation | RiskWarning] = []

        # Price deviation from last trade
        if order.price and order.last_trade_price and order.last_trade_price > 0:
            deviation_pct = (
                abs(order.price - order.last_trade_price) / order.last_trade_price
            ) * 100.0

            if deviation_pct > FAT_FINGER_PRICE_LAST_TRADE_PCT:
                results.append(
                    RiskViolation(
                        check_name="fat_finger_price_last_trade",
                        message=(
                            f"Order price ${order.price:.4f} deviates "
                            f"{deviation_pct:.2f}% from last trade "
                            f"${order.last_trade_price:.4f} "
                            f"(limit {FAT_FINGER_PRICE_LAST_TRADE_PCT:.1f}%)"
                        ),
                        severity="block",
                        current_value=deviation_pct,
                        limit_value=FAT_FINGER_PRICE_LAST_TRADE_PCT,
                    )
                )

        # Price deviation from VWAP
        if order.price and order.vwap and order.vwap > 0:
            vwap_deviation_pct = (
                abs(order.price - order.vwap) / order.vwap
            ) * 100.0

            if vwap_deviation_pct > FAT_FINGER_PRICE_VWAP_PCT:
                results.append(
                    RiskViolation(
                        check_name="fat_finger_price_vwap",
                        message=(
                            f"Order price ${order.price:.4f} deviates "
                            f"{vwap_deviation_pct:.2f}% from VWAP "
                            f"${order.vwap:.4f} "
                            f"(limit {FAT_FINGER_PRICE_VWAP_PCT:.1f}%)"
                        ),
                        severity="block",
                        current_value=vwap_deviation_pct,
                        limit_value=FAT_FINGER_PRICE_VWAP_PCT,
                    )
                )

        # Max shares per order
        if order.qty > FAT_FINGER_MAX_SHARES:
            results.append(
                RiskViolation(
                    check_name="fat_finger_max_shares",
                    message=(
                        f"Order quantity {order.qty:,.0f} shares exceeds "
                        f"maximum {FAT_FINGER_MAX_SHARES:,} shares per order"
                    ),
                    severity="block",
                    current_value=order.qty,
                    limit_value=float(FAT_FINGER_MAX_SHARES),
                )
            )

        return results

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    async def _check_duplicate(
        self,
        order: OrderCandidate,
    ) -> RiskViolation | None:
        """
        Detect duplicate orders: same ticker+side+size within 5 seconds.

        Uses Redis with a TTL-based key to detect rapid duplicates.
        """
        # Compose a dedup key from ticker+side+quantity
        dedup_key = (
            f"{REDIS_DUPLICATE_PREFIX}"
            f"{order.symbol}:{order.side}:{order.qty:.4f}"
        )

        try:
            exists = await self._redis.exists(dedup_key)
            if exists:
                return RiskViolation(
                    check_name="duplicate_order",
                    message=(
                        f"Duplicate order detected: {order.side.upper()} "
                        f"{order.qty} {order.symbol} within "
                        f"{DUPLICATE_WINDOW_SECONDS}s of identical order"
                    ),
                    severity="block",
                    current_value=1.0,
                    limit_value=0.0,
                )

            # Mark this order pattern for the dedup window
            await self._redis.setex(
                dedup_key,
                DUPLICATE_WINDOW_SECONDS,
                "1",
            )
        except Exception:
            logger.exception("Duplicate detection check failed")
            # Non-blocking on Redis failure — log but allow
            pass

        return None

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _check_rate_limits(
        self,
    ) -> list[RiskViolation | RiskWarning]:
        """
        Check order rate limits:
          - 10 orders/min
          - 60 orders/hour
          - 200 orders/day (bounded by settings.orders_per_day)
          - 20 cancels/min
        """
        results: list[RiskViolation | RiskWarning] = []
        now = time.time()

        try:
            # --- Orders per minute ---
            minute_key = f"{REDIS_RATE_LIMIT_PREFIX}orders:minute"
            await self._redis.zadd(minute_key, {f"o:{now:.6f}": now})
            await self._redis.zremrangebyscore(minute_key, "-inf", now - 60)
            await self._redis.expire(minute_key, 120)

            minute_count = await self._redis.zcard(minute_key)
            if minute_count > RATE_LIMIT_ORDERS_PER_MINUTE:
                results.append(
                    RiskViolation(
                        check_name="rate_limit_per_minute",
                        message=(
                            f"Order rate limit exceeded: {minute_count} orders "
                            f"in last minute (limit {RATE_LIMIT_ORDERS_PER_MINUTE})"
                        ),
                        severity="block",
                        current_value=float(minute_count),
                        limit_value=float(RATE_LIMIT_ORDERS_PER_MINUTE),
                    )
                )

            # --- Orders per hour ---
            hour_key = f"{REDIS_RATE_LIMIT_PREFIX}orders:hour"
            await self._redis.zadd(hour_key, {f"o:{now:.6f}": now})
            await self._redis.zremrangebyscore(hour_key, "-inf", now - 3600)
            await self._redis.expire(hour_key, 7200)

            hour_count = await self._redis.zcard(hour_key)
            if hour_count > RATE_LIMIT_ORDERS_PER_HOUR:
                results.append(
                    RiskViolation(
                        check_name="rate_limit_per_hour",
                        message=(
                            f"Order rate limit exceeded: {hour_count} orders "
                            f"in last hour (limit {RATE_LIMIT_ORDERS_PER_HOUR})"
                        ),
                        severity="block",
                        current_value=float(hour_count),
                        limit_value=float(RATE_LIMIT_ORDERS_PER_HOUR),
                    )
                )

            # --- Orders per day ---
            effective_daily_limit = min(
                RATE_LIMIT_ORDERS_PER_DAY,
                settings.orders_per_day,
                settings.max_daily_orders,
            )
            day_key = f"{REDIS_RATE_LIMIT_PREFIX}orders:day"
            await self._redis.zadd(day_key, {f"o:{now:.6f}": now})
            await self._redis.zremrangebyscore(day_key, "-inf", now - 86400)
            await self._redis.expire(day_key, 172800)

            day_count = await self._redis.zcard(day_key)
            if day_count > effective_daily_limit:
                results.append(
                    RiskViolation(
                        check_name="rate_limit_per_day",
                        message=(
                            f"Daily order limit exceeded: {day_count} orders "
                            f"today (limit {effective_daily_limit})"
                        ),
                        severity="block",
                        current_value=float(day_count),
                        limit_value=float(effective_daily_limit),
                    )
                )
            elif day_count > effective_daily_limit * 0.9:
                results.append(
                    RiskWarning(
                        check_name="rate_limit_per_day",
                        message=(
                            f"Approaching daily order limit: {day_count} of "
                            f"{effective_daily_limit} orders used"
                        ),
                        severity="alert",
                        current_value=float(day_count),
                        limit_value=float(effective_daily_limit),
                    )
                )

        except Exception:
            logger.exception("Rate limit check failed")

        return results

    async def record_cancel(self) -> RiskViolation | None:
        """
        Record an order cancellation and check cancel rate limit.

        Call this when an order is cancelled.
        Returns a violation if cancel rate limit (20/min) is exceeded.
        """
        now = time.time()
        cancel_key = f"{REDIS_RATE_LIMIT_PREFIX}cancels:minute"

        try:
            await self._redis.zadd(cancel_key, {f"c:{now:.6f}": now})
            await self._redis.zremrangebyscore(cancel_key, "-inf", now - 60)
            await self._redis.expire(cancel_key, 120)

            cancel_count = await self._redis.zcard(cancel_key)
            if cancel_count > RATE_LIMIT_CANCELS_PER_MINUTE:
                return RiskViolation(
                    check_name="cancel_rate_limit",
                    message=(
                        f"Cancel rate limit exceeded: {cancel_count} cancels "
                        f"in last minute (limit {RATE_LIMIT_CANCELS_PER_MINUTE})"
                    ),
                    severity="block",
                    current_value=float(cancel_count),
                    limit_value=float(RATE_LIMIT_CANCELS_PER_MINUTE),
                )
        except Exception:
            logger.exception("Cancel rate limit check failed")

        return None

    # ------------------------------------------------------------------
    # Notional rate tracking
    # ------------------------------------------------------------------

    async def _check_notional_rate(
        self,
        order_value: float,
    ) -> RiskViolation | None:
        """
        Check notional order value rate: max $200K/minute.

        Tracks cumulative notional value of orders submitted in a rolling
        1-minute window.
        """
        now = time.time()
        key = REDIS_NOTIONAL_RATE_PREFIX

        try:
            # Add this order's notional value
            await self._redis.zadd(key, {f"n:{now:.6f}:{order_value:.2f}": now})
            await self._redis.zremrangebyscore(key, "-inf", now - 60)
            await self._redis.expire(key, 120)

            # Sum all values in the window
            members = await self._redis.zrangebyscore(key, now - 60, now)
            total_notional = 0.0
            for member in members:
                try:
                    total_notional += float(member.split(":")[2])
                except (IndexError, ValueError):
                    continue

            if total_notional > FAT_FINGER_MAX_NOTIONAL_PER_MINUTE:
                return RiskViolation(
                    check_name="notional_rate_limit",
                    message=(
                        f"Notional rate limit exceeded: ${total_notional:,.2f} "
                        f"in last minute (limit "
                        f"${FAT_FINGER_MAX_NOTIONAL_PER_MINUTE:,.2f}/min)"
                    ),
                    severity="block",
                    current_value=total_notional,
                    limit_value=FAT_FINGER_MAX_NOTIONAL_PER_MINUTE,
                )
        except Exception:
            logger.exception("Notional rate limit check failed")

        return None

    # ------------------------------------------------------------------
    # Liquidity checks
    # ------------------------------------------------------------------

    def _check_liquidity(
        self,
        order: OrderCandidate,
    ) -> list[RiskViolation | RiskWarning]:
        """
        Liquidity checks:
          - Max 5% of 20-day ADV per order
          - Min ADV: 10K shares or $50K dollar volume
          - Max spread: 5% of mid price
        """
        results: list[RiskViolation | RiskWarning] = []

        # --- Max % of ADV ---
        if order.avg_daily_volume and order.avg_daily_volume > 0:
            adv_pct = (order.qty / order.avg_daily_volume) * 100.0

            if adv_pct > LIQUIDITY_MAX_ADV_PCT:
                results.append(
                    RiskViolation(
                        check_name="liquidity_adv_pct",
                        message=(
                            f"Order qty {order.qty:,.0f} is {adv_pct:.2f}% of "
                            f"20-day ADV ({order.avg_daily_volume:,.0f} shares). "
                            f"Limit: {LIQUIDITY_MAX_ADV_PCT:.1f}%"
                        ),
                        severity="block",
                        current_value=adv_pct,
                        limit_value=LIQUIDITY_MAX_ADV_PCT,
                    )
                )

            # Min ADV check (shares)
            if order.avg_daily_volume < LIQUIDITY_MIN_ADV_SHARES:
                results.append(
                    RiskWarning(
                        check_name="liquidity_min_adv_shares",
                        message=(
                            f"{order.symbol} ADV ({order.avg_daily_volume:,.0f} shares) "
                            f"below minimum threshold ({LIQUIDITY_MIN_ADV_SHARES:,} shares). "
                            f"Low liquidity risk."
                        ),
                        severity="alert",
                        current_value=float(order.avg_daily_volume),
                        limit_value=float(LIQUIDITY_MIN_ADV_SHARES),
                    )
                )

        # --- Min ADV dollar volume ---
        if (
            order.avg_daily_dollar_volume is not None
            and order.avg_daily_dollar_volume < LIQUIDITY_MIN_ADV_DOLLAR
        ):
            results.append(
                RiskWarning(
                    check_name="liquidity_min_adv_dollar",
                    message=(
                        f"{order.symbol} ADV dollar volume "
                        f"(${order.avg_daily_dollar_volume:,.2f}) "
                        f"below minimum (${LIQUIDITY_MIN_ADV_DOLLAR:,.2f}). "
                        f"Low liquidity risk."
                    ),
                    severity="alert",
                    current_value=order.avg_daily_dollar_volume,
                    limit_value=LIQUIDITY_MIN_ADV_DOLLAR,
                )
            )

        # --- Max spread ---
        if order.bid and order.ask and order.bid > 0 and order.ask > 0:
            mid = (order.bid + order.ask) / 2.0
            spread = order.ask - order.bid
            spread_pct = (spread / mid) * 100.0

            if spread_pct > LIQUIDITY_MAX_SPREAD_PCT:
                results.append(
                    RiskViolation(
                        check_name="liquidity_max_spread",
                        message=(
                            f"{order.symbol} spread ${spread:.4f} "
                            f"({spread_pct:.2f}% of mid ${mid:.4f}) "
                            f"exceeds {LIQUIDITY_MAX_SPREAD_PCT:.1f}% limit"
                        ),
                        severity="block",
                        current_value=spread_pct,
                        limit_value=LIQUIDITY_MAX_SPREAD_PCT,
                    )
                )

        return results

    # ------------------------------------------------------------------
    # Market hours check
    # ------------------------------------------------------------------

    def _check_market_hours(
        self,
        order: OrderCandidate,
    ) -> RiskViolation | None:
        """
        Block market orders in pre/post market hours.

        When settings.no_extended_hours is True, also block all non-limit
        orders outside regular trading hours.  When settings.limit_orders_only
        is True, block all market orders regardless of time.
        """
        # If limit_orders_only is set, reject any non-limit order
        if settings.limit_orders_only and order.order_type != "limit":
            return RiskViolation(
                check_name="limit_orders_only",
                message=(
                    f"Only limit orders are allowed (got {order.order_type}). "
                    f"Market/stop orders are disabled by configuration."
                ),
                severity="block",
                current_value=0.0,
                limit_value=0.0,
            )

        # Market orders blocked in extended hours (basic time-based check)
        if settings.no_extended_hours and order.order_type == "market":
            now_utc = datetime.now(timezone.utc)
            # US market hours: 9:30 AM - 4:00 PM ET = 14:30 - 21:00 UTC
            # (This is a simplified check; production should use proper
            # market calendar with holidays and DST adjustments.)
            hour_utc = now_utc.hour
            minute_utc = now_utc.minute

            market_open = (hour_utc == 14 and minute_utc >= 30) or hour_utc > 14
            market_close = hour_utc < 21

            if not (market_open and market_close):
                return RiskViolation(
                    check_name="extended_hours_market_order",
                    message=(
                        "Market orders are not allowed outside regular trading "
                        "hours (9:30 AM - 4:00 PM ET). Use a limit order instead."
                    ),
                    severity="block",
                    current_value=0.0,
                    limit_value=0.0,
                )

        return None

    # ------------------------------------------------------------------
    # Circuit breakers
    # ------------------------------------------------------------------

    async def check_circuit_breakers(self) -> CircuitBreakerStatus:
        """
        Check all circuit breakers against current portfolio state.

        Reads reference values (day/week/month start, peak) from the
        latest portfolio snapshot in the database.
        """
        try:
            row = await self._db.fetchrow(
                """
                SELECT portfolio_value, day_start_value, week_start_value,
                       month_start_value, peak_value
                FROM portfolio_snapshots
                ORDER BY snapshot_at DESC
                LIMIT 1
                """
            )

            if not row:
                # No snapshots yet — cannot evaluate breakers
                return CircuitBreakerStatus(trading_allowed=True)

            return await self._circuit_breakers.check_all(
                current_value=float(row["portfolio_value"]),
                day_start_value=float(row["day_start_value"] or row["portfolio_value"]),
                week_start_value=float(row["week_start_value"] or row["portfolio_value"]),
                month_start_value=float(row["month_start_value"] or row["portfolio_value"]),
                peak_value=float(row["peak_value"] or row["portfolio_value"]),
            )
        except Exception:
            logger.exception("Circuit breaker check failed — defaulting to safe (halted)")
            # On failure, assume the worst — halt trading
            status = CircuitBreakerStatus(trading_allowed=False)
            status.most_severe = "error"
            return status

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    async def trigger_kill_switch(
        self,
        level: str,
        triggered_by: str = "system",
        reason: str = "",
    ) -> None:
        """
        Activate a kill switch at the specified level.

        Levels:
          - "strategy": stop a specific strategy from trading
          - "account":  stop all trading for this account
          - "system":   cancel all open orders, flatten all positions,
                        halt all trading system-wide

        Kill switch state is stored in both Redis (fast runtime check) and
        PostgreSQL (persistence across restarts).
        """
        if level not in ("strategy", "account", "system"):
            raise ValueError(f"Invalid kill switch level: {level}")

        logger.critical(
            "KILL SWITCH TRIGGERED: level=%s, by=%s, reason=%s",
            level,
            triggered_by,
            reason,
        )

        now = datetime.now(timezone.utc)

        # Set in Redis
        redis_key = f"{REDIS_KILL_SWITCH_PREFIX}{level}"
        await self._redis.hset(redis_key, mapping={
            "active": "true",
            "triggered_at": now.isoformat(),
            "triggered_by": triggered_by,
            "reason": reason,
        })

        # Persist to DB
        try:
            await self._db.execute(
                """
                UPDATE kill_switch_state
                SET active = true, triggered_at = $1, triggered_by = $2, reason = $3
                WHERE level = $4
                """,
                now,
                triggered_by,
                reason,
                level,
            )
        except Exception:
            logger.exception("Failed to persist kill switch state to DB")

        # Audit log
        try:
            await self._db.execute(
                """
                INSERT INTO audit_log (action, output, created_at)
                VALUES ($1, $2::jsonb, NOW())
                """,
                f"kill_switch_triggered:{level}",
                json.dumps({
                    "level": level,
                    "triggered_by": triggered_by,
                    "reason": reason,
                }),
            )
        except Exception:
            logger.exception("Failed to write kill switch audit log")

        # System-level: cancel all open orders and flatten positions
        if level == "system":
            await self._emergency_flatten()

    async def _emergency_flatten(self) -> None:
        """
        Emergency position flattening for system-level kill switch.

        Cancels all open orders and marks all positions for closing.
        Actual broker order submission is handled by the execution service.
        """
        logger.critical("EMERGENCY FLATTEN: Cancelling all open orders")

        try:
            # Cancel all non-terminal orders
            cancelled = await self._db.execute(
                """
                UPDATE orders
                SET status = 'cancelled', updated_at = NOW()
                WHERE status IN ('created', 'risk_checked', 'submitted')
                """
            )
            logger.critical("Emergency flatten: cancelled orders — %s", cancelled)

            # Publish flatten command to execution service via Redis
            await self._redis.publish(
                "channel:emergency",
                json.dumps({
                    "action": "flatten_all",
                    "triggered_at": datetime.now(timezone.utc).isoformat(),
                }),
            )
        except Exception:
            logger.exception("Emergency flatten failed — MANUAL INTERVENTION REQUIRED")

    async def is_trading_halted(self) -> tuple[bool, str]:
        """
        Check if trading is halted at any kill switch level.

        Returns (is_halted, reason).  Checks Redis first (fast), falls
        back to DB if Redis is unavailable.
        """
        levels = ("system", "account", "strategy")

        for level in levels:
            redis_key = f"{REDIS_KILL_SWITCH_PREFIX}{level}"
            try:
                data = await self._redis.hgetall(redis_key)
                if data and data.get("active") == "true":
                    reason = data.get("reason", f"{level} kill switch active")
                    return True, f"{level}: {reason}"
            except Exception:
                logger.warning("Redis kill switch check failed for %s, checking DB", level)

        # Fallback: check PostgreSQL
        try:
            row = await self._db.fetchrow(
                """
                SELECT level, reason
                FROM kill_switch_state
                WHERE active = true
                ORDER BY
                    CASE level
                        WHEN 'system' THEN 1
                        WHEN 'account' THEN 2
                        WHEN 'strategy' THEN 3
                    END
                LIMIT 1
                """
            )
            if row:
                return True, f"{row['level']}: {row['reason'] or 'kill switch active'}"
        except Exception:
            logger.exception("Kill switch DB check failed — assuming halted for safety")
            return True, "Kill switch check failed — halted for safety"

        # Also check circuit breakers
        breaker_active = await self._circuit_breakers.is_any_breaker_active()
        if breaker_active:
            active = await self._circuit_breakers.get_active_breakers()
            return True, f"Circuit breaker(s) active: {', '.join(active)}"

        return False, ""

    async def reset_kill_switch(
        self,
        level: str,
        reset_by: str = "manual",
    ) -> bool:
        """
        Reset (deactivate) a kill switch at the specified level.

        Requires explicit action — kill switches never auto-reset.
        Returns True if the switch was active and is now reset.
        """
        if level not in ("strategy", "account", "system"):
            raise ValueError(f"Invalid kill switch level: {level}")

        logger.info("Kill switch reset: level=%s, by=%s", level, reset_by)

        redis_key = f"{REDIS_KILL_SWITCH_PREFIX}{level}"

        # Clear Redis
        await self._redis.delete(redis_key)

        # Clear DB
        try:
            result = await self._db.execute(
                """
                UPDATE kill_switch_state
                SET active = false, triggered_at = NULL, triggered_by = NULL, reason = NULL
                WHERE level = $1 AND active = true
                """,
                level,
            )
            was_active = result and "UPDATE 1" in result
        except Exception:
            logger.exception("Failed to reset kill switch in DB")
            was_active = False

        # Audit log
        try:
            await self._db.execute(
                """
                INSERT INTO audit_log (action, output, created_at)
                VALUES ($1, $2::jsonb, NOW())
                """,
                f"kill_switch_reset:{level}",
                json.dumps({"level": level, "reset_by": reset_by}),
            )
        except Exception:
            logger.exception("Failed to write kill switch reset audit log")

        return was_active

    # ------------------------------------------------------------------
    # Dashboard status
    # ------------------------------------------------------------------

    async def get_risk_status(self) -> dict:
        """
        Return comprehensive risk status for the dashboard.

        Includes:
          - Kill switch states
          - Circuit breaker states
          - Rate limit usage
          - Current portfolio metrics
          - Recent violations
        """
        halted, halt_reason = await self.is_trading_halted()
        cb_status = await self._circuit_breakers.get_status()

        # Rate limit usage
        now = time.time()
        rate_usage = {}
        try:
            minute_key = f"{REDIS_RATE_LIMIT_PREFIX}orders:minute"
            hour_key = f"{REDIS_RATE_LIMIT_PREFIX}orders:hour"
            day_key = f"{REDIS_RATE_LIMIT_PREFIX}orders:day"

            rate_usage = {
                "orders_per_minute": {
                    "current": await self._redis.zcount(minute_key, now - 60, now),
                    "limit": RATE_LIMIT_ORDERS_PER_MINUTE,
                },
                "orders_per_hour": {
                    "current": await self._redis.zcount(hour_key, now - 3600, now),
                    "limit": RATE_LIMIT_ORDERS_PER_HOUR,
                },
                "orders_per_day": {
                    "current": await self._redis.zcount(day_key, now - 86400, now),
                    "limit": min(
                        RATE_LIMIT_ORDERS_PER_DAY,
                        settings.orders_per_day,
                        settings.max_daily_orders,
                    ),
                },
            }
        except Exception:
            logger.exception("Failed to read rate limit usage")

        # Kill switch states
        kill_switches = {}
        for level in ("strategy", "account", "system"):
            redis_key = f"{REDIS_KILL_SWITCH_PREFIX}{level}"
            try:
                data = await self._redis.hgetall(redis_key)
                kill_switches[level] = {
                    "active": data.get("active") == "true" if data else False,
                    "triggered_at": data.get("triggered_at") if data else None,
                    "triggered_by": data.get("triggered_by") if data else None,
                    "reason": data.get("reason") if data else None,
                }
            except Exception:
                kill_switches[level] = {"active": False, "error": "unavailable"}

        # Recent compliance violations
        recent_violations = []
        try:
            rows = await self._db.fetch(
                """
                SELECT rule, message, blocking, created_at
                FROM compliance_log
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
            recent_violations = [
                {
                    "rule": row["rule"],
                    "message": row["message"],
                    "blocking": row["blocking"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in rows
            ]
        except Exception:
            logger.exception("Failed to fetch recent compliance violations")

        return {
            "trading_halted": halted,
            "halt_reason": halt_reason,
            "kill_switches": kill_switches,
            "circuit_breakers": cb_status,
            "rate_limits": rate_usage,
            "recent_compliance_violations": recent_violations,
            "settings": {
                "max_position_pct": settings.max_position_pct,
                "daily_drawdown_pct": settings.daily_drawdown_pct,
                "weekly_drawdown_pct": settings.weekly_drawdown_pct,
                "max_portfolio_utilization_pct": settings.max_portfolio_utilization_pct,
                "orders_per_day": settings.orders_per_day,
                "limit_orders_only": settings.limit_orders_only,
                "no_extended_hours": settings.no_extended_hours,
                "shadow_mode": settings.shadow_mode,
                "paper_mode": settings.paper_mode,
            },
            "hardcoded_limits": {
                "absolute_max_position_pct": HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT,
                "absolute_max_drawdown_pct": HardcodedLimits.ABSOLUTE_MAX_DRAWDOWN_PCT,
                "absolute_max_order_value": HardcodedLimits.ABSOLUTE_MAX_ORDER_VALUE,
                "stop_loss_required": HardcodedLimits.STOP_LOSS_REQUIRED,
                "wash_sale_check_always_on": HardcodedLimits.WASH_SALE_CHECK_ALWAYS_ON,
            },
        }

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    async def _audit_risk_check(
        self,
        order: OrderCandidate,
        result: RiskCheckResult,
    ) -> None:
        """Write the risk check result to the audit log."""
        try:
            decision = "pass" if result.passed else "reject"
            await self._db.execute(
                """
                INSERT INTO audit_log (
                    action, input_snapshot, output, decision, created_at
                )
                VALUES ($1, $2::jsonb, $3::jsonb, $4, NOW())
                """,
                "pre_trade_risk_check",
                json.dumps({
                    "symbol": order.symbol,
                    "side": order.side,
                    "qty": order.qty,
                    "price": order.price,
                    "notional": order.notional_value,
                    "order_type": order.order_type,
                }),
                json.dumps(result.to_dict()),
                decision,
            )
        except Exception:
            logger.exception("Failed to write risk check audit log")
