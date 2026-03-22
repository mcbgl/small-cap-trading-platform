"use client";

import { useState } from "react";
import {
  BarChart3,
  Play,
  Calendar,
  DollarSign,
  TrendingUp,
  Activity,
  Target,
  Percent,
  Clock,
  Table2,
} from "lucide-react";
import Badge from "@/components/common/Badge";

// ── Placeholder stat values ──

const STATS = [
  { label: "Total Return", value: "\u2014", icon: <TrendingUp size={14} /> },
  { label: "Sharpe Ratio", value: "\u2014", icon: <Activity size={14} /> },
  { label: "Max Drawdown", value: "\u2014", icon: <Target size={14} /> },
  { label: "Win Rate", value: "\u2014", icon: <Percent size={14} /> },
];

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export default function BacktestPage() {
  const [strategy, setStrategy] = useState("");
  const [startDate, setStartDate] = useState("2025-01-01");
  const [endDate, setEndDate] = useState("2026-03-21");
  const [capital, setCapital] = useState("100000");
  const [benchmark, setBenchmark] = useState("russell2000");

  const inputStyle = {
    backgroundColor: "var(--bg-primary)",
    borderColor: "var(--border)",
    color: "var(--text-primary)",
  };

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
            Configure and run strategy backtests against historical data
          </p>
        </div>
      </div>

      {/* ── Configuration Panel ── */}
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

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {/* Strategy selector */}
          <div>
            <label
              className="flex items-center gap-1 text-xs font-medium mb-1.5"
              style={{ color: "var(--text-muted)" }}
            >
              <Activity size={12} />
              Strategy
            </label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="w-full rounded-md border px-3 py-2 text-sm"
              style={inputStyle}
            >
              <option value="">Select a strategy...</option>
              <option value="short-squeeze">Short Squeeze</option>
              <option value="distressed-value">Distressed Value</option>
              <option value="insider-following">Insider Following</option>
              <option value="multi-signal">Multi-Signal Composite</option>
            </select>
          </div>

          {/* Start date */}
          <div>
            <label
              className="flex items-center gap-1 text-xs font-medium mb-1.5"
              style={{ color: "var(--text-muted)" }}
            >
              <Calendar size={12} />
              Start Date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full rounded-md border px-3 py-2 text-sm"
              style={inputStyle}
            />
          </div>

          {/* End date */}
          <div>
            <label
              className="flex items-center gap-1 text-xs font-medium mb-1.5"
              style={{ color: "var(--text-muted)" }}
            >
              <Calendar size={12} />
              End Date
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full rounded-md border px-3 py-2 text-sm"
              style={inputStyle}
            />
          </div>

          {/* Initial capital */}
          <div>
            <label
              className="flex items-center gap-1 text-xs font-medium mb-1.5"
              style={{ color: "var(--text-muted)" }}
            >
              <DollarSign size={12} />
              Initial Capital
            </label>
            <div className="relative">
              <span
                className="absolute left-3 top-1/2 -translate-y-1/2 text-sm"
                style={{ color: "var(--text-muted)" }}
              >
                $
              </span>
              <input
                type="text"
                value={capital}
                onChange={(e) => setCapital(e.target.value.replace(/[^0-9]/g, ""))}
                className="w-full rounded-md border pl-7 pr-3 py-2 text-sm"
                style={inputStyle}
              />
            </div>
          </div>

          {/* Benchmark */}
          <div>
            <label
              className="flex items-center gap-1 text-xs font-medium mb-1.5"
              style={{ color: "var(--text-muted)" }}
            >
              <TrendingUp size={12} />
              Benchmark
            </label>
            <select
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
              className="w-full rounded-md border px-3 py-2 text-sm"
              style={inputStyle}
            >
              <option value="russell2000">Russell 2000</option>
              <option value="sp500">S&P 500</option>
            </select>
          </div>
        </div>

        {/* Run button */}
        <div className="mt-5 flex items-center gap-3">
          <div className="relative group">
            <button
              disabled
              className="flex items-center gap-1.5 rounded-md px-5 py-2 text-sm font-medium transition-colors opacity-50 cursor-not-allowed"
              style={{
                backgroundColor: "var(--accent-blue)",
                color: "white",
              }}
            >
              <Play size={14} />
              Run Backtest
            </button>
            {/* Tooltip */}
            <div
              className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-1.5 rounded text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
              style={{
                backgroundColor: "var(--bg-hover)",
                color: "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
            >
              Coming soon -- backtest engine in development
            </div>
          </div>
          <Badge variant="warning">Coming Soon</Badge>
        </div>
      </div>

      {/* ── Equity Curve Chart Area ── */}
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
            style={{ color: "var(--text-muted)", opacity: 0.3 }}
          />
          <p className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>
            Equity curve will render here after running a backtest
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)", opacity: 0.6 }}>
            Strategy vs {benchmark === "russell2000" ? "Russell 2000" : "S&P 500"} benchmark
          </p>
        </div>
      </div>

      {/* ── Stats Row ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {STATS.map((stat) => (
          <div
            key={stat.label}
            className="rounded-lg border p-4"
            style={{
              backgroundColor: "var(--bg-card)",
              borderColor: "var(--border)",
            }}
          >
            <div className="flex items-center gap-1.5 mb-2">
              <span style={{ color: "var(--text-muted)" }}>{stat.icon}</span>
              <span
                className="text-xs font-medium uppercase tracking-wider"
                style={{ color: "var(--text-muted)" }}
              >
                {stat.label}
              </span>
            </div>
            <span
              className="text-xl font-bold font-mono"
              style={{ color: "var(--text-secondary)" }}
            >
              {stat.value}
            </span>
          </div>
        ))}
      </div>

      {/* ── Monthly Returns Heatmap ── */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-wider mb-4 flex items-center gap-2"
          style={{ color: "var(--text-primary)" }}
        >
          <Clock size={14} style={{ color: "var(--accent-blue)" }} />
          Monthly Returns Heatmap
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th
                  className="text-left py-2 pr-3 font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-muted)" }}
                >
                  Year
                </th>
                {MONTHS.map((m) => (
                  <th
                    key={m}
                    className="text-center py-2 px-1.5 font-medium uppercase tracking-wider"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {m}
                  </th>
                ))}
                <th
                  className="text-center py-2 px-2 font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-muted)" }}
                >
                  YTD
                </th>
              </tr>
            </thead>
            <tbody>
              {[2025, 2026].map((year) => (
                <tr
                  key={year}
                  className="border-t"
                  style={{ borderColor: "var(--border)" }}
                >
                  <td
                    className="py-2.5 pr-3 font-mono font-medium"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {year}
                  </td>
                  {MONTHS.map((m) => (
                    <td
                      key={m}
                      className="text-center py-2.5 px-1.5"
                    >
                      <div
                        className="rounded px-1.5 py-1 mx-auto"
                        style={{
                          backgroundColor: "var(--bg-hover)",
                          color: "var(--text-muted)",
                          width: "fit-content",
                          minWidth: "36px",
                        }}
                      >
                        --
                      </div>
                    </td>
                  ))}
                  <td className="text-center py-2.5 px-2">
                    <div
                      className="rounded px-1.5 py-1 mx-auto font-medium"
                      style={{
                        backgroundColor: "var(--bg-hover)",
                        color: "var(--text-muted)",
                        width: "fit-content",
                        minWidth: "36px",
                      }}
                    >
                      --
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Trade Log ── */}
      <div
        className="rounded-lg border"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <div
          className="flex items-center gap-2 p-4 border-b"
          style={{ borderColor: "var(--border)" }}
        >
          <Table2 size={14} style={{ color: "var(--accent-blue)" }} />
          <h2
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-primary)" }}
          >
            Trade Log
          </h2>
        </div>

        {/* Table header */}
        <div
          className="grid grid-cols-8 gap-2 px-4 py-2.5 text-xs font-medium uppercase tracking-wider"
          style={{
            color: "var(--text-muted)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span>Date</span>
          <span>Symbol</span>
          <span>Side</span>
          <span>Qty</span>
          <span>Entry</span>
          <span>Exit</span>
          <span>P&L</span>
          <span>Signal</span>
        </div>

        {/* Empty state */}
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <BarChart3
            size={40}
            style={{ color: "var(--text-muted)", opacity: 0.3 }}
          />
          <p className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>
            Trade log will populate after running a backtest
          </p>
        </div>
      </div>
    </div>
  );
}
