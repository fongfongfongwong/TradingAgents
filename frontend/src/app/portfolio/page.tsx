"use client";

import { useEffect, useState } from "react";
import { getPortfolio } from "@/lib/api";
import type { PortfolioSummary } from "@/lib/api";

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPortfolio()
      .then(setPortfolio)
      .catch(() => setError("Failed to load portfolio. Is the backend running?"));
  }, []);

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Portfolio</h1>

      {error && (
        <div className="rounded-lg border border-yellow-700 bg-yellow-900/30 px-4 py-3 text-sm text-yellow-300">
          {error}
        </div>
      )}

      {portfolio && (
        <>
          {/* Summary row */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <SummaryCard label="Total Value" value={fmt(portfolio.total_value)} />
            <SummaryCard label="Cash" value={fmt(portfolio.cash)} />
            <SummaryCard
              label="Total P&L"
              value={fmt(portfolio.total_pnl)}
              color={portfolio.total_pnl >= 0 ? "text-green-400" : "text-red-400"}
            />
            <SummaryCard
              label="P&L %"
              value={`${(portfolio.total_pnl_pct * 100).toFixed(2)}%`}
              color={portfolio.total_pnl_pct >= 0 ? "text-green-400" : "text-red-400"}
            />
          </div>

          {/* Positions table */}
          <section>
            <h2 className="mb-3 text-lg font-semibold">Positions</h2>
            <div className="overflow-hidden rounded-lg border border-gray-800">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-gray-800 bg-gray-800/40 text-xs uppercase text-gray-400">
                  <tr>
                    <th className="px-4 py-3">Ticker</th>
                    <th className="px-4 py-3">Shares</th>
                    <th className="px-4 py-3">Avg Cost</th>
                    <th className="px-4 py-3">Current</th>
                    <th className="px-4 py-3">P&L</th>
                    <th className="px-4 py-3">P&L %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {portfolio.positions.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-gray-500">
                        No open positions.
                      </td>
                    </tr>
                  )}
                  {portfolio.positions.map((pos) => (
                    <tr key={pos.ticker} className="hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-medium">{pos.ticker}</td>
                      <td className="px-4 py-3">{pos.shares}</td>
                      <td className="px-4 py-3">${pos.avg_cost.toFixed(2)}</td>
                      <td className="px-4 py-3">${pos.current_price.toFixed(2)}</td>
                      <td
                        className={`px-4 py-3 ${pos.pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                      >
                        {fmt(pos.pnl)}
                      </td>
                      <td
                        className={`px-4 py-3 ${pos.pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}
                      >
                        {(pos.pnl_pct * 100).toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

/* ---------- helpers ---------- */

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(n);
}

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-800/30 p-4">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${color ?? "text-white"}`}>{value}</p>
    </div>
  );
}
