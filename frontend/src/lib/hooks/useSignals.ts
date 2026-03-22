"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type {
  Signal,
  SignalFilters,
  ScreenerPreset,
  ScreenerResponse,
} from "@/types";

function buildSignalQueryString(filters?: SignalFilters): string {
  if (!filters) return "";
  const params = new URLSearchParams();
  if (filters.ticker) params.set("ticker", filters.ticker);
  if (filters.signal_type) params.set("signal_type", filters.signal_type);
  if (filters.min_score !== undefined)
    params.set("min_score", String(filters.min_score));
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useSignals(filters?: SignalFilters) {
  return useQuery<Signal[]>({
    queryKey: ["signals", filters],
    queryFn: () => {
      const qs = buildSignalQueryString(filters);
      return apiGet<Signal[]>(`/api/signals${qs}`);
    },
    refetchInterval: 30_000,
  });
}

export function useScreenerPresets() {
  return useQuery<ScreenerPreset[]>({
    queryKey: ["screener", "presets"],
    queryFn: () => apiGet<ScreenerPreset[]>("/api/screener/presets"),
    staleTime: 5 * 60_000,
  });
}

export function useScreenerResults(preset: string) {
  return useQuery<ScreenerResponse>({
    queryKey: ["screener", "results", preset],
    queryFn: () =>
      apiGet<ScreenerResponse>(
        `/api/screener/presets/${encodeURIComponent(preset)}`
      ),
    enabled: !!preset,
    staleTime: 60_000,
  });
}

export function useScreenerOverview() {
  return useQuery<ScreenerResponse>({
    queryKey: ["screener", "overview"],
    queryFn: () => apiGet<ScreenerResponse>("/api/screener/overview"),
    staleTime: 60_000,
  });
}
