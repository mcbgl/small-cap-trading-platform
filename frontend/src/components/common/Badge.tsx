"use client";

import type { ReactNode } from "react";

type BadgeVariant = "success" | "danger" | "warning" | "info" | "neutral";

interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, { bg: string; text: string; border: string }> = {
  success: {
    bg: "rgba(16, 185, 129, 0.15)",
    text: "var(--accent-green)",
    border: "rgba(16, 185, 129, 0.3)",
  },
  danger: {
    bg: "rgba(239, 68, 68, 0.15)",
    text: "var(--accent-red)",
    border: "rgba(239, 68, 68, 0.3)",
  },
  warning: {
    bg: "rgba(245, 158, 11, 0.15)",
    text: "var(--accent-amber)",
    border: "rgba(245, 158, 11, 0.3)",
  },
  info: {
    bg: "rgba(59, 130, 246, 0.15)",
    text: "var(--accent-blue)",
    border: "rgba(59, 130, 246, 0.3)",
  },
  neutral: {
    bg: "rgba(107, 114, 128, 0.15)",
    text: "var(--text-secondary)",
    border: "rgba(107, 114, 128, 0.3)",
  },
};

export default function Badge({
  variant = "neutral",
  children,
  className = "",
}: BadgeProps) {
  const style = variantStyles[variant];

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border ${className}`}
      style={{
        backgroundColor: style.bg,
        color: style.text,
        borderColor: style.border,
      }}
    >
      {children}
    </span>
  );
}
