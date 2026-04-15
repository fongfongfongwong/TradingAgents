"use client";

import { useState, type FormEvent } from "react";
import { useTicker } from "@/hooks/useTicker";
import { runBacktest, type BacktestResult } from "@/lib/api";

const SAMPLE: BacktestResult = {
  ticker: "AAPL",
  metrics: {
    total_return: 0.2834,
    sharpe_ratio: 1.42,
    max_drawdown: -0.0891,
    win_rate: 0.64,
    total_trades: 8,
    winning_trades: 4,
    total_pnl: 10427.15,
    sortino_ratio: 1.85,
    annual_return: 0.31,
  },
  trades_count: 8,
};

export default function BacktestTab() {
  const { ticker } = useTicker();
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [capital, setCapital] = useState(100_000);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [useSample, setUseSample] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setUseSample(false);

    try {
      const r = await runBacktest({
        ticker,
        start_date: startDate,
        end_date: endDate,
        initial_capital: capital,
      });
      setResult(r);
    } catch {
      setError("Backtest failed. No backtest data available \u2014 check backend connection and try again.");
      setResult(null);
      setUseSample(false);
    } finally {
      setLoading(false);
    }
  };

  const showSample = () => {
    setResult(SAMPLE);
    setUseSample(true);
  };

  const m = result?.metrics;

  const pct = (v: number | undefined) =>
    v != null ? `${(v * 100).toFixed(2)}%` : "--";

  const fmt = (v: number | undefined) =>
    v != null
      ? v.toLocaleString("en-US", { style: "currency", currency: "USD" })
      : "--";

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold">Backtest — {ticker}</h2>

      {/* Form */}
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-[10px] text-[#8a8f98]">Start</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="rounded border border-white/[0.08] bg-white/[0.02] px-2 py-1.5 text-xs text-[#f7f8f8]"
          />
        </div>
        <div>
          <label className="mb-1 block text-[10px] text-[#8a8f98]">End</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="rounded border border-white/[0.08] bg-white/[0.02] px-2 py-1.5 text-xs text-[#f7f8f8]"
          />
        </div>
        <div>
          <label className="mb-1 block text-[10px] text-[#8a8f98]">Capital ($)</label>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            className="w-28 rounded border border-white/[0.08] bg-white/[0.02] px-2 py-1.5 text-xs text-[#f7f8f8]"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="rounded bg-[#5e6ad2] px-4 py-1.5 text-xs font-medium text-white hover:bg-[#7170ff] disabled:opacity-50"
        >
          {loading ? "Running..." : "Run Backtest"}
        </button>
        {!result && (
          <button
            type="button"
            onClick={showSample}
            className="rounded border border-white/[0.08] px-3 py-1.5 text-xs text-[#8a8f98] hover:text-[#d0d6e0]"
          >
            View Sample
          </button>
        )}
      </form>

      {error && (
        <div className="rounded border border-[#ec7e00]/30 bg-[#ec7e00]/10 px-3 py-2 text-xs text-[#ec7e00]">
          {error}
        </div>
      )}

      {useSample && (
        <div className="rounded border border-[#5e6ad2]/30 bg-[#5e6ad2]/10 px-3 py-2 text-xs text-[#828fff]">
          Showing sample backtest data.
        </div>
      )}

      {/* Results */}
      {m && (
        <>
          {/* Metric cards */}
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: "Total Return", value: pct(m.total_return), positive: (m.total_return ?? 0) > 0 },
              { label: "Sharpe Ratio", value: m.sharpe_ratio?.toFixed(2) ?? "--", positive: (m.sharpe_ratio ?? 0) > 1 },
              { label: "Max Drawdown", value: pct(m.max_drawdown), positive: false },
              { label: "Win Rate", value: pct(m.win_rate), positive: (m.win_rate ?? 0) > 0.5 },
            ].map((card) => (
              <div
                key={card.label}
                className="rounded border border-white/[0.08] bg-[#0f1011] p-3"
              >
                <p className="text-[10px] text-[#8a8f98]">{card.label}</p>
                <p
                  className={`mt-1 font-mono text-xl font-bold ${
                    card.positive ? "text-[#10b981]" : "text-[#e23b4a]"
                  }`}
                >
                  {card.value}
                </p>
              </div>
            ))}
          </div>

          {/* Summary row */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded border border-white/[0.08] bg-[#0f1011] p-3 text-center">
              <p className="text-[10px] text-[#8a8f98]">Total Trades</p>
              <p className="font-mono text-lg font-bold text-[#f7f8f8]">
                {result?.trades_count ?? m.total_trades ?? "--"}
              </p>
            </div>
            <div className="rounded border border-white/[0.08] bg-[#0f1011] p-3 text-center">
              <p className="text-[10px] text-[#8a8f98]">Winning Trades</p>
              <p className="font-mono text-lg font-bold text-[#f7f8f8]">
                {m.winning_trades ?? "--"}
              </p>
            </div>
            <div className="rounded border border-white/[0.08] bg-[#0f1011] p-3 text-center">
              <p className="text-[10px] text-[#8a8f98]">Total P&L</p>
              <p
                className={`font-mono text-lg font-bold ${
                  (m.total_pnl ?? 0) >= 0 ? "text-[#10b981]" : "text-[#e23b4a]"
                }`}
              >
                {fmt(m.total_pnl)}
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
