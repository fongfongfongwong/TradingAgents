"use client";

import { useCallback, useEffect, useState } from "react";
import { useSignalsStore } from "@/stores/signalsStore";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface IndexData {
  symbol: string;
  price: number;
  change_pct: number;
}

interface MarketOverview {
  indices: Record<string, { price: number; change_pct: number }>;
  fear_greed: { value: number; label: string } | null;
  vix: { value: number; change_pct: number } | null;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function TopBar() {
  const [data, setData] = useState<MarketOverview | null>(null);
  const [error, setError] = useState(false);

  // Auto-refresh countdown from the global store (written by SignalTable)
  const autoRefresh = useSignalsStore((s) => s.autoRefresh);

  const fetchOverview = useCallback(async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/market/overview`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: MarketOverview = await res.json();
      setData(json);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void fetchOverview();
    const interval = setInterval(() => { void fetchOverview(); }, 60_000);
    return () => clearInterval(interval);
  }, [fetchOverview]);

  const changeColor = (pct: number) => (pct >= 0 ? "#3FB950" : "#F85149");

  const formatChange = (pct: number) =>
    `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;

  /* ---- Fear/Greed badge color ---- */
  const fgColor = (value: number | null): string => {
    if (value === null) return "#8B949E";
    if (value <= 25) return "#F85149";
    if (value <= 45) return "#F0883E";
    if (value <= 55) return "#8B949E";
    if (value <= 75) return "#3FB950";
    return "#3FB950";
  };

  return (
    <div className="flex h-[80px] min-h-[80px] items-center border-b border-[#21262D] bg-[#0D1117] px-4">
      {/* ---- Left: Indices ---- */}
      <div className="flex items-center gap-5">
        {error && !data && (
          <span className="text-xs text-[#484F58]">Market data unavailable</span>
        )}

        {data?.indices && Object.entries(data.indices).map(([symbol, idx]: [string, any]) => (
          <div key={symbol} className="flex flex-col items-start">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#8B949E]">
              {symbol}
            </span>
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-sm font-bold text-[#E6EDF3]">
                {(idx.price ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span
                className="font-mono text-xs font-semibold"
                style={{ color: changeColor(idx.change_pct ?? 0) }}
              >
                {formatChange(idx.change_pct)}
              </span>
            </div>
          </div>
        ))}

        {data && Object.keys(data.indices ?? {}).length === 0 && (
          <span className="text-xs text-[#484F58]">No index data</span>
        )}
      </div>

      {/* ---- Center: Brand ---- */}
      <div className="flex flex-1 items-center justify-center">
        <h1 className="text-sm font-bold tracking-widest text-[#58A6FF]">
          FLAB MASA
        </h1>
      </div>

      {/* ---- Right: Auto-refresh countdown + Fear/Greed + VIX ---- */}
      <div className="flex items-center gap-4">
        {/* Auto-refresh countdown chip */}
        {autoRefresh.autoRefreshEnabled && (
          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase tracking-wider text-[#8B949E]">
              Next Refresh
            </span>
            <span className="font-mono text-sm font-bold text-[#58A6FF]">
              {Math.floor(autoRefresh.nextRefreshIn / 60_000)}:
              {String(Math.floor((autoRefresh.nextRefreshIn % 60_000) / 1000)).padStart(2, "0")}
            </span>
          </div>
        )}
        {data?.fear_greed && (
          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase tracking-wider text-[#8B949E]">
              Fear/Greed
            </span>
            <span
              className="font-mono text-sm font-bold"
              style={{ color: fgColor(data.fear_greed.value ?? 50) }}
            >
              {data.fear_greed.value ?? "—"}
              {data.fear_greed.label && (
                <span className="ml-1 text-[10px] font-normal text-[#8B949E]">
                  {data.fear_greed.label}
                </span>
              )}
            </span>
          </div>
        )}

        {data?.vix && (
          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase tracking-wider text-[#8B949E]">VIX</span>
            <span
              className="font-mono text-sm font-bold"
              style={{ color: (data.vix.value ?? 0) > 25 ? "#F85149" : (data.vix.value ?? 0) > 18 ? "#F0883E" : "#3FB950" }}
            >
              {(data.vix.value ?? 0).toFixed(1)}
            </span>
          </div>
        )}

        {error && data && (
          <span className="text-[9px] text-[#484F58]">stale</span>
        )}
      </div>
    </div>
  );
}
