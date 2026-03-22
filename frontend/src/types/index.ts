// ── Enums ──

export enum SignalType {
  INSIDER_BUY = "INSIDER_BUY",
  INSIDER_SELL = "INSIDER_SELL",
  SEC_FILING = "SEC_FILING",
  PRICE_SPIKE = "PRICE_SPIKE",
  VOLUME_SURGE = "VOLUME_SURGE",
  SHORT_SQUEEZE = "SHORT_SQUEEZE",
  AI_PATTERN = "AI_PATTERN",
  DISTRESSED = "DISTRESSED",
}

export enum OrderStatus {
  PENDING = "PENDING",
  SUBMITTED = "SUBMITTED",
  FILLED = "FILLED",
  PARTIALLY_FILLED = "PARTIALLY_FILLED",
  CANCELLED = "CANCELLED",
  REJECTED = "REJECTED",
}

export enum OrderSide {
  BUY = "BUY",
  SELL = "SELL",
}

export enum AlertPriority {
  CRITICAL = "CRITICAL",
  WARNING = "WARNING",
  INFO = "INFO",
}

// ── Core Types ──

export interface Ticker {
  symbol: string;
  name: string;
  sector?: string;
  marketCap?: number;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  avgVolume?: number;
}

export interface Signal {
  id: string;
  type: SignalType;
  symbol: string;
  title: string;
  description: string;
  confidence: number;
  timestamp: string;
  priority: AlertPriority;
  metadata?: Record<string, unknown>;
}

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  price?: number;
  status: OrderStatus;
  filledQuantity: number;
  filledPrice?: number;
  createdAt: string;
  updatedAt: string;
}

export interface Position {
  symbol: string;
  name: string;
  quantity: number;
  avgCost: number;
  currentPrice: number;
  marketValue: number;
  unrealizedPnl: number;
  unrealizedPnlPercent: number;
  dayChange: number;
  dayChangePercent: number;
}

export interface WatchlistItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  signals: number;
  addedAt: string;
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
  signalType: SignalType;
}

export interface AlertItem {
  id: string;
  priority: AlertPriority;
  title: string;
  message: string;
  symbol?: string;
  timestamp: string;
  read: boolean;
  actionUrl?: string;
}

export interface SystemStatus {
  service: string;
  status: "connected" | "disconnected" | "degraded";
  latency?: number;
  lastCheck: string;
  details?: string;
}
