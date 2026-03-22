"use client";

import {
  Search,
  AlertTriangle,
  TrendingUp,
  UserCheck,
  Sparkles,
} from "lucide-react";

interface PresetButton {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  color: string;
}

const presets: PresetButton[] = [
  {
    id: "distressed",
    title: "Distressed Assets",
    description: "Find undervalued stocks trading below book value with high debt ratios",
    icon: <AlertTriangle size={24} />,
    color: "var(--accent-red)",
  },
  {
    id: "short-squeeze",
    title: "Short Squeeze",
    description: "High short interest, rising volume, and positive momentum signals",
    icon: <TrendingUp size={24} />,
    color: "var(--accent-amber)",
  },
  {
    id: "insider-buying",
    title: "Insider Buying",
    description: "Recent insider purchases from executives and board members",
    icon: <UserCheck size={24} />,
    color: "var(--accent-green)",
  },
  {
    id: "ai-opportunity",
    title: "AI Opportunity",
    description: "AI-identified opportunities using multi-factor pattern recognition",
    icon: <Sparkles size={24} />,
    color: "var(--accent-purple)",
  },
];

export default function ScreenerPage() {
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
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Scan the market with AI-powered preset strategies
        </p>
      </div>

      {/* Preset Strategy Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {presets.map((preset) => (
          <button
            key={preset.id}
            className="text-left rounded-lg border p-5 transition-all hover:scale-[1.02]"
            style={{
              backgroundColor: "var(--bg-card)",
              borderColor: "var(--border)",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor = preset.color;
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
            }}
          >
            <div className="mb-3" style={{ color: preset.color }}>
              {preset.icon}
            </div>
            <h3
              className="text-sm font-semibold mb-1"
              style={{ color: "var(--text-primary)" }}
            >
              {preset.title}
            </h3>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
              {preset.description}
            </p>
          </button>
        ))}
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
        </div>
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Search
            size={48}
            style={{ color: "var(--text-muted)", opacity: 0.4 }}
          />
          <p className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>
            Select a preset strategy above or create a custom screen to find opportunities.
          </p>
        </div>
      </div>
    </div>
  );
}
