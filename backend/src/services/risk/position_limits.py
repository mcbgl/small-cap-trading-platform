"""
Position sizing and concentration limit enforcement.

Checks per-trade, per-name, per-sector, OTC, and distressed exposure limits.
All limits respect both configurable bounds and hardcoded absolute maximums.

Threshold tiers:
  - Alert (warning): approaching limit, non-blocking
  - Block (violation): at or above limit, blocks order
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import asyncpg

from src.config import HardcodedLimits, settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes shared by risk modules
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RiskViolation:
    """A blocking risk check failure."""

    check_name: str
    message: str
    severity: str  # "block" | "alert"
    current_value: float
    limit_value: float


@dataclass(frozen=True, slots=True)
class RiskWarning:
    """A non-blocking risk warning (approaching a limit)."""

    check_name: str
    message: str
    severity: str  # always "alert"
    current_value: float
    limit_value: float


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Per-trade capital as % of NAV
TRADE_SIZE_ALERT_PCT = 1.5
TRADE_SIZE_BLOCK_PCT = 2.0

# Single-name concentration as % of NAV
NAME_CONCENTRATION_ALERT_PCT = 4.0
NAME_CONCENTRATION_BLOCK_PCT = 5.0

# Sector concentration as % of NAV
SECTOR_CONCENTRATION_ALERT_PCT = 12.0
SECTOR_CONCENTRATION_BLOCK_PCT = 15.0

# OTC total as % of NAV
OTC_TOTAL_BLOCK_PCT = 15.0

# Distressed total as % of NAV
DISTRESSED_TOTAL_BLOCK_PCT = 20.0


@dataclass
class AccountState:
    """
    Snapshot of account state passed through the risk pipeline.

    Callers must populate these fields before calling risk checks.
    """

    nav: float = 0.0
    cash: float = 0.0
    total_invested: float = 0.0

    # Current position value for the ticker being traded (0 if new position)
    existing_position_value: float = 0.0

    # Sector-level aggregates
    sector_exposure: dict[str, float] = field(default_factory=dict)

    # Category-level aggregates
    total_otc_exposure: float = 0.0
    total_distressed_exposure: float = 0.0

    # Ticker metadata
    symbol: str = ""
    sector: str | None = None
    is_otc: bool = False
    is_distressed: bool = False


@dataclass
class OrderCandidate:
    """
    Minimal order representation for risk checks.

    Populated from the inbound OrderCreate request plus market data.
    """

    ticker_id: int = 0
    symbol: str = ""
    side: str = "buy"  # "buy" | "sell"
    qty: float = 0.0
    price: float = 0.0
    order_type: str = "limit"
    stop_loss: float | None = None
    notional_value: float = 0.0  # qty * price

    # Market data for fat-finger checks
    last_trade_price: float | None = None
    vwap: float | None = None
    avg_daily_volume: float | None = None
    avg_daily_dollar_volume: float | None = None
    bid: float | None = None
    ask: float | None = None

    # Ticker metadata
    sector: str | None = None
    is_otc: bool = False
    is_distressed: bool = False


class PositionLimitChecker:
    """
    Enforces position sizing and concentration limits.

    All checks use the pattern:
        effective_limit = min(configurable_setting, hardcoded_absolute_max)
    to ensure hardcoded limits can never be exceeded.
    """

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        self._db = db_pool

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_position_size(
        self,
        order_value: float,
        nav: float,
    ) -> RiskViolation | RiskWarning | None:
        """
        Check per-trade capital limit: 2% of NAV.

        Alert at 1.5%, block at 2%.  Hardcoded absolute max applies.
        """
        if nav <= 0:
            return RiskViolation(
                check_name="position_size",
                message="Cannot evaluate position size: NAV is zero or negative",
                severity="block",
                current_value=order_value,
                limit_value=0.0,
            )

        pct = (order_value / nav) * 100.0
        block_limit = min(TRADE_SIZE_BLOCK_PCT, HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT)
        alert_limit = TRADE_SIZE_ALERT_PCT

        if pct >= block_limit:
            return RiskViolation(
                check_name="position_size",
                message=(
                    f"Order value ${order_value:,.2f} is {pct:.2f}% of NAV "
                    f"(limit {block_limit:.1f}%)"
                ),
                severity="block",
                current_value=pct,
                limit_value=block_limit,
            )

        if pct >= alert_limit:
            return RiskWarning(
                check_name="position_size",
                message=(
                    f"Order value ${order_value:,.2f} is {pct:.2f}% of NAV "
                    f"(alert threshold {alert_limit:.1f}%)"
                ),
                severity="alert",
                current_value=pct,
                limit_value=alert_limit,
            )

        return None

    def check_name_concentration(
        self,
        symbol: str,
        order_value: float,
        existing_position_value: float,
        nav: float,
    ) -> RiskViolation | RiskWarning | None:
        """
        Check single-name concentration: 5% of NAV.

        Alert at 4%, block at 5%.
        """
        if nav <= 0:
            return RiskViolation(
                check_name="name_concentration",
                message="Cannot evaluate name concentration: NAV is zero or negative",
                severity="block",
                current_value=order_value,
                limit_value=0.0,
            )

        total_exposure = existing_position_value + order_value
        pct = (total_exposure / nav) * 100.0

        # Effective limit is the lesser of configurable and hardcoded
        effective_max = min(
            settings.max_position_pct,
            HardcodedLimits.ABSOLUTE_MAX_POSITION_PCT,
        )
        block_limit = min(NAME_CONCENTRATION_BLOCK_PCT, effective_max)
        alert_limit = NAME_CONCENTRATION_ALERT_PCT

        if pct >= block_limit:
            return RiskViolation(
                check_name="name_concentration",
                message=(
                    f"{symbol} total exposure ${total_exposure:,.2f} would be "
                    f"{pct:.2f}% of NAV (limit {block_limit:.1f}%)"
                ),
                severity="block",
                current_value=pct,
                limit_value=block_limit,
            )

        if pct >= alert_limit:
            return RiskWarning(
                check_name="name_concentration",
                message=(
                    f"{symbol} total exposure ${total_exposure:,.2f} is "
                    f"{pct:.2f}% of NAV (alert threshold {alert_limit:.1f}%)"
                ),
                severity="alert",
                current_value=pct,
                limit_value=alert_limit,
            )

        return None

    def check_sector_concentration(
        self,
        sector: str | None,
        order_value: float,
        sector_exposure: dict[str, float],
        nav: float,
    ) -> RiskViolation | RiskWarning | None:
        """
        Check per-sector concentration: 15% of NAV.

        Alert at 12%, block at 15%.
        """
        if not sector or nav <= 0:
            return None

        current_sector_value = sector_exposure.get(sector, 0.0)
        new_sector_total = current_sector_value + order_value
        pct = (new_sector_total / nav) * 100.0

        if pct >= SECTOR_CONCENTRATION_BLOCK_PCT:
            return RiskViolation(
                check_name="sector_concentration",
                message=(
                    f"Sector '{sector}' exposure would be ${new_sector_total:,.2f} "
                    f"({pct:.2f}% of NAV, limit {SECTOR_CONCENTRATION_BLOCK_PCT:.1f}%)"
                ),
                severity="block",
                current_value=pct,
                limit_value=SECTOR_CONCENTRATION_BLOCK_PCT,
            )

        if pct >= SECTOR_CONCENTRATION_ALERT_PCT:
            return RiskWarning(
                check_name="sector_concentration",
                message=(
                    f"Sector '{sector}' exposure approaching limit at "
                    f"{pct:.2f}% of NAV (alert threshold {SECTOR_CONCENTRATION_ALERT_PCT:.1f}%)"
                ),
                severity="alert",
                current_value=pct,
                limit_value=SECTOR_CONCENTRATION_ALERT_PCT,
            )

        return None

    async def check_otc_exposure(
        self,
        is_otc: bool,
        order_value: float,
        current_otc_total: float,
        nav: float,
    ) -> RiskViolation | None:
        """
        Check total OTC exposure: 15% of NAV.

        OTC securities carry higher counterparty and liquidity risk.
        """
        if not is_otc or nav <= 0:
            return None

        new_total = current_otc_total + order_value
        pct = (new_total / nav) * 100.0

        if pct >= OTC_TOTAL_BLOCK_PCT:
            return RiskViolation(
                check_name="otc_exposure",
                message=(
                    f"Total OTC exposure would be ${new_total:,.2f} "
                    f"({pct:.2f}% of NAV, limit {OTC_TOTAL_BLOCK_PCT:.1f}%)"
                ),
                severity="block",
                current_value=pct,
                limit_value=OTC_TOTAL_BLOCK_PCT,
            )

        return None

    async def check_distressed_exposure(
        self,
        is_distressed: bool,
        order_value: float,
        current_distressed_total: float,
        nav: float,
    ) -> RiskViolation | None:
        """
        Check total distressed exposure: 20% of NAV.

        Distressed securities (Z-score < 1.8 or similar) require separate limits.
        """
        if not is_distressed or nav <= 0:
            return None

        new_total = current_distressed_total + order_value
        pct = (new_total / nav) * 100.0

        if pct >= DISTRESSED_TOTAL_BLOCK_PCT:
            return RiskViolation(
                check_name="distressed_exposure",
                message=(
                    f"Total distressed exposure would be ${new_total:,.2f} "
                    f"({pct:.2f}% of NAV, limit {DISTRESSED_TOTAL_BLOCK_PCT:.1f}%)"
                ),
                severity="block",
                current_value=pct,
                limit_value=DISTRESSED_TOTAL_BLOCK_PCT,
            )

        return None

    def check_portfolio_utilization(
        self,
        order_value: float,
        nav: float,
        current_invested: float,
    ) -> RiskViolation | RiskWarning | None:
        """
        Check portfolio utilization: configurable, default 50%.

        Prevents over-leveraging the portfolio.
        """
        if nav <= 0:
            return RiskViolation(
                check_name="portfolio_utilization",
                message="Cannot evaluate utilization: NAV is zero or negative",
                severity="block",
                current_value=0.0,
                limit_value=0.0,
            )

        new_invested = current_invested + order_value
        pct = (new_invested / nav) * 100.0
        limit = settings.max_portfolio_utilization_pct

        if pct >= limit:
            return RiskViolation(
                check_name="portfolio_utilization",
                message=(
                    f"Portfolio utilization would be {pct:.2f}% "
                    f"(limit {limit:.1f}%)"
                ),
                severity="block",
                current_value=pct,
                limit_value=limit,
            )

        # Warn at 90% of the utilization limit
        warn_threshold = limit * 0.9
        if pct >= warn_threshold:
            return RiskWarning(
                check_name="portfolio_utilization",
                message=(
                    f"Portfolio utilization at {pct:.2f}% "
                    f"(approaching {limit:.1f}% limit)"
                ),
                severity="alert",
                current_value=pct,
                limit_value=limit,
            )

        return None

    # ------------------------------------------------------------------
    # Aggregate runner
    # ------------------------------------------------------------------

    async def run_all(
        self,
        order: OrderCandidate,
        account: AccountState,
    ) -> list[RiskViolation | RiskWarning]:
        """
        Run all position and concentration limit checks.

        Returns a list of all violations and warnings found.  An empty list
        means all checks passed.
        """
        results: list[RiskViolation | RiskWarning] = []

        # Only check limits for buy orders (sells reduce exposure)
        if order.side != "buy":
            return results

        notional = order.notional_value
        nav = account.nav

        # 1. Per-trade capital (2% of NAV)
        check = self.check_position_size(notional, nav)
        if check:
            results.append(check)

        # 2. Single-name concentration (5% of NAV)
        check = self.check_name_concentration(
            order.symbol,
            notional,
            account.existing_position_value,
            nav,
        )
        if check:
            results.append(check)

        # 3. Sector concentration (15% of NAV)
        check = self.check_sector_concentration(
            order.sector or account.sector,
            notional,
            account.sector_exposure,
            nav,
        )
        if check:
            results.append(check)

        # 4. OTC exposure (15% of NAV)
        check = await self.check_otc_exposure(
            order.is_otc or account.is_otc,
            notional,
            account.total_otc_exposure,
            nav,
        )
        if check:
            results.append(check)

        # 5. Distressed exposure (20% of NAV)
        check = await self.check_distressed_exposure(
            order.is_distressed or account.is_distressed,
            notional,
            account.total_distressed_exposure,
            nav,
        )
        if check:
            results.append(check)

        # 6. Portfolio utilization (50% default)
        check = self.check_portfolio_utilization(
            notional,
            nav,
            account.total_invested,
        )
        if check:
            results.append(check)

        violation_count = sum(1 for r in results if isinstance(r, RiskViolation))
        warning_count = sum(1 for r in results if isinstance(r, RiskWarning))
        if results:
            logger.info(
                "Position limit checks for %s: %d violations, %d warnings",
                order.symbol,
                violation_count,
                warning_count,
            )

        return results
