"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Wallet,
  ArrowUpDown,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Target,
  Activity,
  ShieldAlert,
} from "lucide-react";
import StatCard from "@/components/common/StatCard";
import Badge from "@/components/common/Badge";
import { apiGet } from "@/lib/api";
import { tradingWS } from "@/lib/ws";
import { usePortfolioStore } from "@/lib/stores/portfolio";
import type {
  Position,
  PortfolioSummary,
  PerformanceMetrics,
} from "@/types";

// ── Formatting helpers ──

const currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const currencyFmtShort = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function fmtPct(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function fmtPnl(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${currencyFmt.format(value)}`;
}

export default function PortfolioPage() {
  // ── Fetch portfolio summary ──
  const { data: summary } = useQuery<PortfolioSummary>({
    queryKey: ["portfolio", "summary"],
    queryFn: () => apiGet<PortfolioSummary>("/api/portfolio/summary"),
    refetchInterval: 30_000,
  });

  // ── Fetch positions ──
  const { data: positions, isLoading: positionsLoading } = useQuery<Position[]>({
    queryKey: ["portfolio", "positions"],
    queryFn: () => apiGet<Position[]>("/api/portfolio/positions"),
    refetchInterval: 30_000,
  });

  // ── Fetch performance metrics ──
  const { data: performance } = useQuery<PerformanceMetrics>({
    queryKey: ["portfolio", "performance"],
    queryFn: () => apiGet<PerformanceMetrics>("/api/portfolio/performance"),
    refetchInterval: 60_000,
  });

  // ── Sync positions to Zustand store ──
  const store = usePortfolioStore();
  useEffect(() => {
    if (positions) {
      store.setPositions(positions);
    }
  }, [positions]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── WS price updates ──
  useEffect(() => {
    const handler = (data: unknown) => {
      const update = data as { symbol: string; price: number };
      if (update?.symbol && update?.price) {
        store.updatePrice(update.symbol, update.price);
      }
    };
    tradingWS.subscribe("prices", handler);
    return () => tradingWS.unsubscribe("prices", handler);
  }, [store]);

  // Use store positions for real-time display, fall back to API data
  const displayPositions = store.positions.length > 0 ? store.positions : (positions ?? []);

  const marketValue = summary?.total_value ?? store.totalValue;
  const unrealizedPnl = summary?.unrealized_pnl ?? displayPositions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const dailyPnl = summary?.daily_pnl ?? store.dailyPnl;
  const dailyPnlPct = summary?.daily_pnl_pct ?? store.dailyPnlPercent;

  // Compute total portfolio weight
  const totalInvested = displayPositions.reduce((s, p) => s + p.market_value, 0);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1
            className="text-2xl font-bold flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <Wallet size={24} style={{ color: "var(--accent-blue)" }} />
            Portfolio
          </h1>
          <p
            className="text-sm mt-1"
            style={{ color: "var(--text-secondary)" }}
          >
            Track your holdings and performance
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium border transition-colors"
            style={{
              backgroundColor: "var(--bg-hover)",
              borderColor: "var(--border)",
              color: "var(--text-primary)",
            }}
          >
            <ArrowUpDown size={14} />
            Trade
          </button>
        </div>
      </div>

      {/* Summary Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          title="Market Value"
          value={currencyFmtShort.format(marketValue)}
          icon={<Wallet size={16} />}
        />
        <StatCard
          title="Unrealized P&L"
          value={fmtPnl(unrealizedPnl)}
          changePositive={unrealizedPnl >= 0}
          change={
            totalInvested > 0
              ? fmtPct((unrealizedPnl / totalInvested) * 100)
              : undefined
          }
          icon={
            unrealizedPnl >= 0 ? (
              <TrendingUp size={16} />
            ) : (
              <TrendingDown size={16} />
            )
          }
        />
        <StatCard
          title="Daily Change"
          value={fmtPnl(dailyPnl)}
          change={fmtPct(dailyPnlPct)}
          changePositive={dailyPnl >= 0}
          icon={<Activity size={16} />}
        />
      </div>

      {/* Holdings Table */}
      <div
        className="rounded-lg border overflow-hidden"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <div
          className="p-4 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <h2
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-primary)" }}
          >
            Holdings
          </h2>
        </div>

        {positionsLoading ? (
          <div className="flex items-center justify-center py-16">
            <div
              className="h-6 w-6 rounded-full border-2 border-t-transparent animate-spin"
              style={{ borderColor: "var(--accent-blue)", borderTopColor: "transparent" }}
            />
            <span
              className="ml-3 text-sm"
              style={{ color: "var(--text-muted)" }}
            >
              Loading positions...
            </span>
          </div>
        ) : displayPositions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Wallet
              size={48}
              style={{ color: "var(--text-muted)", opacity: 0.4 }}
            />
            <p
              className="text-sm mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              No positions yet. Start paper trading to build your portfolio.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr
                  className="text-xs font-medium uppercase tracking-wider"
                  style={{
                    color: "var(--text-muted)",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <th className="text-left px-4 py-2.5">Symbol</th>
                  <th className="text-left px-4 py-2.5">Name</th>
                  <th className="text-right px-4 py-2.5">Qty</th>
                  <th className="text-right px-4 py-2.5">Avg Cost</th>
                  <th className="text-right px-4 py-2.5">Price</th>
                  <th className="text-right px-4 py-2.5">Mkt Value</th>
                  <th className="text-right px-4 py-2.5">P&L ($)</th>
                  <th className="text-right px-4 py-2.5">P&L (%)</th>
                  <th className="text-right px-4 py-2.5">Weight</th>
                </tr>
              </thead>
              <tbody>
                {displayPositions.map((pos) => {
                  const weight =
                    marketValue > 0
                      ? (pos.market_value / marketValue) * 100
                      : 0;
                  return (
                    <tr
                      key={pos.id}
                      className="transition-colors cursor-pointer"
                      style={{
                        borderBottom: "1px solid var(--border)",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor =
                          "var(--bg-hover)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = "transparent";
                      }}
                    >
                      <td className="px-4 py-3">
                        <span
                          className="text-sm font-semibold"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {pos.symbol}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className="text-sm"
                          style={{ color: "var(--text-secondary)" }}
                        >
                          {pos.name}
                        </span>
                      </td>
                      <td
                        className="px-4 py-3 text-right text-sm"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {pos.qty.toLocaleString()}
                      </td>
                      <td
                        className="px-4 py-3 text-right text-sm"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {currencyFmt.format(pos.avg_cost)}
                      </td>
                      <td
                        className="px-4 py-3 text-right text-sm font-medium"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {currencyFmt.format(pos.current_price)}
                      </td>
                      <td
                        className="px-4 py-3 text-right text-sm"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {currencyFmt.format(pos.market_value)}
                      </td>
                      <td
                        className="px-4 py-3 text-right text-sm font-medium"
                        style={{
                          color:
                            pos.unrealized_pnl >= 0
                              ? "var(--accent-green)"
                              : "var(--accent-red)",
                        }}
                      >
                        {fmtPnl(pos.unrealized_pnl)}
                      </td>
                      <td
                        className="px-4 py-3 text-right text-sm font-medium"
                        style={{
                          color:
                            pos.unrealized_pnl_pct >= 0
                              ? "var(--accent-green)"
                              : "var(--accent-red)",
                        }}
                      >
                        {fmtPct(pos.unrealized_pnl_pct)}
                      </td>
                      <td
                        className="px-4 py-3 text-right text-sm"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {weight.toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Performance Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Performance Metrics */}
        <div
          className="rounded-lg border p-5"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 size={16} style={{ color: "var(--accent-blue)" }} />
            <h2
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-primary)" }}
            >
              Performance Metrics
            </h2>
          </div>

          {performance ? (
            <div className="grid grid-cols-2 gap-4">
              <MetricRow
                label="Daily Return"
                value={fmtPct(performance.daily_return_pct)}
                positive={performance.daily_return_pct >= 0}
              />
              <MetricRow
                label="Weekly Return"
                value={fmtPct(performance.weekly_return_pct)}
                positive={performance.weekly_return_pct >= 0}
              />
              <MetricRow
                label="Total Return"
                value={fmtPct(performance.total_return_pct)}
                positive={performance.total_return_pct >= 0}
              />
              <MetricRow
                label="Win Rate"
                value={`${performance.win_rate_pct.toFixed(1)}%`}
                positive={performance.win_rate_pct >= 50}
              />
              <MetricRow
                label="Sharpe Ratio"
                value={performance.sharpe_ratio.toFixed(2)}
                positive={performance.sharpe_ratio >= 1}
                icon={<Target size={12} />}
              />
              <MetricRow
                label="Max Drawdown"
                value={`${performance.max_drawdown_pct.toFixed(2)}%`}
                positive={false}
                icon={<ShieldAlert size={12} />}
              />
            </div>
          ) : (
            <div className="flex items-center justify-center py-8">
              <p
                className="text-sm"
                style={{ color: "var(--text-muted)" }}
              >
                Performance data loading...
              </p>
            </div>
          )}
        </div>

        {/* Equity Curve Placeholder */}
        <div
          className="rounded-lg border p-5"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp size={16} style={{ color: "var(--accent-green)" }} />
            <h2
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-primary)" }}
            >
              Equity Curve
            </h2>
          </div>
          <div
            className="flex flex-col items-center justify-center py-12 rounded-md"
            style={{ backgroundColor: "var(--bg-hover)" }}
          >
            <TrendingUp
              size={40}
              style={{ color: "var(--text-muted)", opacity: 0.4 }}
            />
            <p
              className="text-sm mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              Portfolio equity curve — chart loading...
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ──

function MetricRow({
  label,
  value,
  positive,
  icon,
}: {
  label: string;
  value: string;
  positive: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-1.5">
        {icon && (
          <span style={{ color: "var(--text-muted)" }}>{icon}</span>
        )}
        <span
          className="text-xs uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          {label}
        </span>
      </div>
      <span
        className="text-sm font-semibold"
        style={{
          color: positive ? "var(--accent-green)" : "var(--accent-red)",
        }}
      >
        {value}
      </span>
    </div>
  );
}
