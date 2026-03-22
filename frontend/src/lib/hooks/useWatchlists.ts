"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import type { Watchlist, WatchlistItem } from "@/types";

export function useWatchlists() {
  return useQuery<Watchlist[]>({
    queryKey: ["watchlists"],
    queryFn: () => apiGet<Watchlist[]>("/api/watchlists"),
    staleTime: 30_000,
  });
}

export function useWatchlist(id: number) {
  return useQuery<Watchlist>({
    queryKey: ["watchlists", id],
    queryFn: () => apiGet<Watchlist>(`/api/watchlists/${id}`),
    enabled: id > 0,
  });
}

export function useCreateWatchlist() {
  const queryClient = useQueryClient();

  return useMutation<Watchlist, Error, { name: string }>({
    mutationFn: (data: { name: string }) =>
      apiPost<Watchlist>("/api/watchlists", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });
}

export function useAddToWatchlist() {
  const queryClient = useQueryClient();

  return useMutation<
    WatchlistItem,
    Error,
    { watchlistId: number; symbol: string }
  >({
    mutationFn: ({ watchlistId, symbol }) =>
      apiPost<WatchlistItem>(`/api/watchlists/${watchlistId}/items`, {
        symbol,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["watchlists", variables.watchlistId],
      });
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });
}

export function useRemoveFromWatchlist() {
  const queryClient = useQueryClient();

  return useMutation<
    void,
    Error,
    { watchlistId: number; itemId: number }
  >({
    mutationFn: ({ watchlistId, itemId }) =>
      apiDelete<void>(`/api/watchlists/${watchlistId}/items/${itemId}`),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["watchlists", variables.watchlistId],
      });
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });
}
