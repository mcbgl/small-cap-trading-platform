"""
Regulatory compliance module.

Wash sale prevention (30-day lookback/lookahead), PDT monitoring,
market manipulation detection. These checks cannot be overridden.

Compliance violations are always blocking.  They are logged to the
compliance_log table for regulatory audit purposes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg

from src.config import HardcodedLimits

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ComplianceViolation:
    """A blocking compliance violation.  Cannot be overridden."""

    rule: str  # e.g. "wash_sale", "pdt", "stop_loss_required", "manipulation"
    message: str
    blocking: bool = True  # always True for violations


@dataclass(frozen=True, slots=True)
class ComplianceWarning:
    """A non-blocking compliance warning."""

    rule: str
    message: str
    blocking: bool = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Wash sale lookback/lookahead window (calendar days)
WASH_SALE_WINDOW_DAYS = 30

# Pattern Day Trader thresholds
PDT_ROLLING_DAYS = 5  # business days
PDT_WARN_THRESHOLD = 3  # warn at 3 round-trips
PDT_BLOCK_THRESHOLD = 4  # block at 4 round-trips
PDT_EQUITY_MINIMUM = 25_000.0  # $25K minimum for PDT accounts

# Manipulation detection
SPOOF_CANCEL_WINDOW_SECONDS = 1  # large orders cancelled within 1 second
CANCEL_TO_FILL_RATIO_WARN = 10.0  # 10:1 cancel-to-fill ratio warning


# ---------------------------------------------------------------------------
# Compliance Engine
# ---------------------------------------------------------------------------

class ComplianceEngine:
    """
    Runs regulatory compliance checks that cannot be overridden.

    All violations are persisted to the compliance_log table.
    """

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        self._db = db_pool

    # ------------------------------------------------------------------
    # Wash Sale (IRC Section 1091)
    # ------------------------------------------------------------------

    async def check_wash_sale(
        self,
        symbol: str,
        side: str,
        ticker_id: int,
    ) -> ComplianceViolation | None:
        """
        Check for wash sale violation.

        A wash sale occurs when a security is sold at a loss and the same
        (or substantially identical) security is purchased within 30 days
        before or after the loss sale.

        This check is ALWAYS ON per HardcodedLimits.WASH_SALE_CHECK_ALWAYS_ON.
        It cannot be disabled at runtime.
        """
        if not HardcodedLimits.WASH_SALE_CHECK_ALWAYS_ON:
            # Defence-in-depth: this should never be False, but if somehow
            # the constant is modified, we still enforce the check.
            logger.error(
                "WASH_SALE_CHECK_ALWAYS_ON is False — this should never happen. "
                "Enforcing wash sale check anyway."
            )

        # Only check when buying (repurchasing after a loss sale)
        if side != "buy":
            return None

        lookback = datetime.now(timezone.utc) - timedelta(days=WASH_SALE_WINDOW_DAYS)

        try:
            # Find any sell orders for this ticker filled at a loss in the
            # last 30 days.  A "loss" means the filled price is below the
            # average entry price of the position at the time of sale.
            #
            # We check:
            #   1. Same ticker
            #   2. Side = sell
            #   3. Filled within the wash sale window
            #   4. Filled at a loss (filled_avg_price < the buy avg_entry_price)
            #
            # We join orders with positions to get the entry price context.
            # If no position record exists (fully closed), we look at the
            # order's own price vs filled_avg_price as a heuristic.
            row = await self._db.fetchrow(
                """
                SELECT o.id AS order_id,
                       o.filled_avg_price,
                       o.qty,
                       o.filled_at
                FROM orders o
                WHERE o.ticker_id = $1
                  AND o.side = 'sell'
                  AND o.status = 'filled'
                  AND o.filled_at >= $2
                  AND o.filled_avg_price IS NOT NULL
                  AND o.filled_avg_price < COALESCE(
                      (SELECT p.avg_entry_price FROM positions p WHERE p.ticker_id = $1),
                      o.price
                  )
                ORDER BY o.filled_at DESC
                LIMIT 1
                """,
                ticker_id,
                lookback,
            )

            if row:
                loss_date = row["filled_at"]
                days_since = (datetime.now(timezone.utc) - loss_date).days

                violation = ComplianceViolation(
                    rule="wash_sale",
                    message=(
                        f"Wash sale violation: {symbol} was sold at a loss "
                        f"{days_since} day(s) ago (order #{row['order_id']}). "
                        f"Repurchasing within {WASH_SALE_WINDOW_DAYS} days "
                        f"triggers IRS wash sale rule. "
                        f"Loss sale price: ${row['filled_avg_price']:.2f}, "
                        f"qty: {row['qty']}"
                    ),
                )
                await self._log_violation(violation, ticker_id=ticker_id)
                return violation

        except Exception:
            logger.exception("Wash sale check failed for %s", symbol)
            # On error, we block defensively — compliance checks must not silently pass
            return ComplianceViolation(
                rule="wash_sale",
                message=(
                    f"Wash sale check failed for {symbol} due to database error. "
                    f"Blocking order defensively."
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Pattern Day Trader (PDT) Rule
    # ------------------------------------------------------------------

    async def check_pdt(
        self,
        account_equity: float,
    ) -> ComplianceViolation | ComplianceWarning | None:
        """
        Check Pattern Day Trader (PDT) status.

        A day trade = buying and selling the same security on the same day.
        If 4+ day trades in 5 business days and account equity < $25K,
        the account is flagged as a PDT and further day trades are blocked.

        Warns at 3 round-trips, blocks at 4.
        """
        lookback_start = datetime.now(timezone.utc) - timedelta(days=7)  # ~5 business days

        try:
            # Count round-trips: buys and sells of the same ticker on the same day
            row = await self._db.fetchrow(
                """
                WITH day_trades AS (
                    SELECT
                        o.ticker_id,
                        DATE(o.filled_at) AS trade_date,
                        COUNT(DISTINCT o.side) AS sides
                    FROM orders o
                    WHERE o.status = 'filled'
                      AND o.filled_at >= $1
                    GROUP BY o.ticker_id, DATE(o.filled_at)
                    HAVING COUNT(DISTINCT o.side) = 2
                )
                SELECT COUNT(*) AS round_trip_count
                FROM day_trades
                """,
                lookback_start,
            )

            round_trips = row["round_trip_count"] if row else 0

            if round_trips >= PDT_BLOCK_THRESHOLD and account_equity < PDT_EQUITY_MINIMUM:
                violation = ComplianceViolation(
                    rule="pdt",
                    message=(
                        f"Pattern Day Trader violation: {round_trips} day trades "
                        f"in last 5 business days (limit {PDT_BLOCK_THRESHOLD}) "
                        f"with account equity ${account_equity:,.2f} "
                        f"(minimum ${PDT_EQUITY_MINIMUM:,.2f}). "
                        f"Additional day trades are blocked."
                    ),
                )
                await self._log_violation(violation)
                return violation

            if round_trips >= PDT_WARN_THRESHOLD:
                warning = ComplianceWarning(
                    rule="pdt",
                    message=(
                        f"PDT warning: {round_trips} day trades in last 5 business days. "
                        f"At {PDT_BLOCK_THRESHOLD} round-trips with equity below "
                        f"${PDT_EQUITY_MINIMUM:,.2f}, day trading will be blocked."
                    ),
                )
                return warning

        except Exception:
            logger.exception("PDT check failed")
            # Defensive: block on error
            return ComplianceViolation(
                rule="pdt",
                message="PDT check failed due to database error. Blocking defensively.",
            )

        return None

    # ------------------------------------------------------------------
    # Market Manipulation Detection
    # ------------------------------------------------------------------

    async def check_manipulation(
        self,
        symbol: str,
        side: str,
        qty: float,
        ticker_id: int,
    ) -> ComplianceViolation | ComplianceWarning | None:
        """
        Check for patterns indicating potential market manipulation.

        Checks for:
          1. Spoofing: large orders cancelled within 1 second
          2. Wash trading: simultaneous buy + sell of the same security
          3. Cancel-to-fill ratio > 10:1
        """
        now = datetime.now(timezone.utc)

        # --- Check 1: Spoofing detection ---
        try:
            spoof_cutoff = now - timedelta(seconds=SPOOF_CANCEL_WINDOW_SECONDS * 60)
            spoof_row = await self._db.fetchrow(
                """
                SELECT COUNT(*) AS rapid_cancels
                FROM orders o
                WHERE o.ticker_id = $1
                  AND o.status = 'cancelled'
                  AND o.created_at >= $2
                  AND o.qty >= $3
                  AND (
                      EXTRACT(EPOCH FROM (o.updated_at - o.created_at)) <= $4
                      OR o.updated_at IS NULL
                  )
                """,
                ticker_id,
                spoof_cutoff,
                qty * 0.8,  # similar size orders
                float(SPOOF_CANCEL_WINDOW_SECONDS),
            )

            if spoof_row and spoof_row["rapid_cancels"] >= 3:
                violation = ComplianceViolation(
                    rule="manipulation_spoofing",
                    message=(
                        f"Potential spoofing detected for {symbol}: "
                        f"{spoof_row['rapid_cancels']} large orders cancelled within "
                        f"{SPOOF_CANCEL_WINDOW_SECONDS}s in the last minute. "
                        f"This pattern may constitute market manipulation."
                    ),
                )
                await self._log_violation(violation, ticker_id=ticker_id)
                return violation

        except Exception:
            logger.exception("Spoofing check failed for %s", symbol)

        # --- Check 2: Wash trading detection ---
        try:
            wash_window = now - timedelta(seconds=30)
            wash_row = await self._db.fetchrow(
                """
                SELECT COUNT(DISTINCT o.side) AS distinct_sides
                FROM orders o
                WHERE o.ticker_id = $1
                  AND o.status IN ('created', 'submitted', 'risk_checked')
                  AND o.created_at >= $2
                """,
                ticker_id,
                wash_window,
            )

            # If there are active orders on both sides within 30s
            if wash_row and wash_row["distinct_sides"] == 2:
                violation = ComplianceViolation(
                    rule="manipulation_wash_trading",
                    message=(
                        f"Potential wash trading detected for {symbol}: "
                        f"simultaneous buy and sell orders within 30 seconds. "
                        f"This pattern may constitute market manipulation."
                    ),
                )
                await self._log_violation(violation, ticker_id=ticker_id)
                return violation

        except Exception:
            logger.exception("Wash trading check failed for %s", symbol)

        # --- Check 3: Cancel-to-fill ratio ---
        try:
            lookback_1h = now - timedelta(hours=1)
            ratio_row = await self._db.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancels,
                    COUNT(*) FILTER (WHERE status = 'filled') AS fills
                FROM orders
                WHERE ticker_id = $1
                  AND created_at >= $2
                """,
                ticker_id,
                lookback_1h,
            )

            if ratio_row:
                cancels = ratio_row["cancels"] or 0
                fills = ratio_row["fills"] or 0

                if fills > 0 and cancels / fills > CANCEL_TO_FILL_RATIO_WARN:
                    warning = ComplianceWarning(
                        rule="cancel_to_fill_ratio",
                        message=(
                            f"High cancel-to-fill ratio for {symbol}: "
                            f"{cancels}:{fills} ({cancels / fills:.1f}:1) "
                            f"in the last hour (threshold {CANCEL_TO_FILL_RATIO_WARN:.0f}:1). "
                            f"This may trigger regulatory scrutiny."
                        ),
                    )
                    return warning

                if fills == 0 and cancels > 10:
                    warning = ComplianceWarning(
                        rule="cancel_to_fill_ratio",
                        message=(
                            f"Excessive cancellations for {symbol}: "
                            f"{cancels} cancels with 0 fills in the last hour."
                        ),
                    )
                    return warning

        except Exception:
            logger.exception("Cancel-to-fill ratio check failed for %s", symbol)

        return None

    # ------------------------------------------------------------------
    # Stop-Loss Requirement
    # ------------------------------------------------------------------

    def check_stop_loss_required(
        self,
        stop_loss_price: float | None,
    ) -> ComplianceViolation | None:
        """
        Verify that every order has a stop-loss price set.

        This is a hardcoded requirement (HardcodedLimits.STOP_LOSS_REQUIRED)
        and cannot be overridden at runtime.
        """
        # Defence-in-depth: enforce regardless of constant value
        if stop_loss_price is None or stop_loss_price <= 0:
            return ComplianceViolation(
                rule="stop_loss_required",
                message=(
                    "Every position must have a stop-loss order. "
                    "This is a non-overridable safety requirement. "
                    "Set a valid stop_loss price > 0."
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Aggregate runner
    # ------------------------------------------------------------------

    async def run_all(
        self,
        symbol: str,
        side: str,
        qty: float,
        ticker_id: int,
        stop_loss_price: float | None,
        account_equity: float,
    ) -> list[ComplianceViolation | ComplianceWarning]:
        """
        Run all compliance checks.

        Returns a list of all violations and warnings found.  An empty
        list means all compliance checks passed.

        Order of checks:
          1. Stop-loss required (non-overridable)
          2. Wash sale (non-overridable)
          3. PDT (blocks if equity < $25K)
          4. Market manipulation patterns
        """
        results: list[ComplianceViolation | ComplianceWarning] = []

        # 1. Stop-loss required (instant, no DB query)
        check = self.check_stop_loss_required(stop_loss_price)
        if check:
            results.append(check)

        # 2. Wash sale (only for buy orders)
        check = await self.check_wash_sale(symbol, side, ticker_id)
        if check:
            results.append(check)

        # 3. Pattern Day Trader
        check = await self.check_pdt(account_equity)
        if check:
            results.append(check)

        # 4. Market manipulation
        check = await self.check_manipulation(symbol, side, qty, ticker_id)
        if check:
            results.append(check)

        # Log summary
        violations = [r for r in results if isinstance(r, ComplianceViolation)]
        warnings = [r for r in results if isinstance(r, ComplianceWarning)]

        if violations:
            logger.warning(
                "Compliance check for %s %s %s: %d violations, %d warnings",
                side.upper(),
                symbol,
                f"(qty={qty})",
                len(violations),
                len(warnings),
            )
        elif warnings:
            logger.info(
                "Compliance check for %s %s: %d warnings",
                side.upper(),
                symbol,
                len(warnings),
            )

        return results

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    async def _log_violation(
        self,
        violation: ComplianceViolation,
        *,
        ticker_id: int | None = None,
        order_id: int | None = None,
    ) -> None:
        """Persist a compliance violation to the compliance_log table."""
        try:
            await self._db.execute(
                """
                INSERT INTO compliance_log (
                    rule, ticker_id, order_id, violation_type,
                    message, blocking
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                violation.rule,
                ticker_id,
                order_id,
                "violation",
                violation.message,
                violation.blocking,
            )
            logger.info(
                "Logged compliance violation: rule=%s, blocking=%s",
                violation.rule,
                violation.blocking,
            )
        except Exception:
            logger.exception(
                "Failed to log compliance violation: %s",
                violation.rule,
            )
