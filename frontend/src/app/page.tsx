"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  DollarSign,
  TrendingUp,
  Banknote,
  BarChart3,
  Activity,
  AlertTriangle,
  AlertOctagon,
  Info,
  X,
  Zap,
} from "lucide-react";
import StatCard from "@/components/common/StatCard";
import Badge from "@/components/common/Badge";
import { apiGet } from "@/lib/api";
import { tradingWS } from "@/lib/ws";
import { usePortfolioStore } from "@/lib/stores/portfolio";
import { useAlertsStore } from "@/lib/stores/alerts";
import type {
  PortfolioSummary,
  Signal,
} from "@/types";
import { AlertPriority } from "@/types";

// ── Formatting helpers ──

const currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const currencyFmtPrecise = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const pctFmt = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "always",
});

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

// ── Signal type styling ──

const signalTypeMeta: Record<
  string,
  { label: string; color: string; variant: "info" | "warning" | "success" | "danger" | "neutral" }
> = {
  volume: { label: "Volume", color: "var(--accent-blue)", variant: "info" },
  squeeze: { label: "Squeeze", color: "var(--accent-purple)", variant: "neutral" },
  insider: { label: "Insider", color: "var(--accent-green)", variant: "success" },
  technical: { label: "Technical", color: "var(--accent-amber)", variant: "warning" },
  distressed: { label: "Distressed", color: "var(--accent-red)", variant: "danger" },
  ai_composite: { label: "AI", color: "var(--accent-purple)", variant: "neutral" },
};

// ── Alert priority styling ──

const alertPriorityStyle: Record<
  string,
  { icon: React.ReactNode; borderColor: string; color: string }
> = {
  critical: {
    icon: <AlertOctagon size={14} />,
    borderColor: "var(--accent-red)",
    color: "var(--accent-red)",
  },
  warning: {
    icon: <AlertTriangle size={14} />,
    borderColor: "var(--accent-amber)",
    color: "var(--accent-amber)",
  },
  info: {
    icon: <Info size={14} />,
    borderColor: "var(--accent-blue)",
    color: "var(--accent-blue)",
  },
};

// ── Market index type ──

interface MarketIndex {
  symbol: string;
  label: string;
  price: number | null;
  change_pct: number | null;
}

export default function HomePage() {
  // ── Portfolio summary from API ──
  const { data: summary } = useQuery<PortfolioSummary>({
    queryKey: ["portfolio", "summary"],
    queryFn: () => apiGet<PortfolioSummary>("/api/portfolio/summary"),
    refetchInterval: 30_000,
  });

  // ── Fallback to Zustand store for real-time updates ──
  const store = usePortfolioStore();
  const totalValue = summary?.total_value ?? store.totalValue;
  const dailyPnl = summary?.daily_pnl ?? store.dailyPnl;
  const dailyPnlPct = summary?.daily_pnl_pct ?? store.dailyPnlPercent;
  const cash = summary?.cash ?? store.cash;
  const positionCount = summary?.position_count ?? store.positions.length;

  // ── AI Insights / Signals ──
  const { data: signals } = useQuery<Signal[]>({
    queryKey: ["signals", "home"],
    queryFn: () => apiGet<Signal[]>("/api/signals?limit=10&min_score=6"),
    refetchInterval: 60_000,
  });

  // Real-time signal prepend via WS
  const [realtimeSignals] = useRealtimeSignals();

  // ── Alerts from Zustand ──
  const alerts = useAlertsStore((s) => s.alerts);
  const removeAlert = useAlertsStore((s) => s.removeAlert);

  const criticalAlerts = alerts.filter((a) => a.priority === AlertPriority.CRITICAL);
  const warningAlerts = alerts.filter((a) => a.priority === AlertPriority.WARNING);
  const infoAlerts = alerts.filter((a) => a.priority === AlertPriority.INFO);

  // ── Market context ──
  const { data: marketData } = useQuery<MarketIndex[]>({
    queryKey: ["market", "context"],
    queryFn: async () => {
      // Try fetching each index; if API doesn't support, return empty
      try {
        const indices: MarketIndex[] = [];
        const spyData = await apiGet<{ price?: number; change_pct?: number }>(
          "/api/tickers?search=SPY"
        ).catch(() => null);
        indices.push({
          symbol: "SPY",
          label: "S&P 500",
          price: (spyData as Record<string, unknown>)?.price as number | null ?? null,
          change_pct: (spyData as Record<string, unknown>)?.change_pct as number | null ?? null,
        });

        const iwmData = await apiGet<{ price?: number; change_pct?: number }>(
          "/api/tickers?search=IWM"
        ).catch(() => null);
        indices.push({
          symbol: "IWM",
          label: "Russell 2000",
          price: (iwmData as Record<string, unknown>)?.price as number | null ?? null,
          change_pct: (iwmData as Record<string, unknown>)?.change_pct as number | null ?? null,
        });

        const vixData = await apiGet<{ price?: number; change_pct?: number }>(
          "/api/tickers?search=VIX"
        ).catch(() => null);
        indices.push({
          symbol: "VIX",
          label: "VIX",
          price: (vixData as Record<string, unknown>)?.price as number | null ?? null,
          change_pct: (vixData as Record<string, unknown>)?.change_pct as number | null ?? null,
        });

        return indices;
      } catch {
        return [];
      }
    },
    refetchInterval: 60_000,
  });

  // ── WS price subscription ──
  useEffect(() => {
    const handler = (data: unknown) => {
      const priceUpdate = data as { symbol: string; price: number };
      if (priceUpdate?.symbol && priceUpdate?.price) {
        store.updatePrice(priceUpdate.symbol, priceUpdate.price);
      }
    };
    tradingWS.subscribe("prices", handler);
    return () => tradingWS.unsubscribe("prices", handler);
  }, [store]);

  // Merge API signals with real-time signals (deduped)
  const allSignals = mergeSignals(signals ?? [], realtimeSignals);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1
          className="text-2xl font-bold"
          style={{ color: "var(--text-primary)" }}
        >
          Command Center
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Real-time overview of your trading activity
        </p>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Value"
          value={currencyFmt.format(totalValue)}
          icon={<DollarSign size={16} />}
        />
        <StatCard
          title="Daily P&L"
          value={currencyFmtPrecise.format(dailyPnl)}
          change={pctFmt.format(dailyPnlPct / 100)}
          changePositive={dailyPnl >= 0}
          icon={<TrendingUp size={16} />}
        />
        <StatCard
          title="Cash Available"
          value={currencyFmt.format(cash)}
          icon={<Banknote size={16} />}
        />
        <StatCard
          title="Open Positions"
          value={String(positionCount)}
          icon={<BarChart3 size={16} />}
        />
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* AI Insights Feed */}
        <div
          className="rounded-lg border p-5"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Activity size={16} style={{ color: "var(--accent-purple)" }} />
            <h2
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-primary)" }}
            >
              AI Insights Feed
            </h2>
            {allSignals.length > 0 && (
              <span
                className="ml-auto flex items-center justify-center h-5 min-w-5 rounded-full text-xs font-bold px-1.5"
                style={{
                  backgroundColor: "rgba(139, 92, 246, 0.2)",
                  color: "var(--accent-purple)",
                }}
              >
                {allSignals.length}
              </span>
            )}
          </div>

          {allSignals.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Activity
                size={40}
                style={{ color: "var(--text-muted)", opacity: 0.5 }}
              />
              <p
                className="text-sm mt-3"
                style={{ color: "var(--text-muted)" }}
              >
                No signals yet. Connect data feeds to begin monitoring.
              </p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[400px] overflow-y-auto pr-1">
              {allSignals.map((signal) => {
                const meta =
                  signalTypeMeta[signal.signal_type] ??
                  signalTypeMeta.technical;
                return (
                  <div
                    key={signal.id}
                    className="flex items-start gap-3 rounded-md p-3 transition-colors"
                    style={{ backgroundColor: "var(--bg-hover)" }}
                  >
                    <Zap size={14} style={{ color: meta.color, marginTop: 2 }} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span
                          className="text-sm font-semibold"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {signal.symbol}
                        </span>
                        <Badge variant={meta.variant}>{meta.label}</Badge>
                        <Badge
                          variant={
                            signal.score >= 8
                              ? "success"
                              : signal.score >= 6
                                ? "warning"
                                : "neutral"
                          }
                        >
                          {signal.score}/10
                        </Badge>
                        <span
                          className="ml-auto text-xs whitespace-nowrap"
                          style={{ color: "var(--text-muted)" }}
                        >
                          {timeAgo(signal.timestamp)}
                        </span>
                      </div>
                      <p
                        className="text-xs truncate"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {signal.title}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Active Alerts */}
        <div
          className="rounded-lg border p-5"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={16} style={{ color: "var(--accent-amber)" }} />
            <h2
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-primary)" }}
            >
              Active Alerts
            </h2>
            {alerts.length > 0 && (
              <span
                className="ml-auto flex items-center justify-center h-5 min-w-5 rounded-full text-xs font-bold px-1.5"
                style={{
                  backgroundColor: "rgba(245, 158, 11, 0.2)",
                  color: "var(--accent-amber)",
                }}
              >
                {alerts.length}
              </span>
            )}
          </div>

          {alerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <AlertTriangle
                size={40}
                style={{ color: "var(--text-muted)", opacity: 0.5 }}
              />
              <p
                className="text-sm mt-3"
                style={{ color: "var(--text-muted)" }}
              >
                No active alerts
              </p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {[...criticalAlerts, ...warningAlerts, ...infoAlerts].map(
                (alert) => {
                  const style =
                    alertPriorityStyle[alert.priority] ??
                    alertPriorityStyle.info;
                  return (
                    <div
                      key={alert.id}
                      className="flex items-start gap-3 rounded-md p-3"
                      style={{
                        backgroundColor: "var(--bg-hover)",
                        borderLeft: `3px solid ${style.borderColor}`,
                      }}
                    >
                      <span style={{ color: style.color, marginTop: 2 }}>
                        {style.icon}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span
                            className="text-sm font-medium"
                            style={{ color: "var(--text-primary)" }}
                          >
                            {alert.title}
                          </span>
                          {alert.symbol && (
                            <Badge variant="info">{alert.symbol}</Badge>
                          )}
                          <span
                            className="ml-auto text-xs whitespace-nowrap"
                            style={{ color: "var(--text-muted)" }}
                          >
                            {timeAgo(alert.timestamp)}
                          </span>
                        </div>
                        <p
                          className="text-xs"
                          style={{ color: "var(--text-secondary)" }}
                        >
                          {alert.message}
                        </p>
                      </div>
                      <button
                        onClick={() => removeAlert(alert.id)}
                        className="shrink-0 p-1 rounded hover:opacity-80"
                        style={{ color: "var(--text-muted)" }}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  );
                }
              )}
            </div>
          )}
        </div>
      </div>

      {/* Market Context Strip */}
      <div
        className="rounded-lg border p-4"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <h2
          className="text-xs font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          Market Context
        </h2>
        <div className="grid grid-cols-3 gap-4">
          {(
            marketData ?? [
              { symbol: "SPY", label: "S&P 500", price: null, change_pct: null },
              { symbol: "IWM", label: "Russell 2000", price: null, change_pct: null },
              { symbol: "VIX", label: "VIX", price: null, change_pct: null },
            ]
          ).map((idx) => (
            <div key={idx.symbol} className="flex items-center justify-between">
              <span
                className="text-sm"
                style={{ color: "var(--text-secondary)" }}
              >
                {idx.label}
              </span>
              <div className="text-right">
                <span
                  className="text-sm font-medium"
                  style={{ color: "var(--text-primary)" }}
                >
                  {idx.price != null
                    ? currencyFmtPrecise.format(idx.price)
                    : "---"}
                </span>
                <span
                  className="text-xs ml-2"
                  style={{
                    color:
                      idx.change_pct == null
                        ? "var(--text-muted)"
                        : idx.change_pct >= 0
                          ? "var(--accent-green)"
                          : "var(--accent-red)",
                  }}
                >
                  {idx.change_pct != null
                    ? `${idx.change_pct >= 0 ? "+" : ""}${idx.change_pct.toFixed(2)}%`
                    : "---%"}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Hooks ──

/**
 * Custom hook to accumulate real-time signals from WebSocket
 */
function useRealtimeSignals(): [Signal[], (s: Signal) => void] {
  const signalsRef = useRef<Signal[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);

  const addSignal = useCallback((signal: Signal) => {
    signalsRef.current = [signal, ...signalsRef.current].slice(0, 20);
    setSignals([...signalsRef.current]);
  }, []);

  useEffect(() => {
    const handler = (data: unknown) => {
      const signal = data as Signal;
      if (signal?.id && signal?.score >= 6) {
        addSignal(signal);
      }
    };
    tradingWS.subscribe("signals", handler);
    return () => tradingWS.unsubscribe("signals", handler);
  }, [addSignal]);

  return [signals, addSignal];
}

/**
 * Merge API signals with real-time WS signals, deduplicating by id
 */
function mergeSignals(apiSignals: Signal[], rtSignals: Signal[]): Signal[] {
  const seen = new Set<number>();
  const merged: Signal[] = [];

  for (const s of rtSignals) {
    if (!seen.has(s.id)) {
      seen.add(s.id);
      merged.push(s);
    }
  }
  for (const s of apiSignals) {
    if (!seen.has(s.id)) {
      seen.add(s.id);
      merged.push(s);
    }
  }

  return merged.slice(0, 15);
}
