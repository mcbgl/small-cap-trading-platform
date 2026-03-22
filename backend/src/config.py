"""
Configuration module with three-tier guardrails model.

Tier 1 (HardcodedLimits): Absolute safety limits. Never overridable at runtime.
Tier 2 (Settings fields with bounds): Configurable within safe bounds via env/config.
Tier 3 (Settings fields without bounds): Freely configurable operational settings.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class HardcodedLimits:
    """Tier 1: Absolute safety limits — never overridable at runtime."""

    ABSOLUTE_MAX_POSITION_PCT = 10.0
    ABSOLUTE_MAX_DRAWDOWN_PCT = 20.0
    ABSOLUTE_MAX_ORDER_VALUE = 500_000
    KILL_SWITCH_ALWAYS_AVAILABLE = True
    AUDIT_LOGGING_ALWAYS_ON = True
    STOP_LOSS_REQUIRED = True
    WASH_SALE_CHECK_ALWAYS_ON = True


class Settings(BaseSettings):
    """Tier 2 & 3: Configurable settings loaded from environment / .env file."""

    # --- Database ---
    database_url: str = "postgresql://trader:trader@localhost:5432/trading"
    questdb_url: str = "http://localhost:9000"
    questdb_ilp_host: str = "localhost"
    questdb_ilp_port: int = 9009
    redis_url: str = "redis://localhost:6379"

    # --- API Keys ---
    polygon_api_key: str = ""
    anthropic_api_key: str = ""
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    ollama_url: str = "http://localhost:11434"
    edgar_user_agent: str = ""

    # --- Tier 2: Configurable with safety bounds ---
    max_position_pct: float = Field(default=5.0, ge=1.0, le=10.0)
    daily_drawdown_pct: float = Field(default=3.0, ge=1.0, le=5.0)
    weekly_drawdown_pct: float = Field(default=5.0, ge=2.0, le=8.0)
    fixed_stop_loss_pct: float = Field(default=8.0, ge=3.0, le=15.0)
    ai_confidence_min: float = Field(default=0.70, ge=0.50, le=0.95)
    orders_per_day: int = Field(default=200, ge=10, le=500)

    # --- Conservative defaults ---
    max_portfolio_utilization_pct: float = 50.0
    max_daily_orders: int = 50
    human_approval_above_usd: float = 5000.0
    shadow_mode: bool = True
    paper_mode: bool = True
    limit_orders_only: bool = True
    no_extended_hours: bool = True

    # --- Tier 3: Free config ---
    log_level: str = "INFO"
    secret_key: str = "change-me"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
