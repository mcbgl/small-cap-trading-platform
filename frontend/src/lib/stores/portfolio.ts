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
  const positionsValue = positions.reduce((sum, p) => sum + p.market_value, 0);
  const totalValue = cash + positionsValue;
  const dailyPnl = positions.reduce((sum, p) => sum + p.day_change * p.qty, 0);
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
      const market_value = price * p.qty;
      const unrealized_pnl = (price - p.avg_cost) * p.qty;
      const unrealized_pnl_pct =
        p.avg_cost > 0 ? ((price - p.avg_cost) / p.avg_cost) * 100 : 0;
      return {
        ...p,
        current_price: price,
        market_value,
        unrealized_pnl,
        unrealized_pnl_pct,
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
