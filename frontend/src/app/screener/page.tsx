"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Search,
  AlertTriangle,
  TrendingUp,
  UserCheck,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Loader2,
  Zap,
} from "lucide-react";
import Badge from "@/components/common/Badge";
import { apiGet } from "@/lib/api";
import type { ScreenerResponse, ScreenerResult, Signal } from "@/types";

// ── Preset definitions ──

interface PresetConfig {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  color: string;
}

const presets: PresetConfig[] = [
  {
    id: "distressed",
    title: "Distressed Assets",
    description:
      "Find undervalued stocks trading below book value with high debt ratios",
    icon: <AlertTriangle size={24} />,
    color: "var(--accent-red)",
  },
  {
    id: "short-squeeze",
    title: "Short Squeeze",
    description:
      "High short interest, rising volume, and positive momentum signals",
    icon: <TrendingUp size={24} />,
    color: "var(--accent-amber)",
  },
  {
    id: "insider-buying",
    title: "Insider Buying",
    description:
      "Recent insider purchases from executives and board members",
    icon: <UserCheck size={24} />,
    color: "var(--accent-green)",
  },
  {
    id: "ai-opportunity",
    title: "AI Opportunity",
    description:
      "AI-identified opportunities using multi-factor pattern recognition",
    icon: <Sparkles size={24} />,
    color: "var(--accent-purple)",
  },
];

// ── Formatting helpers ──

const currencyCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

const signalTypeMeta: Record<
  string,
  { label: string; variant: "info" | "warning" | "success" | "danger" | "neutral" }
> = {
  volume: { label: "Volume", variant: "info" },
  squeeze: { label: "Squeeze", variant: "neutral" },
  insider: { label: "Insider", variant: "success" },
  technical: { label: "Technical", variant: "warning" },
  distressed: { label: "Distressed", variant: "danger" },
  ai_composite: { label: "AI", variant: "neutral" },
};

export default function ScreenerPage() {
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  // Custom filter state
  const [minMarketCap, setMinMarketCap] = useState("");
  const [sector, setSector] = useState("");
  const [minScore, setMinScore] = useState(0);

  // ── Fetch preset counts (overview) ──
  const { data: overview } = useQuery<
    Record<string, { count: number }>
  >({
    queryKey: ["screener", "overview"],
    queryFn: () =>
      apiGet<Record<string, { count: number }>>("/api/screener/overview").catch(
        () => ({})
      ),
    staleTime: 120_000,
  });

  // ── Fetch results for active preset ──
  const { data: results, isLoading: resultsLoading } =
    useQuery<ScreenerResponse>({
      queryKey: ["screener", "results", activePreset],
      queryFn: () =>
        apiGet<ScreenerResponse>(
          `/api/screener/presets/${activePreset}`
        ),
      enabled: !!activePreset,
    });

  // Filter results client-side
  const filteredResults = (results?.results ?? []).filter((r) => {
    if (minScore > 0 && r.score < minScore) return false;
    if (minMarketCap && r.market_cap < Number(minMarketCap) * 1_000_000)
      return false;
    if (sector && !r.sector.toLowerCase().includes(sector.toLowerCase()))
      return false;
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1
          className="text-2xl font-bold flex items-center gap-2"
          style={{ color: "var(--text-primary)" }}
        >
          <Search size={24} style={{ color: "var(--accent-blue)" }} />
          Stock Screener
        </h1>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--text-secondary)" }}
        >
          Scan the market with AI-powered preset strategies
        </p>
      </div>

      {/* Preset Strategy Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {presets.map((preset) => {
          const isActive = activePreset === preset.id;
          const count = overview?.[preset.id]?.count;
          return (
            <button
              key={preset.id}
              onClick={() =>
                setActivePreset(isActive ? null : preset.id)
              }
              className="text-left rounded-lg border p-5 transition-all hover:scale-[1.02] relative"
              style={{
                backgroundColor: "var(--bg-card)",
                borderColor: isActive
                  ? preset.color
                  : "var(--border)",
                borderWidth: isActive ? 2 : 1,
              }}
            >
              <div className="mb-3 flex items-center justify-between">
                <span style={{ color: preset.color }}>{preset.icon}</span>
                {count !== undefined && (
                  <span
                    className="flex items-center justify-center h-5 min-w-5 rounded-full text-xs font-bold px-1.5"
                    style={{
                      backgroundColor: `${preset.color}22`,
                      color: preset.color,
                    }}
                  >
                    {count}
                  </span>
                )}
              </div>
              <h3
                className="text-sm font-semibold mb-1"
                style={{ color: "var(--text-primary)" }}
              >
                {preset.title}
              </h3>
              <p
                className="text-xs leading-relaxed"
                style={{ color: "var(--text-muted)" }}
              >
                {preset.description}
              </p>
            </button>
          );
        })}
      </div>

      {/* Custom Filters (collapsible) */}
      <div
        className="rounded-lg border"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium"
          style={{ color: "var(--text-secondary)" }}
        >
          <span>Custom Filters</span>
          {showFilters ? (
            <ChevronUp size={16} />
          ) : (
            <ChevronDown size={16} />
          )}
        </button>
        {showFilters && (
          <div
            className="px-4 pb-4 flex flex-wrap items-end gap-4 border-t"
            style={{ borderColor: "var(--border)" }}
          >
            <div className="mt-3">
              <label
                className="block text-xs uppercase tracking-wider mb-1"
                style={{ color: "var(--text-muted)" }}
              >
                Min Market Cap ($M)
              </label>
              <input
                type="number"
                value={minMarketCap}
                onChange={(e) => setMinMarketCap(e.target.value)}
                placeholder="e.g. 50"
                className="rounded-md border px-3 py-1.5 text-sm w-28"
                style={{
                  backgroundColor: "var(--bg-primary)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>
            <div className="mt-3">
              <label
                className="block text-xs uppercase tracking-wider mb-1"
                style={{ color: "var(--text-muted)" }}
              >
                Sector
              </label>
              <input
                type="text"
                value={sector}
                onChange={(e) => setSector(e.target.value)}
                placeholder="e.g. Technology"
                className="rounded-md border px-3 py-1.5 text-sm w-36"
                style={{
                  backgroundColor: "var(--bg-primary)",
                  borderColor: "var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>
            <div className="mt-3">
              <label
                className="block text-xs uppercase tracking-wider mb-1"
                style={{ color: "var(--text-muted)" }}
              >
                Min Score: {minScore}
              </label>
              <input
                type="range"
                min={0}
                max={10}
                step={1}
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className="w-32 accent-blue-500"
              />
            </div>
          </div>
        )}
      </div>

      {/* Results Area */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <div className="flex items-center gap-2 mb-4">
          <h2
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-primary)" }}
          >
            Screening Results
          </h2>
          {results && (
            <Badge variant="info">
              {filteredResults.length} match{filteredResults.length !== 1 ? "es" : ""}
            </Badge>
          )}
        </div>

        {!activePreset ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Search
              size={48}
              style={{ color: "var(--text-muted)", opacity: 0.4 }}
            />
            <p
              className="text-sm mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              Select a screening preset above to scan for opportunities.
            </p>
          </div>
        ) : resultsLoading ? (
          <div className="flex flex-col items-center justify-center py-16">
            <Loader2
              size={32}
              className="animate-spin"
              style={{ color: "var(--accent-blue)" }}
            />
            <p
              className="text-sm mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              Running screener...
            </p>
          </div>
        ) : filteredResults.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Search
              size={40}
              style={{ color: "var(--text-muted)", opacity: 0.4 }}
            />
            <p
              className="text-sm mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              No results match the current filters. Try adjusting your criteria.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {filteredResults.map((result) => {
              const isExpanded = expandedRow === result.symbol;
              const scoreMeta = signalTypeMeta[result.latest_signal_type] ?? signalTypeMeta.technical;
              return (
                <div key={result.symbol}>
                  <button
                    onClick={() =>
                      setExpandedRow(isExpanded ? null : result.symbol)
                    }
                    className="w-full text-left rounded-md p-3 flex items-center gap-4 transition-colors"
                    style={{ backgroundColor: "var(--bg-hover)" }}
                  >
                    {/* Symbol */}
                    <span
                      className="text-sm font-bold w-16"
                      style={{ color: "var(--text-primary)" }}
                    >
                      {result.symbol}
                    </span>

                    {/* Name */}
                    <span
                      className="text-sm flex-1 truncate"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {result.name}
                    </span>

                    {/* Score Badge */}
                    <Badge
                      variant={
                        result.score >= 8
                          ? "success"
                          : result.score >= 6
                            ? "warning"
                            : "neutral"
                      }
                    >
                      {result.score.toFixed(1)}
                    </Badge>

                    {/* Market Cap */}
                    <span
                      className="text-xs w-20 text-right"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {currencyCompact.format(result.market_cap)}
                    </span>

                    {/* Signal Count */}
                    <span
                      className="flex items-center gap-1 text-xs w-16 text-right"
                      style={{ color: "var(--text-muted)" }}
                    >
                      <Zap size={10} />
                      {result.signal_count}
                    </span>

                    {/* Signal Type Badge */}
                    <Badge variant={scoreMeta.variant}>
                      {scoreMeta.label}
                    </Badge>

                    {isExpanded ? (
                      <ChevronUp
                        size={14}
                        style={{ color: "var(--text-muted)" }}
                      />
                    ) : (
                      <ChevronDown
                        size={14}
                        style={{ color: "var(--text-muted)" }}
                      />
                    )}
                  </button>

                  {/* Expanded signal details */}
                  {isExpanded && result.signals.length > 0 && (
                    <div
                      className="ml-6 mt-1 mb-2 rounded-md p-3 space-y-2"
                      style={{
                        backgroundColor: "var(--bg-primary)",
                        borderLeft: "2px solid var(--border)",
                      }}
                    >
                      {result.signals.map((sig, i) => {
                        const sMeta =
                          signalTypeMeta[sig.signal_type] ??
                          signalTypeMeta.technical;
                        return (
                          <div
                            key={sig.id ?? i}
                            className="flex items-start gap-2"
                          >
                            <Badge variant={sMeta.variant}>
                              {sMeta.label}
                            </Badge>
                            <div className="flex-1">
                              <span
                                className="text-xs font-medium"
                                style={{
                                  color: "var(--text-primary)",
                                }}
                              >
                                {sig.title}
                              </span>
                              <p
                                className="text-xs mt-0.5"
                                style={{
                                  color: "var(--text-secondary)",
                                }}
                              >
                                {sig.description}
                              </p>
                            </div>
                            <Badge
                              variant={
                                sig.score >= 8
                                  ? "success"
                                  : sig.score >= 6
                                    ? "warning"
                                    : "neutral"
                              }
                            >
                              {sig.score}/10
                            </Badge>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
