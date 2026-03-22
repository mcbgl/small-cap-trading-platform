"""
Pydantic models for API request/response schemas.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SignalType(StrEnum):
    VOLUME = "volume"
    SQUEEZE = "squeeze"
    INSIDER = "insider"
    TECHNICAL = "technical"
    DISTRESSED = "distressed"
    AI_COMPOSITE = "ai_composite"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"
    MARKET = "market"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(StrEnum):
    CREATED = "created"
    RISK_CHECKED = "risk_checked"
    SUBMITTED = "submitted"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Tickers
# ---------------------------------------------------------------------------

class TickerBase(BaseModel):
    symbol: str
    name: str
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    avg_volume: int | None = None
    exchange: str | None = None
    is_otc: bool = False
    is_active: bool = True


class TickerResponse(TickerBase):
    id: int
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class SignalBase(BaseModel):
    ticker_id: int
    signal_type: SignalType
    score: float = Field(ge=0.0, le=10.0)
    confidence: float = Field(ge=0.0, le=1.0)
    model: str | None = None
    reasoning: str | None = None


class SignalResponse(SignalBase):
    id: int
    symbol: str | None = None
    raw_output: dict | None = None
    metadata: dict | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class OrderCreate(BaseModel):
    ticker_id: int
    side: OrderSide
    qty: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    order_type: OrderType = OrderType.LIMIT
    stop_loss: float | None = Field(default=None, gt=0)


class OrderResponse(BaseModel):
    id: int
    ticker_id: int
    symbol: str | None = None
    side: OrderSide
    qty: float
    price: float | None = None
    order_type: OrderType
    status: OrderStatus
    stop_loss: float | None = None
    broker: str | None = None
    broker_order_id: str | None = None
    paper_mode: bool = True
    filled_qty: float = 0
    filled_avg_price: float | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

class PositionResponse(BaseModel):
    id: int
    ticker_id: int
    symbol: str | None = None
    side: str = "long"
    qty: float
    avg_entry_price: float
    current_price: float | None = None
    unrealized_pnl: float | None = None
    stop_loss: float
    trailing_stop_pct: float | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------

class WatchlistCreate(BaseModel):
    name: str
    description: str | None = None


class WatchlistResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    ticker_count: int = 0
    created_at: datetime


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class AuditLogEntry(BaseModel):
    id: int
    action: str
    model_id: str | None = None
    prompt_hash: str | None = None
    input_snapshot: dict | None = None
    output: dict | None = None
    decision: str | None = None
    human_override: bool = False
    order_id: int | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# AI Insight Card
# ---------------------------------------------------------------------------

class InsightCard(BaseModel):
    title: str
    ticker: str
    score: float = Field(ge=0.0, le=10.0)
    pros: list[str] = []
    cons: list[str] = []
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
