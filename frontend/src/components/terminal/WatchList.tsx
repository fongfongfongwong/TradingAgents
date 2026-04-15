"use client";

import { useEffect, useState } from "react";
import { useTicker } from "@/hooks/useTicker";
import { getDivergence, type DivergenceData } from "@/lib/api";

interface WatchItem {
  ticker: string;
  score: number | null;
  loading: boolean;
}

export default function WatchList() {
  const { ticker, setTicker, watchlist, removeFromWatchlist } = useTicker();
  const [items, setItems] = useState<WatchItem[]>([]);

  useEffect(() => {
    setItems(watchlist.map((t) => ({ ticker: t, score: null, loading: true })));

    watchlist.forEach((t, idx) => {
      getDivergence(t)
        .then((d: DivergenceData) => {
          setItems((prev) => {
            const next = [...prev];
            if (next[idx]) {
              next[idx] = { ticker: t, score: d.composite_score, loading: false };
            }
            return next;
          });
        })
        .catch(() => {
          setItems((prev) => {
            const next = [...prev];
            if (next[idx]) {
              next[idx] = { ticker: t, score: null, loading: false };
            }
            return next;
          });
        });
    });
  }, [watchlist]);

  const scoreColor = (s: number | null) => {
    if (s == null) return "text-[#62666d]";
    if (s > 0.15) return "text-[#10b981]";
    if (s < -0.15) return "text-[#e23b4a]";
    return "text-[#ec7e00]";
  };

  return (
    <aside className="flex w-48 shrink-0 flex-col border-r border-white/[0.08] bg-[#0f1011]">
      <div className="border-b border-white/[0.08] px-3 py-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-wider text-[#8a8f98]">
          Watchlist
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto">
        {items.map((item) => (
          <button
            key={item.ticker}
            onClick={() => setTicker(item.ticker)}
            className={`flex w-full items-center justify-between px-3 py-2 text-left transition-colors hover:bg-white/[0.03] ${
              item.ticker === ticker
                ? "border-l-2 border-[#5e6ad2] bg-[#5e6ad2]/10"
                : "border-l-2 border-transparent"
            }`}
          >
            <div>
              <span className="text-xs font-bold text-[#f7f8f8]">
                {item.ticker}
              </span>
            </div>
            <div className="text-right">
              {item.loading ? (
                <span className="text-[10px] text-[#62666d]">...</span>
              ) : (
                <span
                  className={`font-mono text-[11px] font-bold ${scoreColor(item.score)}`}
                >
                  {item.score != null
                    ? `${item.score > 0 ? "+" : ""}${item.score.toFixed(2)}`
                    : "N/A"}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>

      {/* Divergence mini legend */}
      <div className="border-t border-white/[0.08] px-3 py-2">
        <p className="text-[9px] text-[#62666d]">
          Score: divergence composite (-1 to +1)
        </p>
      </div>
    </aside>
  );
}
