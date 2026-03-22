import { create } from "zustand";
import { AlertPriority } from "@/types";
import type { AlertItem } from "@/types";

interface AlertsState {
  alerts: AlertItem[];
  unreadCount: number;

  // Actions
  addAlert: (alert: AlertItem) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  removeAlert: (id: string) => void;
  clearAll: () => void;

  // Filtered getters
  getByPriority: (priority: AlertPriority) => AlertItem[];
}

export const useAlertsStore = create<AlertsState>((set, get) => ({
  alerts: [],
  unreadCount: 0,

  addAlert: (alert: AlertItem) => {
    set((state) => {
      const alerts = [alert, ...state.alerts];
      return {
        alerts,
        unreadCount: alerts.filter((a) => !a.read).length,
      };
    });
  },

  markRead: (id: string) => {
    set((state) => {
      const alerts = state.alerts.map((a) =>
        a.id === id ? { ...a, read: true } : a
      );
      return {
        alerts,
        unreadCount: alerts.filter((a) => !a.read).length,
      };
    });
  },

  markAllRead: () => {
    set((state) => ({
      alerts: state.alerts.map((a) => ({ ...a, read: true })),
      unreadCount: 0,
    }));
  },

  removeAlert: (id: string) => {
    set((state) => {
      const alerts = state.alerts.filter((a) => a.id !== id);
      return {
        alerts,
        unreadCount: alerts.filter((a) => !a.read).length,
      };
    });
  },

  clearAll: () => set({ alerts: [], unreadCount: 0 }),

  getByPriority: (priority: AlertPriority) => {
    return get().alerts.filter((a) => a.priority === priority);
  },
}));
