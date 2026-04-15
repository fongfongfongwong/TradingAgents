"use client";

import { useEffect, useState } from "react";
import { useTicker } from "@/hooks/useTicker";
import { getOptions, type OptionsData } from "@/lib/api";

export default function OptionsTab() {
  const { ticker } = useTicker();
  const [data, setData] = useState<OptionsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getOptions(ticker)
      .then(setData)
      .catch(() => {
        setError("Failed to load options data. Backend may need /api/options endpoint.");
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) {
    return <p className="text-xs text-[#8a8f98]">Loading options for {ticker}...</p>;
  }

  if (error) {
    return <p className="text-xs text-[#e23b4a]">{error}</p>;
  }

  if (!data) return null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold">{ticker} Options</h2>
          <p className="text-[11px] text-[#8a8f98]">Expiration: {data.expiration}</p>
        </div>
        <div className="flex gap-4 text-xs">
          <div className="rounded border border-white/[0.08] bg-white/[0.02] px-3 py-2 text-center">
            <p className="text-[#8a8f98]">Put/Call Ratio</p>
            <p
              className={`font-mono text-lg font-bold ${
                data.put_call_ratio > 1
                  ? "text-[#e23b4a]"
                  : data.put_call_ratio < 0.7
                    ? "text-[#10b981]"
                    : "text-[#ec7e00]"
              }`}
            >
              {data.put_call_ratio.toFixed(2)}
            </p>
          </div>
          {data.iv_rank != null && (
            <div className="rounded border border-white/[0.08] bg-white/[0.02] px-3 py-2 text-center">
              <p className="text-[#8a8f98]">IV Rank</p>
              <p className="font-mono text-lg font-bold text-[#5e6ad2]">
                {data.iv_rank.toFixed(0)}%
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Options chain table */}
      <div className="overflow-x-auto rounded border border-white/[0.08]">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-white/[0.08] bg-white/[0.02]">
              <th colSpan={4} className="px-2 py-1.5 text-center text-[#10b981]">
                CALLS
              </th>
              <th className="border-x border-white/[0.08] px-2 py-1.5 text-center text-[#8a8f98]">
                STRIKE
              </th>
              <th colSpan={4} className="px-2 py-1.5 text-center text-[#e23b4a]">
                PUTS
              </th>
            </tr>
            <tr className="border-b border-white/[0.05] text-[9px] uppercase text-[#62666d]">
              <th className="px-2 py-1 text-right">Bid</th>
              <th className="px-2 py-1 text-right">Ask</th>
              <th className="px-2 py-1 text-right">Vol</th>
              <th className="px-2 py-1 text-right">OI</th>
              <th className="border-x border-white/[0.08] px-2 py-1 text-center" />
              <th className="px-2 py-1 text-right">Bid</th>
              <th className="px-2 py-1 text-right">Ask</th>
              <th className="px-2 py-1 text-right">Vol</th>
              <th className="px-2 py-1 text-right">OI</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.03] font-mono">
            {data.chain.map((row) => (
              <tr key={row.strike} className="hover:bg-white/[0.02]">
                <td className="px-2 py-1 text-right text-[#d0d6e0]">
                  {row.call_bid?.toFixed(2) ?? "--"}
                </td>
                <td className="px-2 py-1 text-right text-[#d0d6e0]">
                  {row.call_ask?.toFixed(2) ?? "--"}
                </td>
                <td className="px-2 py-1 text-right text-[#8a8f98]">
                  {row.call_volume.toLocaleString()}
                </td>
                <td className="px-2 py-1 text-right text-[#62666d]">
                  {row.call_oi.toLocaleString()}
                </td>
                <td className="border-x border-white/[0.08] px-2 py-1 text-center font-bold text-[#f7f8f8]">
                  {row.strike.toFixed(1)}
                </td>
                <td className="px-2 py-1 text-right text-[#d0d6e0]">
                  {row.put_bid?.toFixed(2) ?? "--"}
                </td>
                <td className="px-2 py-1 text-right text-[#d0d6e0]">
                  {row.put_ask?.toFixed(2) ?? "--"}
                </td>
                <td className="px-2 py-1 text-right text-[#8a8f98]">
                  {row.put_volume.toLocaleString()}
                </td>
                <td className="px-2 py-1 text-right text-[#62666d]">
                  {row.put_oi.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
