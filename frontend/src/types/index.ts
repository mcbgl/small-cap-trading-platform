// ── Enums (aligned with backend lowercase values) ──

export enum SignalType {
  VOLUME = "volume",
  SQUEEZE = "squeeze",
  INSIDER = "insider",
  TECHNICAL = "technical",
  DISTRESSED = "distressed",
  AI_COMPOSITE = "ai_composite",
}

export enum OrderStatus {
  CREATED = "created",
  RISK_CHECKED = "risk_checked",
  SUBMITTED = "submitted",
  FILLED = "filled",
  REJECTED = "rejected",
  CANCELLED = "cancelled",
}

export enum OrderSide {
  BUY = "buy",
  SELL = "sell",
}

export enum AlertPriority {
  CRITICAL = "critical",
  WARNING = "warning",
  INFO = "info",
}

// ── Core Types ──

export interface Ticker {
  id: number;
  symbol: string;
  name: string;
  sector?: string;
  market_cap?: number;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  avg_volume?: number;
}

export interface Signal {
  id: number;
  ticker_id: number;
  symbol: string;
  signal_type: SignalType;
  title: string;
  description: string;
  score: number;
  confidence: number;
  timestamp: string;
  priority: AlertPriority;
  metadata?: Record<string, unknown>;
}

export interface Order {
  id: number;
  ticker_id: number;
  symbol: string;
  side: OrderSide;
  qty: number;
  price: number;
  order_type: string;
  status: OrderStatus;
  filled_qty: number;
  filled_price?: number;
  stop_loss?: number;
  created_at: string;
  updated_at: string;
}

export interface OrderCreate {
  ticker_id: number;
  side: OrderSide;
  qty: number;
  price: number;
  order_type: string;
  stop_loss?: number;
}

export interface Position {
  id: number;
  ticker_id: number;
  symbol: string;
  name: string;
  qty: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  day_change: number;
  day_change_pct: number;
}

export interface WatchlistItem {
  id: number;
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  signal_count: number;
  added_at: string;
}

export interface Watchlist {
  id: number;
  name: string;
  items: WatchlistItem[];
  created_at: string;
  updated_at: string;
}

export interface InsightCard {
  id: string;
  symbol: string;
  title: string;
  summary: string;
  score: number;
  confidence: number;
  pros: string[];
  cons: string[];
  model: string;
  timestamp: string;
  signal_type: SignalType;
}

export interface AlertItem {
  id: string;
  priority: AlertPriority;
  title: string;
  message: string;
  symbol?: string;
  timestamp: string;
  read: boolean;
  action_url?: string;
}

export interface SystemStatus {
  service: string;
  status: "connected" | "disconnected" | "degraded";
  latency?: number;
  last_check: string;
  details?: string;
}

// ── Portfolio Types ──

export interface PortfolioSummary {
  total_value: number;
  cash: number;
  invested: number;
  unrealized_pnl: number;
  realized_pnl: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  position_count: number;
  open_order_count: number;
  portfolio_utilization_pct: number;
}

export interface PerformanceMetrics {
  total_return_pct: number;
  daily_return_pct: number;
  weekly_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
}

export interface PortfolioHistoryPoint {
  date: string;
  total_value: number;
  cash: number;
  invested: number;
  daily_pnl: number;
}

// ── Screener Types ──

export interface ScreenerResult {
  symbol: string;
  name: string;
  score: number;
  market_cap: number;
  sector: string;
  signal_count: number;
  signals: Signal[];
  latest_signal_type: SignalType;
  metadata?: Record<string, unknown>;
}

export interface ScreenerResponse {
  preset_name: string;
  results: ScreenerResult[];
  total: number;
  limit: number;
  offset: number;
  executed_at: string;
}

export interface ScreenerPreset {
  name: string;
  description: string;
  filters: Record<string, unknown>;
}

// ── Filing Types ──

export interface Filing {
  id: number;
  ticker_id: number;
  symbol: string;
  form_type: string;
  filed_date: string;
  title: string;
  url: string;
  keywords_found: string[];
  ai_summary?: string;
  ai_score?: number;
  keyword_count: number;
}

// ── Risk Types ──

export interface RiskStatus {
  kill_switches: KillSwitch[];
  circuit_breakers: CircuitBreaker[];
  rate_limits: RateLimit[];
  compliance: ComplianceCheck[];
  limits: RiskLimits;
}

export interface KillSwitch {
  level: string;
  active: boolean;
  activated_at?: string;
  reason?: string;
}

export interface CircuitBreaker {
  level: string;
  threshold_pct: number;
  current_drawdown_pct: number;
  triggered: boolean;
  action: string;
}

export interface RateLimit {
  name: string;
  limit: number;
  current: number;
  window_seconds: number;
}

export interface ComplianceCheck {
  name: string;
  status: "pass" | "fail" | "warning";
  message: string;
}

export interface RiskLimits {
  max_position_pct: number;
  max_portfolio_risk_pct: number;
  max_daily_loss_pct: number;
  max_order_value: number;
}

// ── System Types ──

export interface SystemHealth {
  status: "healthy" | "degraded" | "down";
  components: ComponentHealth[];
}

export interface ComponentHealth {
  name: string;
  status: "healthy" | "degraded" | "down" | "unavailable";
  latency_ms?: number;
  message?: string;
}

export interface AuditLogEntry {
  id: number;
  action: string;
  actor: string;
  target?: string;
  details?: Record<string, unknown>;
  timestamp: string;
}

export interface SystemConfig {
  paper_mode: boolean;
  max_positions: number;
  max_order_value: number;
  risk_enabled: boolean;
  [key: string]: unknown;
}

// ── Filter Types ──

export interface SignalFilters {
  ticker?: string;
  signal_type?: SignalType;
  min_score?: number;
  limit?: number;
}

export interface OrderFilters {
  status?: OrderStatus;
  ticker?: string;
  limit?: number;
}

export interface FilingFilters {
  ticker?: string;
  form_type?: string;
  limit?: number;
}

export interface AuditLogFilters {
  action?: string;
  actor?: string;
  limit?: number;
  offset?: number;
}
