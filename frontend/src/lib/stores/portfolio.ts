import { create } from "zustand";
import type { Position } from "@/types";

interface PortfolioState {
  totalValue: number;
  dailyPnl: number;
  dailyPnlPercent: number;
  cash: number;
  positions: Position[];

  // Actions
  setPositions: (positions: Position[]) => void;
  updatePrice: (symbol: string, price: number) => void;
  setCash: (cash: number) => void;
  reset: () => void;
}

const initialState = {
  totalValue: 50000,
  dailyPnl: 0,
  dailyPnlPercent: 0,
  cash: 50000,
  positions: [] as Position[],
};

function recalculate(positions: Position[], cash: number) {
  const positionsValue = positions.reduce((sum, p) => sum + p.marketValue, 0);
  const totalValue = cash + positionsValue;
  const dailyPnl = positions.reduce((sum, p) => sum + p.dayChange * p.quantity, 0);
  const dailyPnlPercent = totalValue > 0 ? (dailyPnl / totalValue) * 100 : 0;

  return { totalValue, dailyPnl, dailyPnlPercent };
}

export const usePortfolioStore = create<PortfolioState>((set, get) => ({
  ...initialState,

  setPositions: (positions: Position[]) => {
    const { cash } = get();
    const calculated = recalculate(positions, cash);
    set({ positions, ...calculated });
  },

  updatePrice: (symbol: string, price: number) => {
    const { positions, cash } = get();
    const updated = positions.map((p) => {
      if (p.symbol !== symbol) return p;
      const marketValue = price * p.quantity;
      const unrealizedPnl = (price - p.avgCost) * p.quantity;
      const unrealizedPnlPercent =
        p.avgCost > 0 ? ((price - p.avgCost) / p.avgCost) * 100 : 0;
      return {
        ...p,
        currentPrice: price,
        marketValue,
        unrealizedPnl,
        unrealizedPnlPercent,
      };
    });
    const calculated = recalculate(updated, cash);
    set({ positions: updated, ...calculated });
  },

  setCash: (cash: number) => {
    const { positions } = get();
    const calculated = recalculate(positions, cash);
    set({ cash, ...calculated });
  },

  reset: () => set(initialState),
}));
