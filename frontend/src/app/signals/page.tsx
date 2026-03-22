"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Zap,
  AlertOctagon,
  AlertTriangle,
  Info,
  Filter,
  Search,
  Loader2,
} from "lucide-react";
import Badge from "@/components/common/Badge";
import { apiGet } from "@/lib/api";
import { tradingWS } from "@/lib/ws";
import type { Signal, SignalType } from "@/types";

// ── Formatting helpers ──

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
  {
    label: string;
    color: string;
    variant: "info" | "warning" | "success" | "danger" | "neutral";
  }
> = {
  volume: { label: "Volume", color: "var(--accent-blue)", variant: "info" },
  squeeze: {
    label: "Squeeze",
    color: "var(--accent-purple)",
    variant: "neutral",
  },
  insider: {
    label: "Insider",
    color: "var(--accent-green)",
    variant: "success",
  },
  technical: {
    label: "Technical",
    color: "var(--accent-amber)",
    variant: "warning",
  },
  distressed: {
    label: "Distressed",
    color: "var(--accent-red)",
    variant: "danger",
  },
  ai_composite: {
    label: "AI",
    color: "var(--accent-purple)",
    variant: "neutral",
  },
};

// ── Section definitions ──

interface SignalSection {
  title: string;
  priority: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
  borderColor: string;
  emptyMessage: string;
  filter: (s: Signal) => boolean;
}

const sections: SignalSection[] = [
  {
    title: "Critical Signals",
    priority: "critical",
    icon: <AlertOctagon size={16} />,
    color: "var(--accent-red)",
    bgColor: "rgba(239, 68, 68, 0.08)",
    borderColor: "rgba(239, 68, 68, 0.25)",
    emptyMessage: "No critical signals. Your portfolio is stable.",
    filter: (s: Signal) => s.score >= 8,
  },
  {
    title: "Warning Signals",
    priority: "warning",
    icon: <AlertTriangle size={16} />,
    color: "var(--accent-amber)",
    bgColor: "rgba(245, 158, 11, 0.08)",
    borderColor: "rgba(245, 158, 11, 0.25)",
    emptyMessage: "No warnings at this time.",
    filter: (s: Signal) => s.score >= 6 && s.score < 8,
  },
  {
    title: "Informational",
    priority: "info",
    icon: <Info size={16} />,
    color: "var(--accent-blue)",
    bgColor: "rgba(59, 130, 246, 0.08)",
    borderColor: "rgba(59, 130, 246, 0.25)",
    emptyMessage:
      "No informational signals. Connect data feeds to receive updates.",
    filter: (s: Signal) => s.score < 6,
  },
];

export default function SignalsPage() {
  // ── Filter state ──
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [tickerSearch, setTickerSearch] = useState("");
  const [minScore, setMinScore] = useState(0);

  // ── Build query string ──
  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    if (typeFilter) params.set("signal_type", typeFilter);
    if (tickerSearch.trim())
      params.set("ticker", tickerSearch.trim().toUpperCase());
    if (minScore > 0) params.set("min_score", String(minScore));
    params.set("limit", "100");
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }, [typeFilter, tickerSearch, minScore]);

  // ── Fetch signals ──
  const {
    data: apiSignals,
    isLoading,
  } = useQuery<Signal[]>({
    queryKey: ["signals", typeFilter, tickerSearch, minScore],
    queryFn: () => apiGet<Signal[]>(`/api/signals${queryParams}`),
    refetchInterval: 60_000,
  });

  // ── Real-time signals via WebSocket ──
  const realtimeRef = useRef<Signal[]>([]);
  const [realtimeSignals, setRealtimeSignals] = useState<Signal[]>([]);

  const handleWsSignal = useCallback((data: unknown) => {
    const signal = data as Signal;
    if (signal?.id) {
      realtimeRef.current = [signal, ...realtimeRef.current].slice(0, 50);
      setRealtimeSignals([...realtimeRef.current]);
    }
  }, []);

  useEffect(() => {
    tradingWS.subscribe("signals", handleWsSignal);
    return () => tradingWS.unsubscribe("signals", handleWsSignal);
  }, [handleWsSignal]);

  // ── Merge and deduplicate ──
  const allSignals = useMemo(() => {
    const seen = new Set<number>();
    const merged: Signal[] = [];

    // Realtime first (newest)
    for (const s of realtimeSignals) {
      if (!seen.has(s.id)) {
        seen.add(s.id);
        merged.push(s);
      }
    }
    // Then API signals
    for (const s of apiSignals ?? []) {
      if (!seen.has(s.id)) {
        seen.add(s.id);
        merged.push(s);
      }
    }

    return merged;
  }, [apiSignals, realtimeSignals]);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1
          className="text-2xl font-bold flex items-center gap-2"
          style={{ color: "var(--text-primary)" }}
        >
          <Zap size={24} style={{ color: "var(--accent-amber)" }} />
          Signal & Alert Center
        </h1>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--text-secondary)" }}
        >
          Real-time trading signals organized by priority
        </p>
      </div>

      {/* Filter Bar */}
      <div
        className="rounded-lg border p-4 flex flex-wrap items-center gap-3"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <div
          className="flex items-center gap-1.5"
          style={{ color: "var(--text-muted)" }}
        >
          <Filter size={14} />
          <span className="text-xs font-medium uppercase tracking-wider">
            Filters
          </span>
        </div>

        {/* Signal Type Dropdown */}
        <select
          className="rounded-md border px-3 py-1.5 text-sm"
          style={{
            backgroundColor: "var(--bg-primary)",
            borderColor: "var(--border)",
            color: "var(--text-secondary)",
          }}
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="">All Types</option>
          <option value="volume">Volume</option>
          <option value="squeeze">Squeeze</option>
          <option value="insider">Insider</option>
          <option value="technical">Technical</option>
          <option value="distressed">Distressed</option>
          <option value="ai_composite">AI Composite</option>
        </select>

        {/* Ticker Search */}
        <div
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5"
          style={{
            backgroundColor: "var(--bg-primary)",
            borderColor: "var(--border)",
          }}
        >
          <Search size={12} style={{ color: "var(--text-muted)" }} />
          <input
            type="text"
            placeholder="Ticker..."
            value={tickerSearch}
            onChange={(e) => setTickerSearch(e.target.value)}
            className="bg-transparent border-none outline-none text-sm w-20"
            style={{ color: "var(--text-primary)" }}
          />
        </div>

        {/* Min Score */}
        <div className="flex items-center gap-2">
          <span
            className="text-xs"
            style={{ color: "var(--text-muted)" }}
          >
            Min Score: {minScore}
          </span>
          <input
            type="range"
            min={0}
            max={10}
            step={1}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-24 accent-blue-500"
          />
        </div>

        {/* Signal count */}
        <span
          className="ml-auto text-xs"
          style={{ color: "var(--text-muted)" }}
        >
          {allSignals.length} signal{allSignals.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Loading State */}
      {isLoading && allSignals.length === 0 && (
        <div className="flex items-center justify-center py-8">
          <Loader2
            size={24}
            className="animate-spin"
            style={{ color: "var(--accent-blue)" }}
          />
          <span
            className="ml-2 text-sm"
            style={{ color: "var(--text-muted)" }}
          >
            Loading signals...
          </span>
        </div>
      )}

      {/* Signal Sections */}
      {sections.map((section) => {
        const sectionSignals = allSignals.filter(section.filter);
        return (
          <div
            key={section.priority}
            className="rounded-lg border p-5"
            style={{
              backgroundColor: section.bgColor,
              borderColor: section.borderColor,
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <span style={{ color: section.color }}>{section.icon}</span>
              <h2
                className="text-sm font-semibold uppercase tracking-wider"
                style={{ color: section.color }}
              >
                {section.title}
              </h2>
              <span
                className="ml-auto flex items-center justify-center h-5 min-w-5 rounded-full text-xs font-bold"
                style={{
                  backgroundColor: section.borderColor,
                  color: section.color,
                }}
              >
                {sectionSignals.length}
              </span>
            </div>

            {sectionSignals.length === 0 ? (
              <div className="flex items-center justify-center py-8">
                <p
                  className="text-sm"
                  style={{ color: "var(--text-muted)" }}
                >
                  {section.emptyMessage}
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {sectionSignals.map((signal) => {
                  const meta =
                    signalTypeMeta[signal.signal_type] ??
                    signalTypeMeta.technical;
                  const confidencePct = Math.round(signal.confidence * 100);
                  return (
                    <div
                      key={signal.id}
                      className="rounded-md p-3 transition-colors"
                      style={{ backgroundColor: "var(--bg-card)" }}
                    >
                      <div className="flex items-start gap-3">
                        {/* Symbol and type */}
                        <div className="flex items-center gap-2 w-36 shrink-0">
                          <span
                            className="text-sm font-bold"
                            style={{ color: "var(--text-primary)" }}
                          >
                            {signal.symbol}
                          </span>
                          <Badge variant={meta.variant}>
                            {meta.label}
                          </Badge>
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span
                              className="text-sm font-medium"
                              style={{
                                color: "var(--text-primary)",
                              }}
                            >
                              {signal.title}
                            </span>
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
                          </div>
                          <p
                            className="text-xs line-clamp-2"
                            style={{
                              color: "var(--text-secondary)",
                            }}
                          >
                            {signal.description}
                          </p>

                          {/* Confidence bar */}
                          <div className="flex items-center gap-2 mt-2">
                            <span
                              className="text-[10px] uppercase tracking-wider"
                              style={{
                                color: "var(--text-muted)",
                              }}
                            >
                              Confidence
                            </span>
                            <div
                              className="flex-1 h-1 rounded-full max-w-32"
                              style={{
                                backgroundColor: "var(--bg-hover)",
                              }}
                            >
                              <div
                                className="h-1 rounded-full transition-all duration-300"
                                style={{
                                  width: `${confidencePct}%`,
                                  backgroundColor:
                                    confidencePct >= 70
                                      ? "var(--accent-green)"
                                      : confidencePct >= 40
                                        ? "var(--accent-amber)"
                                        : "var(--accent-red)",
                                }}
                              />
                            </div>
                            <span
                              className="text-[10px] font-medium"
                              style={{
                                color:
                                  confidencePct >= 70
                                    ? "var(--accent-green)"
                                    : confidencePct >= 40
                                      ? "var(--accent-amber)"
                                      : "var(--accent-red)",
                              }}
                            >
                              {confidencePct}%
                            </span>
                          </div>
                        </div>

                        {/* Time */}
                        <span
                          className="text-xs whitespace-nowrap shrink-0"
                          style={{ color: "var(--text-muted)" }}
                        >
                          {timeAgo(signal.timestamp)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
