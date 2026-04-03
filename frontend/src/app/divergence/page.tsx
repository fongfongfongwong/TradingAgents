"use client";

import { useState, type FormEvent } from "react";
import { getDivergence } from "@/lib/api";
import type { DivergenceData } from "@/lib/api";
import DivergenceChart from "@/components/DivergenceChart";

export default function DivergencePage() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DivergenceData | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!ticker.trim()) return;

    setLoading(true);
    setError(null);
    setData(null);

    try {
      const result = await getDivergence(ticker.toUpperCase().trim());
      setData(result);
    } catch {
      setError("Failed to fetch divergence data. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Agent Divergence</h1>
      <p className="text-sm text-gray-400">
        View how different agents diverge in their bull/bear assessments across
        analytical dimensions.
      </p>

      {/* Ticker input */}
      <form
        onSubmit={handleSubmit}
        className="flex items-end gap-4 rounded-lg border border-gray-800 bg-gray-800/30 p-5"
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
      </form>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {data && (
        <div className="space-y-6">
          {/* Overall score */}
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold">{data.ticker}</h2>
            <span className="rounded-full bg-gray-800 px-3 py-1 text-sm">
              Overall Divergence:{" "}
              <span className="font-bold text-yellow-300">
                {data.overall_score.toFixed(2)}
              </span>
            </span>
          </div>

          {/* Chart */}
          <DivergenceChart dimensions={data.dimensions} />

          {/* Dimension table */}
          <div className="overflow-hidden rounded-lg border border-gray-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-800 bg-gray-800/40 text-xs uppercase text-gray-400">
                <tr>
                  <th className="px-4 py-3">Dimension</th>
                  <th className="px-4 py-3">Bull Score</th>
                  <th className="px-4 py-3">Bear Score</th>
                  <th className="px-4 py-3">Divergence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {data.dimensions.map((dim) => (
                  <tr key={dim.name} className="hover:bg-gray-800/30">
                    <td className="px-4 py-3 font-medium">{dim.name}</td>
                    <td className="px-4 py-3 text-green-400">
                      {dim.bull_score.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-red-400">
                      {dim.bear_score.toFixed(2)}
                    </td>
                    <td className="px-4 py-3">
                      <DivergenceBar value={dim.divergence} />
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
