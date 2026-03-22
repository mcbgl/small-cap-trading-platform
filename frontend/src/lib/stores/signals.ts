"use client";

import { create } from "zustand";
import { tradingWS } from "@/lib/ws";
import { apiGet } from "@/lib/api";
import type { Signal, SignalFilters } from "@/types";

interface SignalsState {
  signals: Signal[];
  loading: boolean;
  lastFetch: string | null;

  // Actions
  fetchSignals: (filters?: SignalFilters) => Promise<void>;
  addSignal: (signal: Signal) => void;
  clearSignals: () => void;
  initWebSocket: () => () => void;
}

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

export const useSignalsStore = create<SignalsState>((set, get) => ({
  signals: [],
  loading: false,
  lastFetch: null,

  fetchSignals: async (filters?: SignalFilters) => {
    set({ loading: true });
    try {
      const qs = buildSignalQueryString(filters);
      const signals = await apiGet<Signal[]>(`/api/signals${qs}`);
      set({ signals, lastFetch: new Date().toISOString(), loading: false });
    } catch (error) {
      console.error("[SignalsStore] Failed to fetch signals:", error);
      set({ loading: false });
    }
  },

  addSignal: (signal: Signal) => {
    set((state) => ({
      signals: [signal, ...state.signals],
    }));
  },

  clearSignals: () => {
    set({ signals: [], lastFetch: null });
  },

  initWebSocket: () => {
    const handler = (data: unknown) => {
      const signal = data as Signal;
      if (signal && signal.id) {
        get().addSignal(signal);
      }
    };

    tradingWS.subscribe("signals", handler);

    return () => {
      tradingWS.unsubscribe("signals", handler);
    };
  },
}));
