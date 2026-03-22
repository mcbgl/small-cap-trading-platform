"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { Filing, FilingFilters } from "@/types";

function buildFilingQueryString(filters?: FilingFilters): string {
  if (!filters) return "";
  const params = new URLSearchParams();
  if (filters.ticker) params.set("ticker", filters.ticker);
  if (filters.form_type) params.set("form_type", filters.form_type);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useFilings(filters?: FilingFilters) {
  return useQuery<Filing[]>({
    queryKey: ["filings", filters],
    queryFn: () => {
      const qs = buildFilingQueryString(filters);
      return apiGet<Filing[]>(`/api/filings${qs}`);
    },
    staleTime: 60_000,
  });
}

export function useFiling(id: number) {
  return useQuery<Filing>({
    queryKey: ["filings", id],
    queryFn: () => apiGet<Filing>(`/api/filings/${id}`),
    enabled: id > 0,
  });
}

export function useFilingKeywords() {
  return useQuery<string[]>({
    queryKey: ["filings", "keywords"],
    queryFn: () => apiGet<string[]>("/api/filings/keywords"),
    staleTime: 10 * 60_000,
  });
}
