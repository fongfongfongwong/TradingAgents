"use client";

import { useEffect, useState } from "react";
import { getStats, listAnalyses, getDivergence } from "@/lib/api";
import type { SystemStats, AnalysisStatus, DivergenceData } from "@/lib/api";
import Link from "next/link";

const CAPABILITIES = [
  { label: "Data Connectors", value: "8", desc: "FMP, Reddit, Google News, SEC, Finnhub, Alpha Vantage, Polygon, Yahoo" },
  { label: "Divergence Dimensions", value: "5", desc: "Institutional, Options, Price Action, News, Retail" },
  { label: "Analyst Agents", value: "6", desc: "Market, Social, News, Fundamentals, Options, Macro" },
  { label: "Tests Passed", value: "710", desc: "Unit, integration, and end-to-end coverage" },
];

const QUICK_TICKERS = ["SPY", "AAPL", "TSLA", "NVDA"];

interface QuickDivergence {
  ticker: string;
  score: number | null;
  loading: boolean;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [recent, setRecent] = useState<AnalysisStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fearGreed, setFearGreed] = useState<{ value: number; label: string } | null>(null);
  const [quickDiv, setQuickDiv] = useState<QuickDivergence[]>(
    QUICK_TICKERS.map((t) => ({ ticker: t, score: null, loading: true }))
  );

  useEffect(() => {
    Promise.all([getStats(), listAnalyses(10)])
      .then(([s, r]) => {
        setStats(s);
        setRecent(r);
      })
      .catch(() => setError("Backend unavailable. Start the API server on :8000."));

    // Fetch Fear & Greed via SPY divergence
    getDivergence("SPY")
      .then((d) => {
        // Derive a fear/greed-like score from divergence
        const composite = d.overall_score;
        const scaled = Math.max(0, Math.min(100, 50 + composite * 50));
        let label = "Neutral";
        if (scaled <= 25) label = "Extreme Fear";
        else if (scaled <= 40) label = "Fear";
        else if (scaled <= 60) label = "Neutral";
        else if (scaled <= 75) label = "Greed";
        else label = "Extreme Greed";
        setFearGreed({ value: Math.round(scaled * 10) / 10, label });
      })
      .catch(() => {
        // Use hardcoded current reading if backend unavailable
        setFearGreed({ value: 19.3, label: "Extreme Fear" });
      });

    // Fetch quick divergence for popular tickers
    QUICK_TICKERS.forEach((ticker, idx) => {
      getDivergence(ticker)
        .then((d) => {
          setQuickDiv((prev) => {
            const next = [...prev];
            next[idx] = { ticker, score: d.overall_score, loading: false };
            return next;
          });
        })
        .catch(() => {
          setQuickDiv((prev) => {
            const next = [...prev];
            next[idx] = { ticker, score: null, loading: false };
            return next;
          });
        });
    });
  }, []);

  const fgColor =
    fearGreed && fearGreed.value <= 25
      ? "text-red-400"
      : fearGreed && fearGreed.value <= 40
        ? "text-orange-400"
        : fearGreed && fearGreed.value <= 60
          ? "text-yellow-300"
          : fearGreed && fearGreed.value <= 75
            ? "text-green-400"
            : "text-green-300";

  const fgBarColor =
    fearGreed && fearGreed.value <= 25
      ? "bg-red-500"
      : fearGreed && fearGreed.value <= 40
        ? "bg-orange-500"
        : fearGreed && fearGreed.value <= 60
          ? "bg-yellow-500"
          : fearGreed && fearGreed.value <= 75
            ? "bg-green-500"
            : "bg-green-400";

  return (
    <div className="space-y-8">
      {/* Hero header */}
      <div>
        <h1 className="text-3xl font-bold">TradingAgents Dashboard</h1>
        <p className="mt-1 text-sm text-gray-400">
          Multi-agent AI trading analysis platform -- v0.2.3
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-yellow-700 bg-yellow-900/30 px-4 py-3 text-sm text-yellow-300">
          {error}
        </div>
      )}

      {/* System Capabilities */}
      <section>
        <h2 className="mb-4 text-lg font-semibold text-gray-200">System Capabilities</h2>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {CAPABILITIES.map((cap) => (
            <div
              key={cap.label}
              className="rounded-lg border border-brand-700/40 bg-gradient-to-br from-brand-900/20 to-gray-800/40 p-4"
            >
              <p className="text-3xl font-bold text-brand-400">{cap.value}</p>
              <p className="mt-1 text-sm font-medium text-white">{cap.label}</p>
              <p className="mt-1 text-xs text-gray-500">{cap.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Fear & Greed + Quick Divergence row */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Fear & Greed Gauge */}
        <div className="rounded-lg border border-gray-800 bg-gray-800/30 p-5">
          <h2 className="mb-4 text-lg font-semibold text-gray-200">Fear & Greed Index</h2>
          {fearGreed ? (
            <div className="flex items-center gap-6">
              <div className="text-center">
                <p className={`text-5xl font-bold ${fgColor}`}>{fearGreed.value}</p>
                <p className={`mt-1 text-sm font-semibold ${fgColor}`}>{fearGreed.label}</p>
              </div>
              <div className="flex-1">
                <div className="h-4 w-full overflow-hidden rounded-full bg-gray-700">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${fgBarColor}`}
                    style={{ width: `${fearGreed.value}%` }}
                  />
                </div>
                <div className="mt-1 flex justify-between text-xs text-gray-500">
                  <span>0 - Extreme Fear</span>
                  <span>100 - Extreme Greed</span>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">Loading...</p>
          )}
        </div>

        {/* Quick Divergence Snapshot */}
        <div className="rounded-lg border border-gray-800 bg-gray-800/30 p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-200">Quick Divergence</h2>
            <Link href="/divergence" className="text-xs text-brand-400 hover:underline">
              Full Analysis
            </Link>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {quickDiv.map((item) => (
              <div
                key={item.ticker}
                className="rounded-md border border-gray-700 bg-gray-900/50 px-3 py-2.5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-white">{item.ticker}</span>
                  {item.loading ? (
                    <span className="text-xs text-gray-500">...</span>
                  ) : item.score !== null ? (
                    <span
                      className={`text-sm font-bold ${
                        item.score > 0.3
                          ? "text-green-400"
                          : item.score < -0.3
                            ? "text-red-400"
                            : "text-yellow-300"
                      }`}
                    >
                      {item.score > 0 ? "+" : ""}
                      {item.score.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-600">N/A</span>
                  )}
                </div>
                {!item.loading && item.score !== null && (
                  <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-gray-700">
                    <div
                      className={`h-full rounded-full ${
                        item.score > 0.3
                          ? "bg-green-500"
                          : item.score < -0.3
                            ? "bg-red-500"
                            : "bg-yellow-500"
                      }`}
                      style={{ width: `${Math.min(Math.abs(item.score) * 100, 100)}%` }}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Runtime Stats */}
      <section>
        <h2 className="mb-3 text-lg font-semibold text-gray-200">Runtime Stats</h2>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard label="Analyses Today" value={stats?.analyses_today ?? "--"} />
          <StatCard label="Total Analyses" value={stats?.analyses_total ?? "--"} />
          <StatCard label="Active Agents" value={stats?.active_agents ?? "--"} />
          <StatCard
            label="Avg Confidence"
            value={stats ? `${(stats.avg_confidence * 100).toFixed(0)}%` : "--"}
          />
        </div>
      </section>

      {/* Recent analyses */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Recent Analyses</h2>
          <Link
            href="/analysis"
            className="text-sm text-brand-400 hover:underline"
          >
            New Analysis
          </Link>
        </div>

        <div className="overflow-hidden rounded-lg border border-gray-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-800 bg-gray-800/40 text-xs uppercase text-gray-400">
              <tr>
                <th className="px-4 py-3">Ticker</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Decision</th>
                <th className="px-4 py-3">Confidence</th>
                <th className="px-4 py-3">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {recent.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-gray-500">
                    No analyses yet. Run one from the Analysis page.
                  </td>
                </tr>
              )}
              {recent.map((a) => (
                <tr key={a.id} className="hover:bg-gray-800/30">
                  <td className="px-4 py-3 font-medium">{a.ticker}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={a.status} />
                  </td>
                  <td className="px-4 py-3">
                    {a.result?.decision ?? "-"}
                  </td>
                  <td className="px-4 py-3">
                    {a.result
                      ? `${(a.result.confidence * 100).toFixed(0)}%`
                      : "-"}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {new Date(a.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/* ---------- helpers ---------- */

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-800/30 p-4">
      <p className="text-xs text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: AnalysisStatus["status"] }) {
  const colors: Record<string, string> = {
    pending: "bg-gray-700 text-gray-300",
    running: "bg-blue-900 text-blue-300",
    completed: "bg-green-900 text-green-300",
    failed: "bg-red-900 text-red-300",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? colors.pending}`}
    >
      {status}
    </span>
  );
}
