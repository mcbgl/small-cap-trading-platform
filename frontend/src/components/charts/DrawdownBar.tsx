"use client";

interface DrawdownBarProps {
  label: string;
  current: number;
  limit: number;
  unit?: string;
}

export default function DrawdownBar({
  label,
  current,
  limit,
  unit = "%",
}: DrawdownBarProps) {
  const pct = limit > 0 ? Math.min((Math.abs(current) / limit) * 100, 100) : 0;

  let barColor = "var(--accent-green)";
  if (pct >= 80) {
    barColor = "var(--accent-red)";
  } else if (pct >= 60) {
    barColor = "var(--accent-amber)";
  }

  const formatValue = (v: number) => {
    if (unit === "$") {
      return "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    }
    return Math.abs(v).toFixed(2) + unit;
  };

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
          {label}
        </span>
        <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
          {formatValue(current)} / {formatValue(limit)}
        </span>
      </div>
      <div className="relative">
        {/* Track */}
        <div
          className="h-2.5 rounded-full w-full"
          style={{ backgroundColor: "var(--bg-hover)" }}
        >
          {/* Fill */}
          <div
            className="h-2.5 rounded-full transition-all duration-500"
            style={{
              width: `${Math.max(pct, 0)}%`,
              backgroundColor: barColor,
              minWidth: pct > 0 ? "4px" : "0",
            }}
          />
        </div>
        {/* Threshold marker at limit */}
        <div
          className="absolute top-0 h-2.5"
          style={{
            left: "100%",
            transform: "translateX(-2px)",
            width: "2px",
            backgroundColor: "var(--accent-red)",
            borderRadius: "1px",
            opacity: 0.6,
          }}
        />
      </div>
    </div>
  );
}
