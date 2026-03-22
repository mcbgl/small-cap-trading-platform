"use client";

import { FileText, Filter, Calendar, Tag } from "lucide-react";

export default function FilingsPage() {
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
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
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
        <div className="flex items-center gap-1.5" style={{ color: "var(--text-muted)" }}>
          <Filter size={14} />
          <span className="text-xs font-medium uppercase tracking-wider">Filters</span>
        </div>

        {/* Filing Type Filter */}
        <select
          className="rounded-md border px-3 py-1.5 text-sm"
          style={{
            backgroundColor: "var(--bg-primary)",
            borderColor: "var(--border)",
            color: "var(--text-secondary)",
          }}
          defaultValue=""
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
          <Tag size={12} style={{ color: "var(--text-muted)" }} />
          <input
            type="text"
            placeholder="Ticker..."
            className="bg-transparent border-none outline-none text-sm w-20"
            style={{ color: "var(--text-primary)" }}
          />
        </div>

        {/* Date Range */}
        <div
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5"
          style={{
            backgroundColor: "var(--bg-primary)",
            borderColor: "var(--border)",
          }}
        >
          <Calendar size={12} style={{ color: "var(--text-muted)" }} />
          <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Last 7 days
          </span>
        </div>
      </div>

      {/* Filings Feed */}
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
            Recent Filings
          </h2>
        </div>
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <FileText
            size={48}
            style={{ color: "var(--text-muted)", opacity: 0.4 }}
          />
          <p className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>
            Connect EDGAR feed to monitor real-time SEC filings.
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Filings will appear here as they are published.
          </p>
        </div>
      </div>
    </div>
  );
}
