"use client";

interface StatusDotProps {
  status: "connected" | "disconnected" | "degraded";
  size?: "sm" | "md" | "lg";
  pulse?: boolean;
  className?: string;
}

const sizeMap = {
  sm: "h-2 w-2",
  md: "h-3 w-3",
  lg: "h-4 w-4",
};

const colorMap = {
  connected: "var(--accent-green)",
  disconnected: "var(--accent-red)",
  degraded: "var(--accent-amber)",
};

export default function StatusDot({
  status,
  size = "md",
  pulse = true,
  className = "",
}: StatusDotProps) {
  const color = colorMap[status];

  return (
    <span className={`relative inline-flex ${className}`}>
      {pulse && status === "connected" && (
        <span
          className={`absolute inline-flex ${sizeMap[size]} rounded-full opacity-40`}
          style={{
            backgroundColor: color,
            animation: "ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite",
          }}
        />
      )}
      <span
        className={`relative inline-flex rounded-full ${sizeMap[size]}`}
        style={{ backgroundColor: color }}
      />
    </span>
  );
}
