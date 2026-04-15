import { create } from "zustand";

import type { BatchSignalItem } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface BatchProgress {
  total: number;
  completed: number;
  failed: number;
  running: number;
}

export interface AutoRefreshState {
  autoRefreshEnabled: boolean;
  nextRefreshIn: number;
  toggleAutoRefresh?: () => void;
  refreshNow?: () => void;
}

export interface PriceSnapshot {
  last: number;
  change_pct: number;
  source?: string;
  ts?: string;
}

export interface SignalsState {
  items: BatchSignalItem[];
  prevItems: BatchSignalItem[];
  batchId: string | null;
  batchProgress: BatchProgress | null;
  lastRefreshedAt: number | null;

  // Separate price map — updated independently by usePricePolling
  priceMap: Record<string, PriceSnapshot>;

  // Auto-refresh countdown (written by useAutoRefresh, read by TopBar)
  autoRefresh: AutoRefreshState;

  // Actions
  setItems: (items: BatchSignalItem[]) => void;
  setPriceMap: (map: Record<string, PriceSnapshot>) => void;
  snapshotForDiff: () => void;
  upsertTicker: (ticker: string, partial: Partial<BatchSignalItem>) => void;
  setBatchProgress: (p: BatchProgress | null) => void;
  setBatchId: (id: string | null) => void;
  setAutoRefresh: (state: AutoRefreshState) => void;
  reset: () => void;
}

/* ------------------------------------------------------------------ */
/*  Default stub used when upsertTicker encounters an unknown ticker   */
/* ------------------------------------------------------------------ */

function makeStubItem(
  ticker: string,
  partial: Partial<BatchSignalItem>,
): BatchSignalItem {
  return {
    ticker,
    signal: "HOLD",
    conviction: 0,
    tier: 0,
    expected_value_pct: null,
    thesis_confidence: null,
    antithesis_confidence: null,
    disagreement_score: null,
    final_shares: 0,
    pipeline_latency_ms: 0,
    data_gaps: [],
    cached: false,
    ...partial,
  };
}

/* ------------------------------------------------------------------ */
/*  Store                                                              */
/* ------------------------------------------------------------------ */

export const useSignalsStore = create<SignalsState>()((set, get) => ({
  items: [],
  prevItems: [],
  batchId: null,
  batchProgress: null,
  lastRefreshedAt: null,
  priceMap: {},
  autoRefresh: { autoRefreshEnabled: false, nextRefreshIn: 0 },

  setItems: (items) =>
    set({
      items,
      lastRefreshedAt: Date.now(),
    }),

  setPriceMap: (map) => set({ priceMap: map }),

  snapshotForDiff: () => {
    const current = get().items;
    // Deep copy via structured clone to sever any shared references.
    set({ prevItems: structuredClone(current) });
  },

  upsertTicker: (ticker, partial) =>
    set((state) => {
      const idx = state.items.findIndex((it) => it.ticker === ticker);
      if (idx === -1) {
        // Ticker not present — append a new stub.
        return { items: [...state.items, makeStubItem(ticker, partial)] };
      }
      // Merge into existing item (immutable update).
      const updated = [...state.items];
      updated[idx] = { ...updated[idx], ...partial };
      return { items: updated };
    }),

  setBatchProgress: (p) => set({ batchProgress: p }),

  setBatchId: (id) => set({ batchId: id }),

  setAutoRefresh: (state) => set({ autoRefresh: state }),

  reset: () =>
    set({
      items: [],
      prevItems: [],
      batchId: null,
      batchProgress: null,
      lastRefreshedAt: null,
      priceMap: {},
      autoRefresh: { autoRefreshEnabled: false, nextRefreshIn: 0 },
    }),
}));
