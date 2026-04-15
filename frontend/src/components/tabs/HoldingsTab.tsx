"use client";

import { useEffect, useState } from "react";
import { useTicker } from "@/hooks/useTicker";
import { getHoldings, type HoldingsData } from "@/lib/api";

export default function HoldingsTab() {
  const { ticker } = useTicker();
  const [data, setData] = useState<HoldingsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getHoldings(ticker)
      .then(setData)
      .catch(() => {
        setError("Failed to load holdings data. Backend may need /api/holdings endpoint.");
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) return <p className="text-xs text-[#8a8f98]">Loading holdings for {ticker}...</p>;
  if (error) return <p className="text-xs text-[#e23b4a]">{error}</p>;
  if (!data) return null;

  const fmtShares = (n: number) => n.toLocaleString();

  return (
    <div className="space-y-6">
      {/* Institutional Holders */}
      <div>
        <h2 className="mb-3 text-lg font-bold">
          {ticker} — Institutional Holders
        </h2>

        {data.institutional.length === 0 ? (
          <p className="text-xs text-[#62666d]">No institutional holder data available.</p>
        ) : (
          <div className="overflow-x-auto rounded border border-white/[0.08]">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-white/[0.08] bg-white/[0.02] text-[9px] uppercase text-[#62666d]">
                  <th className="px-3 py-2 text-left">Holder</th>
                  <th className="px-3 py-2 text-right">Shares</th>
                  <th className="px-3 py-2 text-right">Change</th>
                  <th className="px-3 py-2 text-right">Change %</th>
                  <th className="px-3 py-2 text-right">Filing Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.03]">
                {data.institutional.map((h, i) => (
                  <tr key={i} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-2 text-[#d0d6e0]">{h.holder}</td>
                    <td className="px-3 py-2 text-right font-mono text-[#f7f8f8]">
                      {fmtShares(h.shares)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-mono ${
                        h.change > 0
                          ? "text-[#10b981]"
                          : h.change < 0
                            ? "text-[#e23b4a]"
                            : "text-[#8a8f98]"
                      }`}
                    >
                      {h.change > 0 ? "+" : ""}
                      {fmtShares(h.change)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-mono ${
                        h.change_pct > 0
                          ? "text-[#10b981]"
                          : h.change_pct < 0
                            ? "text-[#e23b4a]"
                            : "text-[#8a8f98]"
                      }`}
                    >
                      {h.change_pct > 0 ? "+" : ""}
                      {h.change_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 text-right text-[#8a8f98]">
                      {h.filing_date}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Insider Transactions */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-[#d0d6e0]">
          Insider Transactions
        </h3>

        {data.insider_transactions.length === 0 ? (
          <p className="text-xs text-[#62666d]">No insider transaction data available.</p>
        ) : (
          <div className="overflow-x-auto rounded border border-white/[0.08]">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-white/[0.08] bg-white/[0.02] text-[9px] uppercase text-[#62666d]">
                  <th className="px-3 py-2 text-left">Insider</th>
                  <th className="px-3 py-2 text-left">Relation</th>
                  <th className="px-3 py-2 text-center">Action</th>
                  <th className="px-3 py-2 text-right">Shares</th>
                  <th className="px-3 py-2 text-right">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.03]">
                {data.insider_transactions.map((tx, i) => (
                  <tr key={i} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-2 text-[#d0d6e0]">{tx.insider}</td>
                    <td className="px-3 py-2 text-[#8a8f98]">{tx.relation}</td>
                    <td className="px-3 py-2 text-center">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                          tx.action === "buy"
                            ? "bg-[#10b981]/20 text-[#10b981]"
                            : "bg-[#e23b4a]/20 text-[#e23b4a]"
                        }`}
                      >
                        {tx.action}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[#f7f8f8]">
                      {fmtShares(tx.shares)}
                    </td>
                    <td className="px-3 py-2 text-right text-[#8a8f98]">
                      {tx.date}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
