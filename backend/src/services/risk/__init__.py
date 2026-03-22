"""
Risk engine package — pre-trade risk checks, compliance, circuit breakers.

Public API:
    RiskEngine          — main orchestrator (pre_trade_check, kill_switch, status)
    PositionLimitChecker — position sizing and concentration limits
    ComplianceEngine     — regulatory compliance (wash sale, PDT, manipulation)
    CircuitBreakerMonitor — drawdown circuit breakers

Data classes:
    RiskCheckResult, RiskViolation, RiskWarning
    ComplianceViolation, ComplianceWarning
    Breaker, CircuitBreakerStatus
    OrderCandidate, AccountState
"""

from src.services.risk.circuit_breakers import (
    Breaker,
    CircuitBreakerMonitor,
    CircuitBreakerStatus,
)
from src.services.risk.compliance import (
    ComplianceEngine,
    ComplianceViolation,
    ComplianceWarning,
)
from src.services.risk.engine import RiskCheckResult, RiskEngine
from src.services.risk.position_limits import (
    AccountState,
    OrderCandidate,
    PositionLimitChecker,
    RiskViolation,
    RiskWarning,
)

__all__ = [
    # Engine
    "RiskEngine",
    "RiskCheckResult",
    # Position limits
    "PositionLimitChecker",
    "AccountState",
    "OrderCandidate",
    "RiskViolation",
    "RiskWarning",
    # Compliance
    "ComplianceEngine",
    "ComplianceViolation",
    "ComplianceWarning",
    # Circuit breakers
    "CircuitBreakerMonitor",
    "Breaker",
    "CircuitBreakerStatus",
]
