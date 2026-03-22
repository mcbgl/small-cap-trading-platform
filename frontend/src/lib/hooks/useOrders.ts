"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import type { Order, OrderCreate, OrderFilters } from "@/types";

function buildOrderQueryString(filters?: OrderFilters): string {
  if (!filters) return "";
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.ticker) params.set("ticker", filters.ticker);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function useOrders(filters?: OrderFilters) {
  return useQuery<Order[]>({
    queryKey: ["orders", filters],
    queryFn: () => {
      const qs = buildOrderQueryString(filters);
      return apiGet<Order[]>(`/api/orders${qs}`);
    },
    refetchInterval: 15_000,
  });
}

export function useCreateOrder() {
  const queryClient = useQueryClient();

  return useMutation<Order, Error, OrderCreate>({
    mutationFn: (order: OrderCreate) =>
      apiPost<Order>("/api/orders", order),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });
}

export function useCancelOrder() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, number>({
    mutationFn: (orderId: number) =>
      apiDelete<void>(`/api/orders/${orderId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });
}
