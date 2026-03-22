"use client";

import type { InsightCard as InsightCardType } from "@/types";
import Badge from "@/components/common/Badge";
import { Zap, ThumbsUp, ThumbsDown } from "lucide-react";

interface InsightCardProps {
  insight: InsightCardType;
  className?: string;
}

function getScoreVariant(score: number) {
  if (score >= 70) return "success" as const;
  if (score >= 40) return "warning" as const;
  return "danger" as const;
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.7) return "var(--accent-green)";
  if (confidence >= 0.4) return "var(--accent-amber)";
  return "var(--accent-red)";
}

export default function InsightCard({ insight, className = "" }: InsightCardProps) {
  const scoreVariant = getScoreVariant(insight.score);
  const confidenceColor = getConfidenceColor(insight.confidence);
  const confidencePercent = Math.round(insight.confidence * 100);

  return (
    <div
      className={`rounded-lg border p-4 ${className}`}
      style={{
        backgroundColor: "var(--bg-card)",
        borderColor: "var(--border)",
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Zap size={16} style={{ color: "var(--accent-amber)" }} />
          <span className="font-semibold text-sm" style={{ color: "var(--text-primary)" }}>
            {insight.symbol}
          </span>
          <Badge variant={scoreVariant}>{insight.score}/100</Badge>
        </div>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {new Date(insight.timestamp).toLocaleTimeString()}
        </span>
      </div>

      {/* Title & Summary */}
      <h3 className="text-sm font-medium mb-1" style={{ color: "var(--text-primary)" }}>
        {insight.title}
      </h3>
      <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
        {insight.summary}
      </p>

      {/* Pros & Cons */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <div className="flex items-center gap-1 mb-1">
            <ThumbsUp size={12} style={{ color: "var(--accent-green)" }} />
            <span
              className="text-xs font-medium"
              style={{ color: "var(--accent-green)" }}
            >
              Pros
            </span>
          </div>
          <ul className="space-y-0.5">
            {insight.pros.map((pro, i) => (
              <li
                key={i}
                className="text-xs"
                style={{ color: "var(--text-secondary)" }}
              >
                + {pro}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="flex items-center gap-1 mb-1">
            <ThumbsDown size={12} style={{ color: "var(--accent-red)" }} />
            <span
              className="text-xs font-medium"
              style={{ color: "var(--accent-red)" }}
            >
              Cons
            </span>
          </div>
          <ul className="space-y-0.5">
            {insight.cons.map((con, i) => (
              <li
                key={i}
                className="text-xs"
                style={{ color: "var(--text-secondary)" }}
              >
                - {con}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Confidence Bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            Confidence
          </span>
          <span className="text-xs font-medium" style={{ color: confidenceColor }}>
            {confidencePercent}%
          </span>
        </div>
        <div
          className="h-1.5 rounded-full w-full"
          style={{ backgroundColor: "var(--bg-hover)" }}
        >
          <div
            className="h-1.5 rounded-full transition-all duration-500"
            style={{
              width: `${confidencePercent}%`,
              backgroundColor: confidenceColor,
            }}
          />
        </div>
      </div>

      {/* Model Attribution */}
      <div className="flex items-center justify-between">
        <Badge variant="neutral">{insight.model}</Badge>
        <Badge variant="info">{insight.signalType.replace("_", " ")}</Badge>
      </div>
    </div>
  );
}
