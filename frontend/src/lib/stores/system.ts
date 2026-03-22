"use client";

import { create } from "zustand";
import { tradingWS } from "@/lib/ws";
import { apiGet } from "@/lib/api";
import type { SystemHealth, RiskStatus } from "@/types";

interface SystemState {
  health: SystemHealth | null;
  riskStatus: RiskStatus | null;
  connected: boolean;
  paperMode: boolean;

  // Actions
  fetchHealth: () => Promise<void>;
  fetchRiskStatus: () => Promise<void>;
  setConnected: (connected: boolean) => void;
  setPaperMode: (paperMode: boolean) => void;
  initWebSocket: () => () => void;
}

export const useSystemStore = create<SystemState>((set) => ({
  health: null,
  riskStatus: null,
  connected: false,
  paperMode: true,

  fetchHealth: async () => {
    try {
      const health = await apiGet<SystemHealth>("/api/system/health");
      set({ health });
    } catch (error) {
      console.error("[SystemStore] Failed to fetch health:", error);
      set({
        health: {
          status: "down",
          components: [],
        },
      });
    }
  },

  fetchRiskStatus: async () => {
    try {
      const riskStatus = await apiGet<RiskStatus>("/api/risk/status");
      set({ riskStatus });
    } catch (error) {
      console.error("[SystemStore] Failed to fetch risk status:", error);
    }
  },

  setConnected: (connected: boolean) => {
    set({ connected });
  },

  setPaperMode: (paperMode: boolean) => {
    set({ paperMode });
  },

  initWebSocket: () => {
    const handler = (data: unknown) => {
      const update = data as {
        type: string;
        health?: SystemHealth;
        risk_status?: RiskStatus;
        connected?: boolean;
      };

      if (update.type === "health" && update.health) {
        set({ health: update.health });
      }
      if (update.type === "risk_update" && update.risk_status) {
        set({ riskStatus: update.risk_status });
      }
    };

    tradingWS.subscribe("system", handler);

    const unsubConnection = tradingWS.onConnectionChange((connected) => {
      set({ connected });
    });

    // Set initial connection state
    set({ connected: tradingWS.connected });

    return () => {
      tradingWS.unsubscribe("system", handler);
      unsubConnection();
    };
  },
}));
