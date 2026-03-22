"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Settings,
  Cpu,
  HardDrive,
  Gauge,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Server,
  Database,
  Radio,
  Brain,
  FileText,
  Wifi,
  Cloud,
} from "lucide-react";
import { apiGet } from "@/lib/api";
import type {
  SystemHealth,
  ComponentHealth,
  AuditLogEntry,
  SystemConfig,
} from "@/types";
import StatusDot from "@/components/common/StatusDot";
import Badge from "@/components/common/Badge";

// ── Extended types ──

interface SystemStatusResponse {
  mode: string;
  shadow_mode: boolean;
  workers: Record<string, string>;
  ai_costs?: {
    monthly_estimate: number;
    requests_today: number;
  };
  uptime_seconds?: number;
}

interface AuditLogResponse {
  entries: AuditLogEntry[];
  total: number;
}

// ── Service icon map ──

const SERVICE_ICONS: Record<string, React.ReactNode> = {
  PostgreSQL: <Database size={16} style={{ color: "var(--accent-blue)" }} />,
  QuestDB: <Database size={16} style={{ color: "var(--accent-purple)" }} />,
  Redis: <Server size={16} style={{ color: "var(--accent-red)" }} />,
  "Ollama / Qwen": <Brain size={16} style={{ color: "var(--accent-green)" }} />,
  "Polygon WS": <Wifi size={16} style={{ color: "var(--accent-amber)" }} />,
  EDGAR: <FileText size={16} style={{ color: "var(--accent-blue)" }} />,
  "Anthropic API": <Cloud size={16} style={{ color: "var(--accent-purple)" }} />,
};

function healthToStatus(
  status: string
): "connected" | "disconnected" | "degraded" {
  if (status === "healthy") return "connected";
  if (status === "degraded") return "degraded";
  return "disconnected";
}

function formatLatency(ms?: number): string {
  if (ms === undefined || ms === null) return "--";
  if (ms < 1) return "<1ms";
  return `${Math.round(ms)}ms`;
}

function formatUptime(seconds?: number): string {
  if (!seconds) return "--";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

export default function SystemPage() {
  const [configExpanded, setConfigExpanded] = useState(false);
  const [auditPage, setAuditPage] = useState(0);
  const AUDIT_LIMIT = 20;

  // ── Data fetching ──

  const {
    data: health,
    isLoading: loadingHealth,
    dataUpdatedAt: healthUpdatedAt,
  } = useQuery<SystemHealth>({
    queryKey: ["system", "health"],
    queryFn: () => apiGet<SystemHealth>("/api/system/health"),
    refetchInterval: 30_000,
  });

  const { data: systemStatus } = useQuery<SystemStatusResponse>({
    queryKey: ["system", "status"],
    queryFn: () => apiGet<SystemStatusResponse>("/api/system/status"),
    refetchInterval: 60_000,
  });

  const { data: systemConfig } = useQuery<SystemConfig>({
    queryKey: ["system", "config"],
    queryFn: () => apiGet<SystemConfig>("/api/system/config"),
    staleTime: 120_000,
  });

  const { data: auditLog, isLoading: loadingAudit } = useQuery<AuditLogResponse>({
    queryKey: ["system", "audit-log", auditPage],
    queryFn: () =>
      apiGet<AuditLogResponse>(
        `/api/system/audit-log?limit=${AUDIT_LIMIT}&offset=${auditPage * AUDIT_LIMIT}`
      ),
    staleTime: 30_000,
  });

  // ── Derived values ──

  const components: ComponentHealth[] = health?.components ?? [];
  const lastCheckTime = healthUpdatedAt
    ? new Date(healthUpdatedAt).toLocaleTimeString()
    : "--";

  const workers = systemStatus?.workers ?? {};
  const mode = systemStatus?.mode ?? "paper";
  const shadowMode = systemStatus?.shadow_mode ?? false;
  const aiCosts = systemStatus?.ai_costs;

  // Filter out secret-looking config values
  const safeConfig = systemConfig
    ? Object.entries(systemConfig).filter(
        ([key]) =>
          !key.toLowerCase().includes("secret") &&
          !key.toLowerCase().includes("password") &&
          !key.toLowerCase().includes("token") &&
          !key.toLowerCase().includes("api_key")
      )
    : [];

  const auditEntries = auditLog?.entries ?? [];
  const auditTotal = auditLog?.total ?? 0;
  const totalAuditPages = Math.max(1, Math.ceil(auditTotal / AUDIT_LIMIT));

  // Placeholder resource gauges
  const resources = [
    { label: "CPU", value: 0, unit: "%", icon: <Cpu size={16} style={{ color: "var(--accent-blue)" }} /> },
    { label: "RAM", value: 0, unit: "%", icon: <HardDrive size={16} style={{ color: "var(--accent-purple)" }} /> },
    { label: "GPU", value: 0, unit: "%", icon: <Gauge size={16} style={{ color: "var(--accent-green)" }} /> },
  ];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1
            className="text-2xl font-bold flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <Settings size={24} style={{ color: "var(--accent-blue)" }} />
            System Health
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Monitor infrastructure, services, and audit trail
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            Last check: {lastCheckTime}
          </span>
          {loadingHealth && (
            <RefreshCw
              size={14}
              className="animate-spin"
              style={{ color: "var(--text-muted)" }}
            />
          )}
        </div>
      </div>

      {/* ── Service Health Grid ── */}
      <div>
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          Services
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {components.length > 0
            ? components.map((comp) => (
                <div
                  key={comp.name}
                  className="rounded-lg border p-4"
                  style={{
                    backgroundColor: "var(--bg-card)",
                    borderColor: "var(--border)",
                  }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {SERVICE_ICONS[comp.name] ?? (
                        <Radio size={16} style={{ color: "var(--text-muted)" }} />
                      )}
                      <span
                        className="text-sm font-semibold"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {comp.name}
                      </span>
                    </div>
                    <StatusDot status={healthToStatus(comp.status)} size="md" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      {comp.status === "healthy"
                        ? "Connected"
                        : comp.status === "degraded"
                          ? "Degraded"
                          : comp.message || "Disconnected"}
                    </span>
                    <span
                      className="text-xs font-mono"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {formatLatency(comp.latency_ms)}
                    </span>
                  </div>
                </div>
              ))
            : // Fallback: show default services as disconnected
              [
                "PostgreSQL",
                "QuestDB",
                "Redis",
                "Ollama / Qwen",
                "Polygon WS",
                "EDGAR",
                "Anthropic API",
              ].map((name) => (
                <div
                  key={name}
                  className="rounded-lg border p-4"
                  style={{
                    backgroundColor: "var(--bg-card)",
                    borderColor: "var(--border)",
                  }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {SERVICE_ICONS[name] ?? (
                        <Radio size={16} style={{ color: "var(--text-muted)" }} />
                      )}
                      <span
                        className="text-sm font-semibold"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {name}
                      </span>
                    </div>
                    <StatusDot status="disconnected" size="md" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      Awaiting connection
                    </span>
                    <span
                      className="text-xs font-mono"
                      style={{ color: "var(--text-muted)" }}
                    >
                      --
                    </span>
                  </div>
                </div>
              ))}
        </div>
      </div>

      {/* ── System Status Section ── */}
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
          System Status
        </h2>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
          {/* Mode */}
          <div>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Mode
            </span>
            <div className="mt-1">
              <Badge variant={mode === "live" ? "danger" : "success"}>
                {mode === "live" ? "LIVE" : "PAPER"}
              </Badge>
            </div>
          </div>

          {/* Shadow Mode */}
          <div>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Shadow Mode
            </span>
            <div className="mt-1">
              <Badge variant={shadowMode ? "info" : "neutral"}>
                {shadowMode ? "ON" : "OFF"}
              </Badge>
            </div>
          </div>

          {/* AI Costs */}
          <div>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              AI Cost (Monthly Est.)
            </span>
            <p
              className="text-sm font-medium font-mono mt-1"
              style={{ color: "var(--text-secondary)" }}
            >
              {aiCosts
                ? `$${aiCosts.monthly_estimate.toFixed(2)}`
                : "--"}
            </p>
          </div>

          {/* Uptime */}
          <div>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Uptime
            </span>
            <p
              className="text-sm font-medium mt-1"
              style={{ color: "var(--text-secondary)" }}
            >
              {formatUptime(systemStatus?.uptime_seconds)}
            </p>
          </div>
        </div>

        {/* Workers */}
        <div>
          <span
            className="text-xs font-medium"
            style={{ color: "var(--text-muted)" }}
          >
            Workers
          </span>
          <div className="flex flex-wrap gap-2 mt-2">
            {Object.keys(workers).length > 0
              ? Object.entries(workers).map(([name, status]) => (
                  <div
                    key={name}
                    className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs border"
                    style={{
                      backgroundColor: "var(--bg-hover)",
                      borderColor: "var(--border)",
                    }}
                  >
                    <StatusDot
                      status={
                        status === "running"
                          ? "connected"
                          : status === "idle"
                            ? "degraded"
                            : "disconnected"
                      }
                      size="sm"
                      pulse={status === "running"}
                    />
                    <span style={{ color: "var(--text-secondary)" }}>
                      {name}
                    </span>
                  </div>
                ))
              : ["market_data", "edgar", "signal_scanner", "health_monitor", "ai_worker"].map(
                  (name) => (
                    <div
                      key={name}
                      className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs border"
                      style={{
                        backgroundColor: "var(--bg-hover)",
                        borderColor: "var(--border)",
                      }}
                    >
                      <StatusDot status="disconnected" size="sm" pulse={false} />
                      <span style={{ color: "var(--text-muted)" }}>
                        {name}
                      </span>
                    </div>
                  )
                )}
          </div>
        </div>
      </div>

      {/* ── Configuration (Collapsible) ── */}
      <div
        className="rounded-lg border"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <button
          onClick={() => setConfigExpanded(!configExpanded)}
          className="w-full flex items-center justify-between p-4 text-left transition-colors"
          style={{ color: "var(--text-primary)" }}
        >
          <span className="text-sm font-semibold uppercase tracking-wider">
            Configuration
          </span>
          {configExpanded ? (
            <ChevronDown size={16} style={{ color: "var(--text-muted)" }} />
          ) : (
            <ChevronRight size={16} style={{ color: "var(--text-muted)" }} />
          )}
        </button>

        {configExpanded && (
          <div
            className="border-t px-4 pb-4"
            style={{ borderColor: "var(--border)" }}
          >
            {safeConfig.length > 0 ? (
              <table className="w-full text-xs mt-3">
                <thead>
                  <tr>
                    <th
                      className="text-left py-1.5 font-medium uppercase tracking-wider"
                      style={{ color: "var(--text-muted)" }}
                    >
                      Key
                    </th>
                    <th
                      className="text-left py-1.5 font-medium uppercase tracking-wider"
                      style={{ color: "var(--text-muted)" }}
                    >
                      Value
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {safeConfig.map(([key, value]) => (
                    <tr
                      key={key}
                      className="border-t"
                      style={{ borderColor: "var(--border)" }}
                    >
                      <td
                        className="py-2 font-mono"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        {key}
                      </td>
                      <td
                        className="py-2 font-mono"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {typeof value === "boolean"
                          ? value
                            ? "true"
                            : "false"
                          : String(value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p
                className="text-xs mt-3"
                style={{ color: "var(--text-muted)" }}
              >
                No configuration data available
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Audit Log ── */}
      <div
        className="rounded-lg border"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <div
          className="flex items-center justify-between p-4 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <h2
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Audit Log
          </h2>
          {loadingAudit && (
            <RefreshCw
              size={14}
              className="animate-spin"
              style={{ color: "var(--text-muted)" }}
            />
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr
                className="border-b"
                style={{ borderColor: "var(--border)" }}
              >
                <th
                  className="text-left px-4 py-2.5 font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-muted)" }}
                >
                  Timestamp
                </th>
                <th
                  className="text-left px-4 py-2.5 font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-muted)" }}
                >
                  Action
                </th>
                <th
                  className="text-left px-4 py-2.5 font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-muted)" }}
                >
                  Actor
                </th>
                <th
                  className="text-left px-4 py-2.5 font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-muted)" }}
                >
                  Target
                </th>
                <th
                  className="text-left px-4 py-2.5 font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-muted)" }}
                >
                  Details
                </th>
              </tr>
            </thead>
            <tbody>
              {auditEntries.length > 0 ? (
                auditEntries.map((entry) => (
                  <tr
                    key={entry.id}
                    className="border-b"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <td
                      className="px-4 py-2.5 whitespace-nowrap font-mono"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {new Date(entry.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge
                        variant={
                          entry.action.includes("kill") ||
                          entry.action.includes("reject")
                            ? "danger"
                            : entry.action.includes("warn")
                              ? "warning"
                              : "info"
                        }
                      >
                        {entry.action}
                      </Badge>
                    </td>
                    <td
                      className="px-4 py-2.5"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {entry.actor}
                    </td>
                    <td
                      className="px-4 py-2.5 font-mono"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {entry.target || "--"}
                    </td>
                    <td
                      className="px-4 py-2.5 max-w-xs truncate"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {entry.details
                        ? JSON.stringify(entry.details).slice(0, 80)
                        : "--"}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center"
                    style={{ color: "var(--text-muted)" }}
                  >
                    No audit log entries
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {auditTotal > AUDIT_LIMIT && (
          <div
            className="flex items-center justify-between px-4 py-3 border-t"
            style={{ borderColor: "var(--border)" }}
          >
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Page {auditPage + 1} of {totalAuditPages} ({auditTotal} entries)
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setAuditPage(Math.max(0, auditPage - 1))}
                disabled={auditPage === 0}
                className="px-3 py-1 rounded text-xs font-medium border transition-colors disabled:opacity-30"
                style={{
                  backgroundColor: "var(--bg-hover)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              >
                Previous
              </button>
              <button
                onClick={() =>
                  setAuditPage(Math.min(totalAuditPages - 1, auditPage + 1))
                }
                disabled={auditPage >= totalAuditPages - 1}
                className="px-3 py-1 rounded text-xs font-medium border transition-colors disabled:opacity-30"
                style={{
                  backgroundColor: "var(--bg-hover)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Resource Gauges ── */}
      <div>
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          Resource Usage
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {resources.map((resource) => (
            <div
              key={resource.label}
              className="rounded-lg border p-4"
              style={{
                backgroundColor: "var(--bg-card)",
                borderColor: "var(--border)",
              }}
            >
              <div className="flex items-center gap-2 mb-3">
                {resource.icon}
                <span
                  className="text-sm font-semibold"
                  style={{ color: "var(--text-primary)" }}
                >
                  {resource.label}
                </span>
                <span
                  className="ml-auto text-sm font-mono"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {resource.value}
                  {resource.unit}
                </span>
              </div>
              <div
                className="h-2 rounded-full w-full"
                style={{ backgroundColor: "var(--bg-hover)" }}
              >
                <div
                  className="h-2 rounded-full transition-all duration-500"
                  style={{
                    width: `${resource.value}%`,
                    backgroundColor:
                      resource.value > 80
                        ? "var(--accent-red)"
                        : resource.value > 60
                          ? "var(--accent-amber)"
                          : "var(--accent-green)",
                    minWidth: resource.value > 0 ? "4px" : "0",
                  }}
                />
              </div>
              <p
                className="text-xs mt-2 italic"
                style={{ color: "var(--text-muted)" }}
              >
                Placeholder -- real metrics coming soon
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
