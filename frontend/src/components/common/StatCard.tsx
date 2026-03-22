"use client";

import type { ReactNode } from "react";

interface StatCardProps {
  title: string;
  value: string;
  change?: string;
  changePositive?: boolean;
  icon?: ReactNode;
  className?: string;
}

export default function StatCard({
  title,
  value,
  change,
  changePositive,
  icon,
  className = "",
}: StatCardProps) {
  return (
    <div
      className={`rounded-lg border p-4 ${className}`}
      style={{
        backgroundColor: "var(--bg-card)",
        borderColor: "var(--border)",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <span
          className="text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          {title}
        </span>
        {icon && (
          <span style={{ color: "var(--text-muted)" }}>{icon}</span>
        )}
      </div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          {value}
        </span>
        {change && (
          <span
            className="text-sm font-medium mb-0.5"
            style={{
              color:
                changePositive === undefined
                  ? "var(--text-secondary)"
                  : changePositive
                    ? "var(--accent-green)"
                    : "var(--accent-red)",
            }}
          >
            {change}
          </span>
        )}
      </div>
    </div>
  );
}
