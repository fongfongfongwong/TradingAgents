"use client";

import { useState, type FormEvent } from "react";
import { getDivergence } from "@/lib/api";
import type { DivergenceData } from "@/lib/api";
import DivergenceChart from "@/components/DivergenceChart";

const DIMENSION_INFO: Record<string, { label: string; desc: string }> = {
  institutional: { label: "Institutional", desc: "Large-cap flow, dark pool activity, 13F filings" },
  options: { label: "Options", desc: "Put/call ratio, unusual activity, IV skew" },
  price_action: { label: "Price Action", desc: "Trend, momentum, support/resistance levels" },
  news: { label: "News", desc: "Sentiment from headlines, earnings, press releases" },
  retail: { label: "Retail", desc: "Reddit, StockTwits, social media positioning" },
};

const QUICK_TICKERS = ["SPY", "AAPL", "TSLA", "NVDA", "MSFT", "AMZN"];

export default function DivergencePage() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DivergenceData | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function fetchTicker(t: string) {
    if (!t.trim()) return;
    setLoading(true);
    setError(null);
    setData(null);
    setTicker(t.toUpperCase());

    try {
      const result = await getDivergence(t.toUpperCase().trim());
      setData(result);
    } catch {
      setError("Failed to fetch divergence data. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    fetchTicker(ticker);
  }

  // Derive regime and composite from data
  const composite = data ? data.overall_score : null;
  const regime =
    composite !== null
      ? composite > 0.3
        ? "RISK_ON"
        : composite < -0.3
          ? "RISK_OFF"
          : "TRANSITIONING"
      : null;

  const regimeColors: Record<string, string> = {
    RISK_ON: "bg-green-900/50 text-green-300 border-green-700",
    RISK_OFF: "bg-red-900/50 text-red-300 border-red-700",
    TRANSITIONING: "bg-yellow-900/50 text-yellow-300 border-yellow-700",
  };

  const compositeLabel =
    composite !== null
      ? composite > 0.15
        ? "Bullish"
        : composite < -0.15
          ? "Bearish"
          : "Neutral"
      : null;

  const compositeLabelColor =
    compositeLabel === "Bullish"
      ? "text-green-400"
      : compositeLabel === "Bearish"
        ? "text-red-400"
        : "text-yellow-300";

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Agent Divergence</h1>
        <p className="text-sm text-gray-400">
          5-dimensional divergence analysis across institutional, options, price action, news, and retail signals.
        </p>
      </div>

      {/* Dimension Legend */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
          5 Divergence Dimensions
        </h2>
        <div className="flex flex-wrap gap-2">
          {Object.entries(DIMENSION_INFO).map(([key, info]) => (
            <div
              key={key}
              className="rounded-md border border-gray-700 bg-gray-800/40 px-3 py-1.5"
            >
              <span className="text-xs font-semibold text-brand-400">{info.label}</span>
              <span className="ml-2 text-xs text-gray-500">{info.desc}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Ticker input */}
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
            className="w-32 rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className="rounded-md bg-brand-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Fetch Divergence"}
        </button>

        {/* Quick ticker buttons */}
        <div className="flex flex-wrap gap-1.5">
          {QUICK_TICKERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => fetchTicker(t)}
              disabled={loading}
              className={`rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                data?.ticker === t
                  ? "border-brand-500 bg-brand-900/30 text-brand-300"
                  : "border-gray-700 bg-gray-800/50 text-gray-400 hover:border-gray-600 hover:text-white"
              } disabled:opacity-40`}
            >
              {t}
            </button>
          ))}
        </div>
      </form>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {data && (
        <div className="space-y-6">
          {/* Header: Ticker + Regime Badge + Composite Score */}
          <div className="flex flex-wrap items-center gap-4">
            <h2 className="text-2xl font-bold text-white">{data.ticker}</h2>

            {regime && (
              <span
                className={`rounded-full border px-3 py-1 text-xs font-bold ${regimeColors[regime]}`}
              >
                {regime.replace("_", " ")}
              </span>
            )}

            {composite !== null && (
              <div className="flex items-center gap-2 rounded-full bg-gray-800 px-4 py-1">
                <span className="text-xs text-gray-400">Composite:</span>
                <span className={`text-lg font-bold ${compositeLabelColor}`}>
                  {composite > 0 ? "+" : ""}
                  {composite.toFixed(3)}
                </span>
                <span className={`text-xs font-semibold ${compositeLabelColor}`}>
                  {compositeLabel}
                </span>
              </div>
            )}
          </div>

          {/* 5-Dimension Visual Bars */}
          <div className="rounded-lg border border-gray-800 bg-gray-800/20 p-5">
            <h3 className="mb-4 text-sm font-semibold text-gray-300">
              Dimension Scores (-1.0 Bearish to +1.0 Bullish)
            </h3>
            <div className="space-y-4">
              {data.dimensions.map((dim) => {
                const net = dim.bull_score - dim.bear_score;
                const pctFromCenter = net * 50; // -50 to +50
                return (
                  <div key={dim.name} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium text-gray-300">
                        {DIMENSION_INFO[dim.name]?.label ?? dim.name}
                      </span>
                      <span
                        className={`font-bold ${
                          net > 0.1
                            ? "text-green-400"
                            : net < -0.1
                              ? "text-red-400"
                              : "text-yellow-300"
                        }`}
                      >
                        {net > 0 ? "+" : ""}
                        {net.toFixed(2)}
                      </span>
                    </div>
                    {/* Centered bar: center is 0, left is bearish, right is bullish */}
                    <div className="relative h-5 w-full overflow-hidden rounded-full bg-gray-700">
                      {/* Center line */}
                      <div className="absolute left-1/2 top-0 h-full w-px bg-gray-500" />
                      {/* Score bar */}
                      {net >= 0 ? (
                        <div
                          className="absolute top-0 h-full rounded-r-full bg-green-500/80"
                          style={{
                            left: "50%",
                            width: `${Math.min(Math.abs(pctFromCenter), 50)}%`,
                          }}
                        />
                      ) : (
                        <div
                          className="absolute top-0 h-full rounded-l-full bg-red-500/80"
                          style={{
                            right: "50%",
                            width: `${Math.min(Math.abs(pctFromCenter), 50)}%`,
                          }}
                        />
                      )}
                    </div>
                    <div className="flex justify-between text-xs text-gray-600">
                      <span>-1.0 Bear</span>
                      <span>0</span>
                      <span>+1.0 Bull</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recharts Chart */}
          <DivergenceChart dimensions={data.dimensions} />

          {/* Dimension table */}
          <div className="overflow-hidden rounded-lg border border-gray-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-800 bg-gray-800/40 text-xs uppercase text-gray-400">
                <tr>
                  <th className="px-4 py-3">Dimension</th>
                  <th className="px-4 py-3">Bull Score</th>
                  <th className="px-4 py-3">Bear Score</th>
                  <th className="px-4 py-3">Net</th>
                  <th className="px-4 py-3">Divergence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {data.dimensions.map((dim) => {
                  const net = dim.bull_score - dim.bear_score;
                  return (
                    <tr key={dim.name} className="hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-medium">
                        {DIMENSION_INFO[dim.name]?.label ?? dim.name}
                      </td>
                      <td className="px-4 py-3 text-green-400">
                        {dim.bull_score.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-red-400">
                        {dim.bear_score.toFixed(2)}
                      </td>
                      <td
                        className={`px-4 py-3 font-semibold ${
                          net > 0.1
                            ? "text-green-400"
                            : net < -0.1
                              ? "text-red-400"
                              : "text-yellow-300"
                        }`}
                      >
                        {net > 0 ? "+" : ""}
                        {net.toFixed(2)}
                      </td>
                      <td className="px-4 py-3">
                        <DivergenceBar value={dim.divergence} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function DivergenceBar({ value }: { value: number }) {
  const pct = Math.min(Math.abs(value) * 100, 100);
  const color =
    pct > 60 ? "bg-red-500" : pct > 30 ? "bg-yellow-500" : "bg-green-500";

  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-gray-700">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400">{value.toFixed(2)}</span>
    </div>
  );
}
