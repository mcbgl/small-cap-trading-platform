"use client";

import { Zap, AlertOctagon, AlertTriangle, Info } from "lucide-react";

interface SignalSection {
  title: string;
  priority: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
  borderColor: string;
  emptyMessage: string;
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
  },
  {
    title: "Warning Signals",
    priority: "warning",
    icon: <AlertTriangle size={16} />,
    color: "var(--accent-amber)",
    bgColor: "rgba(245, 158, 11, 0.08)",
    borderColor: "rgba(245, 158, 11, 0.25)",
    emptyMessage: "No warnings at this time.",
  },
  {
    title: "Informational",
    priority: "info",
    icon: <Info size={16} />,
    color: "var(--accent-blue)",
    bgColor: "rgba(59, 130, 246, 0.08)",
    borderColor: "rgba(59, 130, 246, 0.25)",
    emptyMessage: "No informational signals. Connect data feeds to receive updates.",
  },
];

export default function SignalsPage() {
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
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Real-time trading signals organized by priority
        </p>
      </div>

      {/* Signal Sections */}
      {sections.map((section) => (
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
              0
            </span>
          </div>
          <div className="flex items-center justify-center py-8">
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              {section.emptyMessage}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
