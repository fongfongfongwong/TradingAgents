"use client";

import { useState, type FormEvent } from "react";
import { runBacktest } from "@/lib/api";
import type { BacktestResult } from "@/lib/api";

export default function BacktestPage() {
  const [ticker, setTicker] = useState("");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [capital, setCapital] = useState(100_000);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!ticker.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await runBacktest({
        ticker: ticker.toUpperCase().trim(),
        start_date: startDate,
        end_date: endDate,
        initial_capital: capital,
      });
      setResult(data);
    } catch {
      setError("Failed to run backtest. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Backtest</h1>

      {/* Form */}
      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap items-end gap-4 rounded-lg border border-gray-800 bg-gray-800/30 p-5"
      >
        <div>
          <label className="mb-1 block text-xs text-gray-400">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            className="w-28 rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-400">Start</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-400">End</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-400">Capital ($)</label>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            className="w-32 rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className="rounded-md bg-brand-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
        >
          {loading ? "Running..." : "Run Backtest"}
        </button>
      </form>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {/* Results */}
      {result && (
        <div className="space-y-6">
          {/* Summary stats */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <MetricCard
              label="Total Return"
              value={`${(result.total_return * 100).toFixed(2)}%`}
              positive={result.total_return >= 0}
            />
            <MetricCard
              label="Sharpe Ratio"
              value={result.sharpe_ratio.toFixed(2)}
              positive={result.sharpe_ratio >= 1}
            />
            <MetricCard
              label="Max Drawdown"
              value={`${(result.max_drawdown * 100).toFixed(2)}%`}
              positive={false}
            />
            <MetricCard
              label="Win Rate"
              value={`${(result.win_rate * 100).toFixed(0)}%`}
              positive={result.win_rate >= 0.5}
            />
          </div>

          {/* Trades table */}
          <div className="overflow-hidden rounded-lg border border-gray-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-800 bg-gray-800/40 text-xs uppercase text-gray-400">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Price</th>
                  <th className="px-4 py-3">Shares</th>
                  <th className="px-4 py-3">P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {result.trades.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                      No trades executed.
                    </td>
                  </tr>
                )}
                {result.trades.map((t, i) => (
                  <tr key={i} className="hover:bg-gray-800/30">
                    <td className="px-4 py-3">{t.date}</td>
                    <td className="px-4 py-3">
                      <span
                        className={
                          t.action === "buy"
                            ? "text-green-400"
                            : "text-red-400"
                        }
                      >
                        {t.action.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3">${t.price.toFixed(2)}</td>
                    <td className="px-4 py-3">{t.shares}</td>
                    <td
                      className={`px-4 py-3 ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                    >
                      ${t.pnl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive: boolean;
}) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-800/30 p-4">
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${positive ? "text-green-400" : "text-red-400"}`}>
        {value}
      </p>
    </div>
  );
}
