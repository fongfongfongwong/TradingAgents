"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

interface TickerContextValue {
  ticker: string;
  setTicker: (t: string) => void;
  watchlist: string[];
  addToWatchlist: (t: string) => void;
  removeFromWatchlist: (t: string) => void;
}

const TickerContext = createContext<TickerContextValue | null>(null);

const DEFAULT_WATCHLIST = ["SPY", "AAPL", "TSLA", "NVDA", "MSFT", "AMZN"];

export function TickerProvider({ children }: { children: ReactNode }) {
  const [ticker, setTickerRaw] = useState("AAPL");
  const [watchlist, setWatchlist] = useState<string[]>(DEFAULT_WATCHLIST);

  const setTicker = useCallback((t: string) => {
    setTickerRaw(t.toUpperCase().trim());
  }, []);

  const addToWatchlist = useCallback((t: string) => {
    const upper = t.toUpperCase().trim();
    setWatchlist((prev) =>
      prev.includes(upper) ? prev : [...prev, upper],
    );
  }, []);

  const removeFromWatchlist = useCallback((t: string) => {
    setWatchlist((prev) => prev.filter((x) => x !== t));
  }, []);

  return (
    <TickerContext.Provider
      value={{ ticker, setTicker, watchlist, addToWatchlist, removeFromWatchlist }}
    >
      {children}
    </TickerContext.Provider>
  );
}

export function useTicker(): TickerContextValue {
  const ctx = useContext(TickerContext);
  if (!ctx) throw new Error("useTicker must be used within TickerProvider");
  return ctx;
}
