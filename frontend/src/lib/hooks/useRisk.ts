"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";
import type { RiskStatus, CircuitBreaker, RiskLimits } from "@/types";

export function useRiskStatus() {
  return useQuery<RiskStatus>({
    queryKey: ["risk", "status"],
    queryFn: () => apiGet<RiskStatus>("/api/risk/status"),
    refetchInterval: 30_000,
  });
}

export function useCircuitBreakers() {
  return useQuery<CircuitBreaker[]>({
    queryKey: ["risk", "circuit-breakers"],
    queryFn: () => apiGet<CircuitBreaker[]>("/api/risk/circuit-breakers"),
    refetchInterval: 15_000,
  });
}

export function useRiskLimits() {
  return useQuery<RiskLimits>({
    queryKey: ["risk", "limits"],
    queryFn: () => apiGet<RiskLimits>("/api/risk/limits"),
    staleTime: 60_000,
  });
}

export function useRiskCompliance() {
  return useQuery<RiskStatus["compliance"]>({
    queryKey: ["risk", "compliance"],
    queryFn: async () => {
      const status = await apiGet<RiskStatus>("/api/risk/compliance");
      return status.compliance;
    },
    refetchInterval: 60_000,
  });
}

export function useKillSwitch() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, { level: string }>({
    mutationFn: ({ level }: { level: string }) =>
      apiPost<void>(`/api/risk/kill-switch/${encodeURIComponent(level)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk"] });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
  });
}
