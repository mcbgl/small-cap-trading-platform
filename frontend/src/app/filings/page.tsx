"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FileText,
  Filter,
  Tag,
  ChevronDown,
  ChevronUp,
  Loader2,
  Search,
  BarChart3,
  ExternalLink,
} from "lucide-react";
import Badge from "@/components/common/Badge";
import { apiGet } from "@/lib/api";
import type { Filing } from "@/types";

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

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ── Filing type badge styling ──

const formTypeMeta: Record<
  string,
  { variant: "danger" | "warning" | "info" | "success" | "neutral" }
> = {
  "8-K": { variant: "danger" },
  "10-K": { variant: "info" },
  "10-Q": { variant: "warning" },
  "4": { variant: "success" },
  "SC 13D": { variant: "danger" },
  "S-1": { variant: "neutral" },
  "DEF 14A": { variant: "neutral" },
};

export default function FilingsPage() {
  const [formType, setFormType] = useState("");
  const [tickerSearch, setTickerSearch] = useState("");
  const [hasKeywords, setHasKeywords] = useState(false);
  const [expandedFiling, setExpandedFiling] = useState<number | null>(null);

  // ── Build query string ──
  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    if (formType) params.set("form_type", formType);
    if (tickerSearch.trim()) params.set("ticker", tickerSearch.trim().toUpperCase());
    params.set("limit", "50");
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }, [formType, tickerSearch]);

  // ── Fetch filings ──
  const { data: filings, isLoading: filingsLoading } = useQuery<Filing[]>({
    queryKey: ["filings", formType, tickerSearch],
    queryFn: () => apiGet<Filing[]>(`/api/filings${queryParams}`),
    refetchInterval: 120_000,
  });

  // ── Fetch keyword frequencies ──
  const { data: keywords } = useQuery<{ keyword: string; count: number }[]>({
    queryKey: ["filings", "keywords"],
    queryFn: () =>
      apiGet<{ keyword: string; count: number }[]>("/api/filings/keywords").catch(
        () => []
      ),
    staleTime: 300_000,
  });

  // Client-side keyword filter
  const displayFilings = useMemo(() => {
    if (!filings) return [];
    if (hasKeywords) {
      return filings.filter((f) => f.keyword_count > 0);
    }
    return filings;
  }, [filings, hasKeywords]);

  // Compute max keyword count for bar widths
  const maxKeywordCount =
    keywords && keywords.length > 0
      ? Math.max(...keywords.map((k) => k.count))
      : 1;

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1
          className="text-2xl font-bold flex items-center gap-2"
          style={{ color: "var(--text-primary)" }}
        >
          <FileText size={24} style={{ color: "var(--accent-blue)" }} />
          SEC Filing Monitor
        </h1>
        <p
          className="text-sm mt-1"
          style={{ color: "var(--text-secondary)" }}
        >
          Real-time monitoring of SEC EDGAR filings
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

        {/* Filing Type Filter */}
        <select
          className="rounded-md border px-3 py-1.5 text-sm"
          style={{
            backgroundColor: "var(--bg-primary)",
            borderColor: "var(--border)",
            color: "var(--text-secondary)",
          }}
          value={formType}
          onChange={(e) => setFormType(e.target.value)}
        >
          <option value="">All Types</option>
          <option value="10-K">10-K (Annual)</option>
          <option value="10-Q">10-Q (Quarterly)</option>
          <option value="8-K">8-K (Current)</option>
          <option value="4">Form 4 (Insider)</option>
          <option value="SC 13D">SC 13D (Activist)</option>
          <option value="S-1">S-1 (IPO)</option>
          <option value="DEF 14A">DEF 14A (Proxy)</option>
        </select>

        {/* Ticker Filter */}
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

        {/* Has Keywords Toggle */}
        <button
          onClick={() => setHasKeywords(!hasKeywords)}
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors"
          style={{
            backgroundColor: hasKeywords
              ? "rgba(245, 158, 11, 0.15)"
              : "var(--bg-primary)",
            borderColor: hasKeywords
              ? "var(--accent-amber)"
              : "var(--border)",
            color: hasKeywords
              ? "var(--accent-amber)"
              : "var(--text-secondary)",
          }}
        >
          <Tag size={12} />
          Has Keywords
        </button>

        {/* Result count */}
        {filings && (
          <span
            className="ml-auto text-xs"
            style={{ color: "var(--text-muted)" }}
          >
            {displayFilings.length} filing{displayFilings.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Filings Feed (2/3 width) */}
        <div
          className="lg:col-span-2 rounded-lg border p-5"
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
              Recent Filings
            </h2>
          </div>

          {filingsLoading ? (
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
                Loading filings...
              </p>
            </div>
          ) : displayFilings.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <FileText
                size={48}
                style={{ color: "var(--text-muted)", opacity: 0.4 }}
              />
              <p
                className="text-sm mt-3"
                style={{ color: "var(--text-muted)" }}
              >
                No filings found. Add tickers to your watchlist to monitor
                EDGAR.
              </p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[600px] overflow-y-auto pr-1">
              {displayFilings.map((filing) => {
                const isExpanded = expandedFiling === filing.id;
                const meta =
                  formTypeMeta[filing.form_type] ?? { variant: "neutral" as const };
                return (
                  <div
                    key={filing.id}
                    className="rounded-md p-3 transition-colors"
                    style={{ backgroundColor: "var(--bg-hover)" }}
                  >
                    {/* Filing header */}
                    <div className="flex items-start gap-3">
                      <Badge variant={meta.variant}>
                        {filing.form_type}
                      </Badge>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span
                            className="text-sm font-semibold"
                            style={{ color: "var(--text-primary)" }}
                          >
                            {filing.symbol}
                          </span>
                          <span
                            className="text-xs"
                            style={{ color: "var(--text-muted)" }}
                          >
                            {formatDate(filing.filed_date)}
                          </span>
                          {filing.keyword_count > 0 && (
                            <Badge variant="warning">
                              {filing.keyword_count} keyword{filing.keyword_count !== 1 ? "s" : ""}
                            </Badge>
                          )}
                          {filing.ai_score != null && (
                            <Badge
                              variant={
                                filing.ai_score >= 7
                                  ? "danger"
                                  : filing.ai_score >= 4
                                    ? "warning"
                                    : "neutral"
                              }
                            >
                              AI: {filing.ai_score}/10
                            </Badge>
                          )}
                        </div>
                        <p
                          className="text-xs"
                          style={{ color: "var(--text-secondary)" }}
                        >
                          {filing.title}
                        </p>

                        {/* Keyword tags */}
                        {filing.keywords_found.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {filing.keywords_found.map((kw) => (
                              <span
                                key={kw}
                                className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium"
                                style={{
                                  backgroundColor: "rgba(245, 158, 11, 0.12)",
                                  color: "var(--accent-amber)",
                                }}
                              >
                                {kw}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-1 shrink-0">
                        {filing.url && (
                          <a
                            href={filing.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1 rounded hover:opacity-80"
                            style={{ color: "var(--accent-blue)" }}
                          >
                            <ExternalLink size={14} />
                          </a>
                        )}
                        {filing.ai_summary && (
                          <button
                            onClick={() =>
                              setExpandedFiling(
                                isExpanded ? null : filing.id
                              )
                            }
                            className="p-1 rounded hover:opacity-80"
                            style={{ color: "var(--text-muted)" }}
                          >
                            {isExpanded ? (
                              <ChevronUp size={14} />
                            ) : (
                              <ChevronDown size={14} />
                            )}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Collapsible AI summary */}
                    {isExpanded && filing.ai_summary && (
                      <div
                        className="mt-3 rounded-md p-3"
                        style={{
                          backgroundColor: "var(--bg-primary)",
                          borderLeft: "2px solid var(--accent-purple)",
                        }}
                      >
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <Sparkle
                            size={12}
                            style={{ color: "var(--accent-purple)" }}
                          />
                          <span
                            className="text-xs font-semibold uppercase tracking-wider"
                            style={{ color: "var(--accent-purple)" }}
                          >
                            AI Summary
                          </span>
                        </div>
                        <p
                          className="text-xs leading-relaxed"
                          style={{ color: "var(--text-secondary)" }}
                        >
                          {filing.ai_summary}
                        </p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Keyword Frequency (1/3 width) */}
        <div
          className="rounded-lg border p-5"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 size={16} style={{ color: "var(--accent-amber)" }} />
            <h2
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-primary)" }}
            >
              Distress Keywords
            </h2>
          </div>

          {!keywords || keywords.length === 0 ? (
            <p
              className="text-sm text-center py-8"
              style={{ color: "var(--text-muted)" }}
            >
              No keyword data available yet.
            </p>
          ) : (
            <div className="space-y-2.5">
              {keywords.slice(0, 15).map((kw) => (
                <div key={kw.keyword}>
                  <div className="flex items-center justify-between mb-0.5">
                    <span
                      className="text-xs font-medium"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {kw.keyword}
                    </span>
                    <span
                      className="text-xs font-bold"
                      style={{ color: "var(--accent-amber)" }}
                    >
                      {kw.count}
                    </span>
                  </div>
                  <div
                    className="h-1.5 rounded-full w-full"
                    style={{ backgroundColor: "var(--bg-hover)" }}
                  >
                    <div
                      className="h-1.5 rounded-full transition-all duration-500"
                      style={{
                        width: `${(kw.count / maxKeywordCount) * 100}%`,
                        backgroundColor: "var(--accent-amber)",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Inline Sparkle icon (lucide doesn't export "Sparkle") ──

function Sparkle({
  size = 16,
  style,
}: {
  size?: number;
  style?: React.CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
    >
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  );
}
