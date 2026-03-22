"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type {
  PortfolioSummary,
  Position,
  PortfolioHistoryPoint,
  PerformanceMetrics,
} from "@/types";

export function usePortfolioSummary() {
  return useQuery<PortfolioSummary>({
    queryKey: ["portfolio", "summary"],
    queryFn: () => apiGet<PortfolioSummary>("/api/portfolio/summary"),
    refetchInterval: 30_000,
  });
}

export function usePositions() {
  return useQuery<Position[]>({
    queryKey: ["portfolio", "positions"],
    queryFn: () => apiGet<Position[]>("/api/portfolio/positions"),
    refetchInterval: 30_000,
  });
}

export function usePortfolioHistory(period: string = "1M") {
  return useQuery<PortfolioHistoryPoint[]>({
    queryKey: ["portfolio", "history", period],
    queryFn: () =>
      apiGet<PortfolioHistoryPoint[]>(
        `/api/portfolio/history?period=${encodeURIComponent(period)}`
      ),
    staleTime: 60_000,
  });
}

export function usePerformance() {
  return useQuery<PerformanceMetrics>({
    queryKey: ["portfolio", "performance"],
    queryFn: () => apiGet<PerformanceMetrics>("/api/portfolio/performance"),
    refetchInterval: 60_000,
  });
}
