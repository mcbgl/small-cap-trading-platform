"use client";

import { useEffect, useRef, useCallback } from "react";

interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface PriceChartProps {
  symbol: string;
  data?: CandleData[];
  height?: number;
}

export default function PriceChart({
  symbol,
  data,
  height = 400,
}: PriceChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);

  const initChart = useCallback(async () => {
    if (!chartContainerRef.current) return;

    const { createChart, CandlestickSeries, HistogramSeries } = await import(
      "lightweight-charts"
    );

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
        vertLines: { color: "rgba(42, 48, 64, 0.5)" },
        horzLines: { color: "rgba(42, 48, 64, 0.5)" },
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
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: "#2a3040",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

    if (data && data.length > 0) {
      const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981",
        downColor: "#ef4444",
        borderUpColor: "#10b981",
        borderDownColor: "#ef4444",
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
      });

      candlestickSeries.setData(
        data.map((d) => ({
          time: d.time,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        }))
      );

      // Volume histogram
      const volumeData = data.filter((d) => d.volume !== undefined);
      if (volumeData.length > 0) {
        const volumeSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "volume",
        });

        chart.priceScale("volume").applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });

        volumeSeries.setData(
          volumeData.map((d) => ({
            time: d.time,
            value: d.volume!,
            color:
              d.close >= d.open
                ? "rgba(16, 185, 129, 0.3)"
                : "rgba(239, 68, 68, 0.3)",
          }))
        );
      }

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
          {symbol ? `Loading chart data for ${symbol}...` : "Loading chart data..."}
        </p>
      </div>
    );
  }

  return <div ref={chartContainerRef} style={{ width: "100%", height }} />;
}
