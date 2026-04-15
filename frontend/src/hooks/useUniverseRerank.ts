import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface UniverseTicker {
  ticker: string;
  composite_score: number;
  realized_vol_20d: number | null;
}

export interface UniverseRankResult {
  equities: UniverseTicker[];
  etfs: UniverseTicker[];
}

export interface UseUniverseRerankReturn {
  /** Top-20 equity tickers sorted by composite volatility score. */
  equityTickers: string[];
  /** Top-20 ETF tickers sorted by composite volatility score. */
  etfTickers: string[];
  /** Combined flat list of all tickers (equities + ETFs). */
  allTickers: string[];
  /** Whether the initial fetch is still in-flight. */
  loading: boolean;
  /** Last error message, or null. */
  error: string | null;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_INTERVAL_MS = 60_000; // 60 seconds

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

/**
 * Polls GET /api/v3/universe/top-volatile every 60 seconds and returns
 * the current top-20 equity + top-20 ETF ticker lists. These become
 * the watchlist for the SignalTable.
 */
export function useUniverseRerank(): UseUniverseRerankReturn {
  const [equityTickers, setEquityTickers] = useState<string[]>([]);
  const [etfTickers, setEtfTickers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchUniverse = useCallback(async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/v3/universe`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();

      // Backend returns {ndx100: string[], top_etfs: string[], combined: string[]}
      // OR {equity: [{ticker, ...}], etf: [{ticker, ...}]} from the top-volatile endpoint
      const eqRaw = data.ndx100 ?? data.equity ?? [];
      const etfRaw = data.top_etfs ?? data.etf ?? [];
      setEquityTickers(eqRaw.map((t: string | { ticker: string }) => typeof t === "string" ? t : t.ticker).slice(0, 20));
      setEtfTickers(etfRaw.map((t: string | { ticker: string }) => typeof t === "string" ? t : t.ticker).slice(0, 20));
      setError(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Universe fetch failed";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchUniverse();

    timerRef.current = setInterval(() => {
      void fetchUniverse();
    }, POLL_INTERVAL_MS);

    return () => {
      if (timerRef.current !== null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [fetchUniverse]);

  const allTickers = useMemo(
    () => [...equityTickers, ...etfTickers],
    [equityTickers, etfTickers],
  );

  return { equityTickers, etfTickers, allTickers, loading, error };
}
