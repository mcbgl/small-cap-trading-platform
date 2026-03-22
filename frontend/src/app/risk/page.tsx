"use client";

import {
  Shield,
  Target,
  TrendingDown,
  Zap,
  PieChart,
  OctagonX,
} from "lucide-react";

interface RiskCard {
  title: string;
  description: string;
  icon: React.ReactNode;
  status: string;
  statusColor: string;
}

const riskCards: RiskCard[] = [
  {
    title: "Position Limits",
    description: "Maximum position size relative to portfolio value",
    icon: <Target size={20} />,
    status: "Within Limits",
    statusColor: "var(--accent-green)",
  },
  {
    title: "Drawdown Status",
    description: "Current drawdown from peak portfolio value",
    icon: <TrendingDown size={20} />,
    status: "0.00%",
    statusColor: "var(--accent-green)",
  },
  {
    title: "Circuit Breakers",
    description: "Auto-halt trading on excessive losses",
    icon: <Zap size={20} />,
    status: "Armed",
    statusColor: "var(--accent-green)",
  },
  {
    title: "Concentration Risk",
    description: "Sector and single-stock exposure limits",
    icon: <PieChart size={20} />,
    status: "No Positions",
    statusColor: "var(--text-muted)",
  },
];

export default function RiskPage() {
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
            Monitor and control portfolio risk exposure
          </p>
        </div>
      </div>

      {/* Risk Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {riskCards.map((card) => (
          <div
            key={card.title}
            className="rounded-lg border p-5"
            style={{
              backgroundColor: "var(--bg-card)",
              borderColor: "var(--border)",
            }}
          >
            <div className="flex items-start justify-between mb-3">
              <div
                className="p-2 rounded-md"
                style={{ backgroundColor: "var(--bg-hover)" }}
              >
                <span style={{ color: "var(--accent-blue)" }}>{card.icon}</span>
              </div>
              <span
                className="text-xs font-semibold px-2 py-1 rounded"
                style={{
                  color: card.statusColor,
                  backgroundColor: "var(--bg-hover)",
                }}
              >
                {card.status}
              </span>
            </div>
            <h3
              className="text-sm font-semibold mb-1"
              style={{ color: "var(--text-primary)" }}
            >
              {card.title}
            </h3>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              {card.description}
            </p>
          </div>
        ))}
      </div>

      {/* Kill Switch */}
      <div
        className="rounded-lg border p-5"
        style={{
          backgroundColor: "rgba(239, 68, 68, 0.08)",
          borderColor: "rgba(239, 68, 68, 0.25)",
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <OctagonX size={24} style={{ color: "var(--accent-red)" }} />
            <div>
              <h3
                className="text-sm font-semibold"
                style={{ color: "var(--accent-red)" }}
              >
                Emergency Kill Switch
              </h3>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                Immediately cancel all open orders and flatten all positions
              </p>
            </div>
          </div>
          <button
            className="px-6 py-2.5 rounded-md text-sm font-bold uppercase tracking-wider transition-all hover:scale-105"
            style={{
              backgroundColor: "var(--accent-red)",
              color: "white",
            }}
          >
            Kill Switch
          </button>
        </div>
      </div>
    </div>
  );
}
