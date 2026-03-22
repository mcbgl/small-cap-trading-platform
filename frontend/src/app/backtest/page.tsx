"use client";

import { BarChart3, Play, Settings } from "lucide-react";

export default function BacktestPage() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1
            className="text-2xl font-bold flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <BarChart3 size={24} style={{ color: "var(--accent-blue)" }} />
            Backtesting
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Configure and run backtests against historical data
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
            <Settings size={14} />
            Configure
          </button>
          <button
            className="flex items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium transition-colors"
            style={{
              backgroundColor: "var(--accent-blue)",
              color: "white",
            }}
          >
            <Play size={14} />
            Run Backtest
          </button>
        </div>
      </div>

      {/* Strategy Configuration */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-4"
          style={{ color: "var(--text-primary)" }}
        >
          Strategy Configuration
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>
              Strategy
            </label>
            <select
              className="w-full rounded-md border px-3 py-2 text-sm"
              style={{
                backgroundColor: "var(--bg-primary)",
                borderColor: "var(--border)",
                color: "var(--text-secondary)",
              }}
              defaultValue=""
            >
              <option value="">Select a strategy...</option>
              <option value="distressed">Distressed Assets</option>
              <option value="short-squeeze">Short Squeeze</option>
              <option value="insider">Insider Buying</option>
              <option value="ai">AI Opportunity</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>
              Date Range
            </label>
            <select
              className="w-full rounded-md border px-3 py-2 text-sm"
              style={{
                backgroundColor: "var(--bg-primary)",
                borderColor: "var(--border)",
                color: "var(--text-secondary)",
              }}
              defaultValue="1y"
            >
              <option value="3m">Last 3 Months</option>
              <option value="6m">Last 6 Months</option>
              <option value="1y">Last 1 Year</option>
              <option value="3y">Last 3 Years</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: "var(--text-muted)" }}>
              Initial Capital
            </label>
            <input
              type="text"
              defaultValue="$50,000"
              className="w-full rounded-md border px-3 py-2 text-sm"
              style={{
                backgroundColor: "var(--bg-primary)",
                borderColor: "var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>
        </div>
      </div>

      {/* Equity Curve Chart Area */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-4"
          style={{ color: "var(--text-primary)" }}
        >
          Equity Curve
        </h2>
        <div
          className="flex flex-col items-center justify-center rounded-md"
          style={{
            height: "400px",
            backgroundColor: "var(--bg-primary)",
            border: "1px dashed var(--border)",
          }}
        >
          <BarChart3
            size={48}
            style={{ color: "var(--text-muted)", opacity: 0.4 }}
          />
          <p className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>
            Configure a strategy and run a backtest to see the equity curve.
          </p>
        </div>
      </div>
    </div>
  );
}
