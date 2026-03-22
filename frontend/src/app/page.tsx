"use client";

import {
  DollarSign,
  TrendingUp,
  Banknote,
  BarChart3,
  Activity,
  AlertTriangle,
} from "lucide-react";
import StatCard from "@/components/common/StatCard";

export default function HomePage() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1
          className="text-2xl font-bold"
          style={{ color: "var(--text-primary)" }}
        >
          Command Center
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Real-time overview of your trading activity
        </p>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Value"
          value="$50,000"
          icon={<DollarSign size={16} />}
        />
        <StatCard
          title="Daily P&L"
          value="+$0.00"
          change="+0.00%"
          changePositive={true}
          icon={<TrendingUp size={16} />}
        />
        <StatCard
          title="Cash Available"
          value="$50,000"
          icon={<Banknote size={16} />}
        />
        <StatCard
          title="Open Positions"
          value="0"
          icon={<BarChart3 size={16} />}
        />
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* AI Insights Feed */}
        <div
          className="rounded-lg border p-5"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Activity size={16} style={{ color: "var(--accent-purple)" }} />
            <h2
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-primary)" }}
            >
              AI Insights Feed
            </h2>
          </div>
          <div
            className="flex flex-col items-center justify-center py-12 text-center"
          >
            <Activity
              size={40}
              style={{ color: "var(--text-muted)", opacity: 0.5 }}
            />
            <p
              className="text-sm mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              No signals yet. Connect data feeds to begin monitoring.
            </p>
          </div>
        </div>

        {/* Active Alerts */}
        <div
          className="rounded-lg border p-5"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={16} style={{ color: "var(--accent-amber)" }} />
            <h2
              className="text-sm font-semibold uppercase tracking-wider"
              style={{ color: "var(--text-primary)" }}
            >
              Active Alerts
            </h2>
          </div>
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <AlertTriangle
              size={40}
              style={{ color: "var(--text-muted)", opacity: 0.5 }}
            />
            <p
              className="text-sm mt-3"
              style={{ color: "var(--text-muted)" }}
            >
              No active alerts
            </p>
          </div>
        </div>
      </div>

      {/* Market Context Strip */}
      <div
        className="rounded-lg border p-4"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border)",
        }}
      >
        <h2
          className="text-xs font-semibold uppercase tracking-wider mb-3"
          style={{ color: "var(--text-muted)" }}
        >
          Market Context
        </h2>
        <div className="grid grid-cols-3 gap-4">
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              S&P 500
            </span>
            <div className="text-right">
              <span
                className="text-sm font-medium"
                style={{ color: "var(--text-primary)" }}
              >
                ---
              </span>
              <span
                className="text-xs ml-2"
                style={{ color: "var(--text-muted)" }}
              >
                ---%
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Russell 2000
            </span>
            <div className="text-right">
              <span
                className="text-sm font-medium"
                style={{ color: "var(--text-primary)" }}
              >
                ---
              </span>
              <span
                className="text-xs ml-2"
                style={{ color: "var(--text-muted)" }}
              >
                ---%
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              VIX
            </span>
            <div className="text-right">
              <span
                className="text-sm font-medium"
                style={{ color: "var(--text-primary)" }}
              >
                ---
              </span>
              <span
                className="text-xs ml-2"
                style={{ color: "var(--text-muted)" }}
              >
                ---%
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
