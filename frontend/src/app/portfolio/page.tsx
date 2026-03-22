"use client";

import { Wallet, ArrowUpDown, TrendingUp, TrendingDown } from "lucide-react";

export default function PortfolioPage() {
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
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
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
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Market Value
          </span>
          <p className="text-xl font-bold mt-1" style={{ color: "var(--text-primary)" }}>
            $0.00
          </p>
        </div>
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <span className="text-xs uppercase tracking-wider flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
            <TrendingUp size={12} />
            Total Gain/Loss
          </span>
          <p className="text-xl font-bold mt-1" style={{ color: "var(--text-secondary)" }}>
            $0.00
          </p>
        </div>
        <div
          className="rounded-lg border p-4"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <span className="text-xs uppercase tracking-wider flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
            <TrendingDown size={12} />
            Day Change
          </span>
          <p className="text-xl font-bold mt-1" style={{ color: "var(--text-secondary)" }}>
            $0.00
          </p>
        </div>
      </div>

      {/* Holdings Table */}
      <div
        className="rounded-lg border"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <div className="p-4 border-b" style={{ borderColor: "var(--border)" }}>
          <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-primary)" }}>
            Holdings
          </h2>
        </div>

        {/* Table Header */}
        <div
          className="grid grid-cols-7 gap-4 px-4 py-2 text-xs font-medium uppercase tracking-wider"
          style={{
            color: "var(--text-muted)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span>Symbol</span>
          <span>Shares</span>
          <span>Avg Cost</span>
          <span>Price</span>
          <span>Market Value</span>
          <span>P&L</span>
          <span>Day Change</span>
        </div>

        {/* Empty State */}
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Wallet
            size={48}
            style={{ color: "var(--text-muted)", opacity: 0.4 }}
          />
          <p className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>
            No positions yet. Start paper trading to build your portfolio.
          </p>
        </div>
      </div>
    </div>
  );
}
