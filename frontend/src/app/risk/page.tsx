"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Shield,
  Zap,
  OctagonX,
  AlertTriangle,
  ShieldCheck,
  Activity,
  ClipboardCheck,
  Ban,
} from "lucide-react";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import type { CircuitBreaker, ComplianceCheck, KillSwitch } from "@/types";
import Badge from "@/components/common/Badge";
import DrawdownBar from "@/components/charts/DrawdownBar";
import ConfirmDialog from "@/components/common/ConfirmDialog";

// ── Types for risk endpoint responses ──

interface RiskStatusResponse {
  kill_switches: KillSwitch[];
  circuit_breakers: CircuitBreaker[];
  rate_limits: { name: string; limit: number; current: number; window_seconds: number }[];
  compliance: ComplianceCheck[];
  limits: {
    max_position_pct: number;
    max_portfolio_risk_pct: number;
    max_daily_loss_pct: number;
    max_order_value: number;
  };
  drawdown_pct?: number;
  orders_today?: number;
  orders_limit?: number;
  positions?: {
    symbol: string;
    nav_pct: number;
    limit_pct: number;
  }[];
  sectors?: {
    sector: string;
    nav_pct: number;
    limit_pct: number;
  }[];
}

// ── Kill switch config ──

const KILL_LEVELS = [
  {
    level: "strategy",
    label: "Strategy Kill",
    description: "Halt all new strategy-generated orders",
    color: "var(--accent-amber)",
    variant: "warning" as const,
  },
  {
    level: "account",
    label: "Account Kill",
    description: "Cancel open orders and block new ones",
    color: "#f97316",
    variant: "warning" as const,
  },
  {
    level: "system",
    label: "System Kill",
    description: "Flatten all positions and halt everything",
    color: "var(--accent-red)",
    variant: "danger" as const,
  },
];

// ── Default circuit breaker display config ──

const CB_DISPLAY = [
  { level: "intraday", label: "Intraday", threshold: -3, timeframe: "Today" },
  { level: "weekly", label: "Weekly", threshold: -5, timeframe: "This Week" },
  { level: "monthly", label: "Monthly", threshold: -8, timeframe: "This Month" },
  { level: "all_time", label: "All-Time", threshold: -15, timeframe: "Lifetime" },
  { level: "velocity", label: "Velocity", threshold: -1.5, timeframe: "10 min" },
];

export default function RiskPage() {
  const queryClient = useQueryClient();
  const [killDialog, setKillDialog] = useState<{
    open: boolean;
    level: string;
    label: string;
    variant: "danger" | "warning";
  }>({ open: false, level: "", label: "", variant: "danger" });

  // ── Data fetching ──

  const { data: riskStatus, isLoading: loadingStatus } = useQuery<RiskStatusResponse>({
    queryKey: ["risk", "status"],
    queryFn: () => apiGet<RiskStatusResponse>("/api/risk/status"),
    refetchInterval: 15_000,
  });

  const { data: circuitBreakers } = useQuery<CircuitBreaker[]>({
    queryKey: ["risk", "circuit-breakers"],
    queryFn: () => apiGet<CircuitBreaker[]>("/api/risk/circuit-breakers"),
    refetchInterval: 10_000,
  });

  // ── Kill switch mutations ──

  const activateKill = useMutation({
    mutationFn: ({ level, reason }: { level: string; reason: string }) =>
      apiPost(`/api/risk/kill-switch/${encodeURIComponent(level)}`, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk"] });
    },
  });

  const deactivateKill = useMutation({
    mutationFn: (level: string) =>
      apiDelete(`/api/risk/kill-switch/${encodeURIComponent(level)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk"] });
    },
  });

  // ── Derived values ──

  const drawdownPct = riskStatus?.drawdown_pct ?? 0;
  const ordersToday = riskStatus?.orders_today ?? 0;
  const ordersLimit = riskStatus?.orders_limit ?? 100;
  const killSwitches = riskStatus?.kill_switches ?? [];
  const compliance = riskStatus?.compliance ?? [];
  const positions = riskStatus?.positions ?? [];
  const sectors = riskStatus?.sectors ?? [];

  const anyKillActive = killSwitches.some((k) => k.active);
  const complianceWarnings = compliance.filter((c) => c.status === "warning").length;
  const complianceFails = compliance.filter((c) => c.status === "fail").length;

  const isKillActive = useCallback(
    (level: string) => killSwitches.find((k) => k.level === level)?.active ?? false,
    [killSwitches]
  );

  const handleKillConfirm = () => {
    const { level } = killDialog;
    if (isKillActive(level)) {
      deactivateKill.mutate(level);
    } else {
      activateKill.mutate({ level, reason: "Manual activation from dashboard" });
    }
    setKillDialog({ open: false, level: "", label: "", variant: "danger" });
  };

  // ── Merge live breaker data with display config ──

  const breakers = CB_DISPLAY.map((display) => {
    const live = circuitBreakers?.find((cb) => cb.level === display.level);
    return {
      ...display,
      threshold: live?.threshold_pct ?? display.threshold,
      current: live?.current_drawdown_pct ?? 0,
      triggered: live?.triggered ?? false,
    };
  });

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1
            className="text-2xl font-bold flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <Shield size={24} style={{ color: "var(--accent-blue)" }} />
            Risk Management
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Real-time risk monitoring and circuit breaker controls
          </p>
        </div>
        {loadingStatus && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            Loading...
          </span>
        )}
      </div>

      {/* ── Top Stat Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Portfolio Drawdown */}
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center justify-between mb-2">
            <span
              className="text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Portfolio Drawdown
            </span>
            <Activity size={16} style={{ color: "var(--text-muted)" }} />
          </div>
          <span
            className="text-2xl font-bold font-mono"
            style={{
              color:
                Math.abs(drawdownPct) > 5
                  ? "var(--accent-red)"
                  : Math.abs(drawdownPct) > 2
                    ? "var(--accent-amber)"
                    : "var(--accent-green)",
            }}
          >
            {drawdownPct.toFixed(2)}%
          </span>
        </div>

        {/* Kill Switch Status */}
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: anyKillActive
              ? "rgba(239, 68, 68, 0.08)"
              : "var(--bg-card)",
            borderColor: anyKillActive
              ? "rgba(239, 68, 68, 0.25)"
              : "var(--border)",
          }}
        >
          <div className="flex items-center justify-between mb-2">
            <span
              className="text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Kill Switch
            </span>
            <OctagonX
              size={16}
              style={{
                color: anyKillActive
                  ? "var(--accent-red)"
                  : "var(--text-muted)",
              }}
            />
          </div>
          {anyKillActive ? (
            <Badge variant="danger">ACTIVE</Badge>
          ) : (
            <span
              className="text-2xl font-bold"
              style={{ color: "var(--accent-green)" }}
            >
              CLEAR
            </span>
          )}
        </div>

        {/* Orders Today */}
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center justify-between mb-2">
            <span
              className="text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Orders Today
            </span>
            <ClipboardCheck size={16} style={{ color: "var(--text-muted)" }} />
          </div>
          <div className="flex items-end gap-1">
            <span
              className="text-2xl font-bold font-mono"
              style={{ color: "var(--text-primary)" }}
            >
              {ordersToday}
            </span>
            <span
              className="text-sm mb-0.5"
              style={{ color: "var(--text-muted)" }}
            >
              / {ordersLimit}
            </span>
          </div>
        </div>

        {/* Compliance Status */}
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center justify-between mb-2">
            <span
              className="text-xs font-medium uppercase tracking-wider"
              style={{ color: "var(--text-muted)" }}
            >
              Compliance
            </span>
            <ShieldCheck size={16} style={{ color: "var(--text-muted)" }} />
          </div>
          {complianceFails > 0 ? (
            <Badge variant="danger">
              {complianceFails} FAIL{complianceFails > 1 ? "S" : ""}
            </Badge>
          ) : complianceWarnings > 0 ? (
            <Badge variant="warning">
              {complianceWarnings} WARNING{complianceWarnings > 1 ? "S" : ""}
            </Badge>
          ) : (
            <span
              className="text-2xl font-bold"
              style={{ color: "var(--accent-green)" }}
            >
              PASS
            </span>
          )}
        </div>
      </div>

      {/* ── Circuit Breakers ── */}
      <div>
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          <Zap
            size={14}
            className="inline mr-1.5"
            style={{ color: "var(--accent-amber)" }}
          />
          Circuit Breakers
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {breakers.map((cb) => {
            const pct =
              cb.threshold !== 0
                ? Math.min(
                    (Math.abs(cb.current) / Math.abs(cb.threshold)) * 100,
                    100
                  )
                : 0;
            let barColor = "var(--accent-green)";
            if (cb.triggered) {
              barColor = "var(--accent-red)";
            } else if (pct >= 80) {
              barColor = "var(--accent-red)";
            } else if (pct >= 60) {
              barColor = "var(--accent-amber)";
            }

            return (
              <div
                key={cb.level}
                className="rounded-lg border p-4"
                style={{
                  backgroundColor: cb.triggered
                    ? "rgba(239, 68, 68, 0.08)"
                    : "var(--bg-card)",
                  borderColor: cb.triggered
                    ? "rgba(239, 68, 68, 0.3)"
                    : "var(--border)",
                }}
              >
                <div className="flex items-center justify-between mb-2">
                  <span
                    className="text-sm font-semibold"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {cb.label}
                  </span>
                  {cb.triggered && <Badge variant="danger">TRIGGERED</Badge>}
                </div>

                <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>
                  Threshold: {cb.threshold}%
                </div>

                <div
                  className="text-xs font-mono mb-2"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Current: {cb.current.toFixed(2)}%
                </div>

                {/* Progress bar */}
                <div
                  className="h-2 rounded-full w-full"
                  style={{ backgroundColor: "var(--bg-hover)" }}
                >
                  <div
                    className="h-2 rounded-full transition-all duration-500"
                    style={{
                      width: `${Math.max(pct, 0)}%`,
                      backgroundColor: barColor,
                      minWidth: pct > 0 ? "3px" : "0",
                    }}
                  />
                </div>

                <div
                  className="text-xs mt-1.5"
                  style={{ color: "var(--text-muted)" }}
                >
                  {cb.timeframe}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Position Limits ── */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-4"
          style={{ color: "var(--text-muted)" }}
        >
          Position Limits
        </h2>

        {/* Per-name concentration */}
        <div className="mb-5">
          <h3
            className="text-xs font-medium mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Per-Name Concentration (% of NAV vs 5% limit)
          </h3>
          {positions.length > 0 ? (
            <div className="space-y-3">
              {positions.map((pos) => (
                <DrawdownBar
                  key={pos.symbol}
                  label={pos.symbol}
                  current={pos.nav_pct}
                  limit={pos.limit_pct}
                  unit="%"
                />
              ))}
            </div>
          ) : (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              No open positions
            </p>
          )}
        </div>

        {/* Sector breakdown */}
        <div className="mb-5">
          <h3
            className="text-xs font-medium mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Sector Exposure
          </h3>
          {sectors.length > 0 ? (
            <div className="space-y-3">
              {sectors.map((sec) => (
                <DrawdownBar
                  key={sec.sector}
                  label={sec.sector}
                  current={sec.nav_pct}
                  limit={sec.limit_pct}
                  unit="%"
                />
              ))}
            </div>
          ) : (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              No sector exposure data
            </p>
          )}
        </div>

        {/* Aggregate limits */}
        <div>
          <h3
            className="text-xs font-medium mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Aggregate Limits
          </h3>
          <div className="space-y-3">
            <DrawdownBar
              label="Daily Loss"
              current={Math.abs(drawdownPct)}
              limit={riskStatus?.limits?.max_daily_loss_pct ?? 3}
              unit="%"
            />
            <DrawdownBar
              label="Portfolio Risk"
              current={0}
              limit={riskStatus?.limits?.max_portfolio_risk_pct ?? 25}
              unit="%"
            />
            <DrawdownBar
              label="Max Order Value"
              current={0}
              limit={riskStatus?.limits?.max_order_value ?? 10000}
              unit="$"
            />
          </div>
        </div>
      </div>

      {/* ── Kill Switch Panel ── */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "rgba(239, 68, 68, 0.04)",
          borderColor: "rgba(239, 68, 68, 0.2)",
        }}
      >
        <div className="flex items-center gap-2 mb-4">
          <OctagonX size={20} style={{ color: "var(--accent-red)" }} />
          <h2
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--accent-red)" }}
          >
            Kill Switches
          </h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {KILL_LEVELS.map((ks) => {
            const active = isKillActive(ks.level);
            const liveSwitch = killSwitches.find((k) => k.level === ks.level);

            return (
              <div
                key={ks.level}
                className="rounded-lg border p-4"
                style={{
                  backgroundColor: active
                    ? "rgba(239, 68, 68, 0.1)"
                    : "var(--bg-card)",
                  borderColor: active
                    ? "rgba(239, 68, 68, 0.3)"
                    : "var(--border)",
                }}
              >
                <div className="flex items-center justify-between mb-2">
                  <span
                    className="text-sm font-semibold"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {ks.label}
                  </span>
                  {active ? (
                    <Badge variant="danger">ACTIVE</Badge>
                  ) : (
                    <Badge variant="success">OFF</Badge>
                  )}
                </div>

                <p
                  className="text-xs mb-3"
                  style={{ color: "var(--text-muted)" }}
                >
                  {ks.description}
                </p>

                {active && liveSwitch?.reason && (
                  <p
                    className="text-xs mb-3 italic"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    Reason: {liveSwitch.reason}
                  </p>
                )}

                <button
                  onClick={() =>
                    setKillDialog({
                      open: true,
                      level: ks.level,
                      label: ks.label,
                      variant: ks.variant,
                    })
                  }
                  className="w-full px-4 py-2 rounded-md text-sm font-bold uppercase tracking-wider transition-all hover:opacity-80"
                  style={{
                    backgroundColor: active
                      ? "var(--bg-hover)"
                      : ks.color,
                    color: active ? "var(--text-primary)" : "white",
                    border: active ? "1px solid var(--border)" : "none",
                  }}
                >
                  {active ? (
                    <span className="flex items-center justify-center gap-1.5">
                      <Ban size={14} /> Deactivate
                    </span>
                  ) : (
                    <span className="flex items-center justify-center gap-1.5">
                      <AlertTriangle size={14} /> Activate
                    </span>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Confirm Dialog ── */}
      <ConfirmDialog
        open={killDialog.open}
        title={
          isKillActive(killDialog.level)
            ? `Deactivate ${killDialog.label}?`
            : `Activate ${killDialog.label}?`
        }
        message={
          isKillActive(killDialog.level)
            ? `This will deactivate the ${killDialog.label.toLowerCase()} and resume normal operations. Are you sure?`
            : `This will immediately activate the ${killDialog.label.toLowerCase()}. This is a potentially disruptive action. Are you sure?`
        }
        confirmLabel={
          isKillActive(killDialog.level) ? "Deactivate" : "Activate"
        }
        confirmVariant={killDialog.variant}
        onConfirm={handleKillConfirm}
        onCancel={() =>
          setKillDialog({ open: false, level: "", label: "", variant: "danger" })
        }
      />
    </div>
  );
}
