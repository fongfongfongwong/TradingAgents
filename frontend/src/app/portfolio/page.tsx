"use client";

import { useEffect, useState } from "react";
import { getPortfolio } from "@/lib/api";
import type { PortfolioSummary } from "@/lib/api";

const DEFAULT_PORTFOLIO: PortfolioSummary = {
  total_value: 100000,
  cash: 100000,
  total_pnl: 0,
  total_pnl_pct: 0,
  positions: [],
};

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usingDefaults, setUsingDefaults] = useState(false);

  useEffect(() => {
    getPortfolio()
      .then((p) => {
        // Sanitize any NaN / null / undefined values
        setPortfolio(sanitizePortfolio(p));
      })
      .catch(() => {
        setError("Backend unavailable. Showing paper trading starting state.");
        setUsingDefaults(true);
        setPortfolio(DEFAULT_PORTFOLIO);
      });
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <p className="mt-1 text-sm text-gray-400">
          Paper trading portfolio -- track positions and P&L in real-time.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-yellow-700 bg-yellow-900/30 px-4 py-3 text-sm text-yellow-300">
          {error}
        </div>
      )}

      {usingDefaults && (
        <div className="rounded-lg border border-blue-800 bg-blue-900/20 px-4 py-3 text-sm text-blue-300">
          Showing initial paper trading state: $100,000 starting capital, no open positions.
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
              value={fmtSafe(portfolio.total_pnl)}
              color={pnlColor(portfolio.total_pnl)}
            />
            <SummaryCard
              label="P&L %"
              value={pctSafe(portfolio.total_pnl_pct)}
              color={pnlColor(portfolio.total_pnl_pct)}
            />
          </div>

          {/* Allocation bar */}
          {portfolio.positions.length > 0 && (
            <section>
              <h2 className="mb-3 text-lg font-semibold">Allocation</h2>
              <div className="h-6 w-full overflow-hidden rounded-full bg-gray-700">
                {portfolio.positions.map((pos, idx) => {
                  const posValue = safeNum(pos.shares) * safeNum(pos.current_price);
                  const pct = portfolio.total_value > 0 ? (posValue / portfolio.total_value) * 100 : 0;
                  const colors = [
                    "bg-brand-500",
                    "bg-green-500",
                    "bg-purple-500",
                    "bg-yellow-500",
                    "bg-blue-500",
                    "bg-red-500",
                  ];
                  return (
                    <div
                      key={pos.ticker}
                      className={`inline-block h-full ${colors[idx % colors.length]}`}
                      style={{ width: `${pct}%` }}
                      title={`${pos.ticker}: ${pct.toFixed(1)}%`}
                    />
                  );
                })}
                {/* Cash portion */}
                <div
                  className="inline-block h-full bg-gray-600"
                  style={{
                    width: `${portfolio.total_value > 0 ? (safeNum(portfolio.cash) / portfolio.total_value) * 100 : 100}%`,
                  }}
                  title={`Cash: ${portfolio.total_value > 0 ? ((safeNum(portfolio.cash) / portfolio.total_value) * 100).toFixed(1) : 100}%`}
                />
              </div>
              <div className="mt-1 flex flex-wrap gap-3 text-xs text-gray-400">
                {portfolio.positions.map((pos, idx) => {
                  const colors = [
                    "bg-brand-500",
                    "bg-green-500",
                    "bg-purple-500",
                    "bg-yellow-500",
                    "bg-blue-500",
                    "bg-red-500",
                  ];
                  return (
                    <span key={pos.ticker} className="flex items-center gap-1">
                      <span className={`inline-block h-2 w-2 rounded-full ${colors[idx % colors.length]}`} />
                      {pos.ticker}
                    </span>
                  );
                })}
                <span className="flex items-center gap-1">
                  <span className="inline-block h-2 w-2 rounded-full bg-gray-600" />
                  Cash
                </span>
              </div>
            </section>
          )}

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
                        No open positions. Run an analysis to generate trade signals.
                      </td>
                    </tr>
                  )}
                  {portfolio.positions.map((pos) => (
                    <tr key={pos.ticker} className="hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-medium">{pos.ticker}</td>
                      <td className="px-4 py-3">{safeNum(pos.shares)}</td>
                      <td className="px-4 py-3">{fmtSafe(pos.avg_cost)}</td>
                      <td className="px-4 py-3">{fmtSafe(pos.current_price)}</td>
                      <td className={`px-4 py-3 ${pnlColor(pos.pnl)}`}>
                        {fmtSafe(pos.pnl)}
                      </td>
                      <td className={`px-4 py-3 ${pnlColor(pos.pnl_pct)}`}>
                        {pctSafe(pos.pnl_pct)}
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

function safeNum(n: number | null | undefined): number {
  if (n === null || n === undefined || isNaN(n)) return 0;
  return n;
}

function sanitizePortfolio(p: PortfolioSummary): PortfolioSummary {
  return {
    total_value: safeNum(p.total_value),
    cash: safeNum(p.cash),
    total_pnl: safeNum(p.total_pnl),
    total_pnl_pct: safeNum(p.total_pnl_pct),
    positions: (p.positions ?? []).map((pos) => ({
      ticker: pos.ticker ?? "???",
      shares: safeNum(pos.shares),
      avg_cost: safeNum(pos.avg_cost),
      current_price: safeNum(pos.current_price),
      pnl: safeNum(pos.pnl),
      pnl_pct: safeNum(pos.pnl_pct),
    })),
  };
}

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(safeNum(n));
}

function fmtSafe(n: number | null | undefined): string {
  return fmt(safeNum(n));
}

function pctSafe(n: number | null | undefined): string {
  const safe = safeNum(n);
  return `${(safe * 100).toFixed(2)}%`;
}

function pnlColor(n: number | null | undefined): string {
  const safe = safeNum(n);
  if (safe > 0) return "text-green-400";
  if (safe < 0) return "text-red-400";
  return "text-gray-400";
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
