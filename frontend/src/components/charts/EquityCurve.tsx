"use client";

import { useEffect, useRef, useCallback } from "react";

interface EquityDataPoint {
  timestamp: string;
  value: number;
  pnl: number;
}

interface EquityCurveProps {
  data?: EquityDataPoint[];
  height?: number;
}

export default function EquityCurve({ data, height = 300 }: EquityCurveProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);

  const initChart = useCallback(async () => {
    if (!chartContainerRef.current) return;

    const { createChart, AreaSeries } = await import("lightweight-charts");

    // Dispose previous chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: "#6b7280",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(42, 48, 64, 0.3)" },
        horzLines: { color: "rgba(42, 48, 64, 0.3)" },
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color: "rgba(59, 130, 246, 0.4)",
          labelBackgroundColor: "#3b82f6",
        },
        horzLine: {
          color: "rgba(59, 130, 246, 0.4)",
          labelBackgroundColor: "#3b82f6",
        },
      },
      rightPriceScale: {
        borderColor: "#2a3040",
      },
      timeScale: {
        borderColor: "#2a3040",
        timeVisible: true,
      },
    });

    chartRef.current = chart;

    if (data && data.length > 0) {
      const startingValue = data[0].value;
      const latestValue = data[data.length - 1].value;
      const isPositive = latestValue >= startingValue;

      const lineColor = isPositive ? "#10b981" : "#ef4444";
      const topFill = isPositive
        ? "rgba(16, 185, 129, 0.2)"
        : "rgba(239, 68, 68, 0.2)";
      const bottomFill = "transparent";

      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor,
        topColor: topFill,
        bottomColor: bottomFill,
        lineWidth: 2,
        priceFormat: {
          type: "custom",
          formatter: (price: number) =>
            "$" + price.toLocaleString("en-US", { minimumFractionDigits: 0 }),
        },
        crosshairMarkerRadius: 4,
        crosshairMarkerBorderColor: lineColor,
        crosshairMarkerBackgroundColor: "#1a1f2e",
      });

      areaSeries.setData(
        data.map((d) => ({
          time: d.timestamp,
          value: d.value,
        }))
      );

      // Add baseline marker at starting value
      areaSeries.createPriceLine({
        price: startingValue,
        color: "rgba(107, 114, 128, 0.4)",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "Start",
      });

      chart.timeScale().fitContent();
    }

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    });

    resizeObserver.observe(chartContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, height]);

  useEffect(() => {
    let cleanup: (() => void) | undefined;

    initChart().then((c) => {
      cleanup = c;
    });

    return () => {
      cleanup?.();
    };
  }, [initChart]);

  if (!data || data.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-md"
        style={{
          height: `${height}px`,
          backgroundColor: "var(--bg-primary)",
          border: "1px dashed var(--border)",
        }}
      >
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Equity curve will render here
        </p>
      </div>
    );
  }

  return <div ref={chartContainerRef} style={{ width: "100%", height }} />;
}
