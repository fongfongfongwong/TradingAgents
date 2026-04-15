import { useEffect, useRef } from "react";

import { getPriceSnapshots } from "@/lib/api";
import { useSignalsStore } from "@/stores/signalsStore";

const POLL_INTERVAL_MS = 2_000; // 2 seconds — Databento delivers real-time data

/**
 * Polls /api/v3/prices/snapshot every 30s and writes to a separate
 * `priceMap` in the Zustand store. This avoids race conditions with
 * `setItems` from signal fetches — prices are merged at render time
 * in SignalTable via the priceMap selector.
 */
export function usePricePolling(): void {
  const itemCount = useSignalsStore((s) => s.items.length);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (itemCount === 0) return;

    const fetchPrices = async () => {
      try {
        const items = useSignalsStore.getState().items;
        if (items.length === 0) return;
        const tickers = items.map((it) => it.ticker);
        const snaps = await getPriceSnapshots(tickers);
        if (snaps && Object.keys(snaps).length > 0) {
          useSignalsStore.getState().setPriceMap(snaps);
        }
      } catch {
        // Silently ignore — prices are best-effort
      }
    };

    // Initial fetch immediately
    const initTimer = setTimeout(() => void fetchPrices(), 300);

    // Poll every 2s
    timerRef.current = setInterval(() => void fetchPrices(), POLL_INTERVAL_MS);

    return () => {
      clearTimeout(initTimer);
      if (timerRef.current !== null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [itemCount]);
}
