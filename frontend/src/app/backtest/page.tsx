"use client";

import { useState, type FormEvent } from "react";
import { runBacktest } from "@/lib/api";
import type { BacktestResult } from "@/lib/api";

const SAMPLE_RESULTS: BacktestResult = {
  id: "sample",
  ticker: "AAPL",
  start_date: "2024-01-01",
  end_date: "2024-12-31",
  total_return: 0.2834,
  sharpe_ratio: 1.42,
  max_drawdown: -0.0891,
  win_rate: 0.64,
  trades: [
    { date: "2024-01-15", action: "buy", price: 185.92, shares: 100, pnl: 0 },
    { date: "2024-03-08", action: "sell", price: 198.45, shares: 100, pnl: 1253.0 },
    { date: "2024-04-22", action: "buy", price: 168.84, shares: 110, pnl: 0 },
    { date: "2024-06-14", action: "sell", price: 212.49, shares: 110, pnl: 4801.5 },
    { date: "2024-08-05", action: "buy", price: 209.82, shares: 95, pnl: 0 },
    { date: "2024-10-18", action: "sell", price: 233.85, shares: 95, pnl: 2282.85 },
    { date: "2024-11-11", action: "buy", price: 224.23, shares: 90, pnl: 0 },
    { date: "2024-12-20", action: "sell", price: 247.45, shares: 90, pnl: 2089.8 },
  ],
};

export default function BacktestPage() {
  const [ticker, setTicker] = useState("");
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [capital, setCapital] = useState(100_000);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSample, setShowSample] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!ticker.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setShowSample(false);

    try {
      const data = await runBacktest({
        ticker: ticker.toUpperCase().trim(),
        start_date: startDate,
        end_date: endDate,
        initial_capital: capital,
      });
      setResult(data);
    } catch {
      setError("Backend unavailable. Showing sample backtest result.");
      setResult(SAMPLE_RESULTS);
      setShowSample(true);
    } finally {
      setLoading(false);
    }
  }

  const displayResult = result;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Backtest</h1>
        <p className="mt-1 text-sm text-gray-400">
          Test trading strategies against historical data with performance metrics.
        </p>
      </div>

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
        {!result && (
          <button
            type="button"
            onClick={() => {
              setResult(SAMPLE_RESULTS);
              setShowSample(true);
              setError(null);
            }}
            className="rounded-md border border-gray-700 px-4 py-2 text-xs text-gray-400 transition-colors hover:border-gray-600 hover:text-white"
          >
            View Sample Result
          </button>
        )}
      </form>

      {error && !showSample && <p className="text-sm text-red-400">{error}</p>}

      {showSample && (
        <div className="rounded-lg border border-blue-800 bg-blue-900/20 px-4 py-3 text-sm text-blue-300">
          Showing sample backtest data (AAPL, 2024). Start the backend to run live backtests.
        </div>
      )}

      {/* Results */}
      {displayResult && (
        <div className="space-y-6">
          {/* Summary stats */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <MetricCard
              label="Total Return"
              value={`${(displayResult.total_return * 100).toFixed(2)}%`}
              positive={displayResult.total_return >= 0}
            />
            <MetricCard
              label="Sharpe Ratio"
              value={displayResult.sharpe_ratio.toFixed(2)}
              positive={displayResult.sharpe_ratio >= 1}
            />
            <MetricCard
              label="Max Drawdown"
              value={`${(displayResult.max_drawdown * 100).toFixed(2)}%`}
              positive={false}
            />
            <MetricCard
              label="Win Rate"
              value={`${(displayResult.win_rate * 100).toFixed(0)}%`}
              positive={displayResult.win_rate >= 0.5}
            />
          </div>

          {/* P&L Summary */}
          <div className="rounded-lg border border-gray-800 bg-gray-800/20 p-4">
            <h3 className="mb-3 text-sm font-semibold text-gray-300">Performance Summary</h3>
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <p className="text-xs text-gray-500">Total Trades</p>
                <p className="text-lg font-bold text-white">{displayResult.trades.length}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500">Winning Trades</p>
                <p className="text-lg font-bold text-green-400">
                  {displayResult.trades.filter((t) => t.pnl > 0).length}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500">Total P&L</p>
                <p className="text-lg font-bold text-green-400">
                  $
                  {displayResult.trades
                    .reduce((sum, t) => sum + t.pnl, 0)
                    .toLocaleString("en-US", { minimumFractionDigits: 2 })}
                </p>
              </div>
            </div>
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
                {displayResult.trades.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                      No trades executed.
                    </td>
                  </tr>
                )}
                {displayResult.trades.map((t, i) => (
                  <tr key={i} className="hover:bg-gray-800/30">
                    <td className="px-4 py-3">{t.date}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          t.action === "buy"
                            ? "bg-green-900/40 text-green-400"
                            : "bg-red-900/40 text-red-400"
                        }`}
                      >
                        {t.action.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3">${t.price.toFixed(2)}</td>
                    <td className="px-4 py-3">{t.shares}</td>
                    <td
                      className={`px-4 py-3 font-medium ${t.pnl > 0 ? "text-green-400" : t.pnl < 0 ? "text-red-400" : "text-gray-500"}`}
                    >
                      {t.pnl > 0 ? "+" : ""}${t.pnl.toFixed(2)}
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
