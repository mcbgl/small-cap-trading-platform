"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type {
  SystemHealth,
  SystemConfig,
  AuditLogEntry,
  AuditLogFilters,
} from "@/types";

export function useSystemHealth() {
  return useQuery<SystemHealth>({
    queryKey: ["system", "health"],
    queryFn: () => apiGet<SystemHealth>("/api/system/health"),
    refetchInterval: 30_000,
  });
}

export function useSystemStatus() {
  return useQuery<SystemHealth>({
    queryKey: ["system", "status"],
    queryFn: () => apiGet<SystemHealth>("/api/system/status"),
    refetchInterval: 30_000,
  });
}

export function useSystemConfig() {
  return useQuery<SystemConfig>({
    queryKey: ["system", "config"],
    queryFn: () => apiGet<SystemConfig>("/api/system/config"),
    staleTime: 5 * 60_000,
  });
}

function buildAuditLogQueryString(filters?: AuditLogFilters): string {
  if (!filters) return "";
  const params = new URLSearchParams();
  if (filters.action) params.set("action", filters.action);
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined)
    params.set("offset", String(filters.offset));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useAuditLog(filters?: AuditLogFilters) {
  return useQuery<AuditLogEntry[]>({
    queryKey: ["system", "audit-log", filters],
    queryFn: () => {
      const qs = buildAuditLogQueryString(filters);
      return apiGet<AuditLogEntry[]>(`/api/system/audit-log${qs}`);
    },
    staleTime: 30_000,
  });
}
