"use client";

interface RiskGaugeProps {
  value: number;
  max: number;
  label: string;
  thresholds?: { warn: number; danger: number };
  size?: number;
}

export default function RiskGauge({
  value,
  max,
  label,
  thresholds = { warn: 60, danger: 80 },
  size = 140,
}: RiskGaugeProps) {
  const pct = Math.min((value / max) * 100, 100);
  const rotation = (pct / 100) * 180;

  // Determine color based on thresholds
  let color = "var(--accent-green)";
  if (pct >= thresholds.danger) {
    color = "var(--accent-red)";
  } else if (pct >= thresholds.warn) {
    color = "var(--accent-amber)";
  }

  const radius = size / 2;
  const strokeWidth = size * 0.08;
  const innerRadius = radius - strokeWidth;

  // SVG arc path helper
  function describeArc(
    cx: number,
    cy: number,
    r: number,
    startAngle: number,
    endAngle: number
  ): string {
    const startRad = ((startAngle - 180) * Math.PI) / 180;
    const endRad = ((endAngle - 180) * Math.PI) / 180;
    const x1 = cx + r * Math.cos(startRad);
    const y1 = cy + r * Math.sin(startRad);
    const x2 = cx + r * Math.cos(endRad);
    const y2 = cy + r * Math.sin(endRad);
    const largeArc = endAngle - startAngle > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
  }

  return (
    <div className="flex flex-col items-center">
      <div style={{ width: size, height: radius + 10, position: "relative" }}>
        <svg
          width={size}
          height={radius + 10}
          viewBox={`0 0 ${size} ${radius + 10}`}
        >
          {/* Background arc (full semicircle) */}
          <path
            d={describeArc(radius, radius, innerRadius, 0, 180)}
            fill="none"
            stroke="var(--bg-hover)"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
          />
          {/* Value arc */}
          {pct > 0 && (
            <path
              d={describeArc(
                radius,
                radius,
                innerRadius,
                0,
                Math.max(rotation, 1)
              )}
              fill="none"
              stroke={color}
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              style={{
                transition: "stroke-dashoffset 0.6s ease, stroke 0.3s ease",
              }}
            />
          )}
        </svg>
        {/* Center value text */}
        <div
          className="absolute flex flex-col items-center"
          style={{
            bottom: 4,
            left: "50%",
            transform: "translateX(-50%)",
          }}
        >
          <span
            className="font-bold font-mono"
            style={{
              fontSize: size * 0.17,
              color,
              lineHeight: 1,
            }}
          >
            {value.toFixed(1)}
          </span>
          <span
            className="text-xs"
            style={{ color: "var(--text-muted)", fontSize: size * 0.08 }}
          >
            / {max}
          </span>
        </div>
      </div>
      <span
        className="text-xs font-medium mt-1"
        style={{ color: "var(--text-secondary)" }}
      >
        {label}
      </span>
    </div>
  );
}
