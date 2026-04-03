"use client";

import { useEffect, useState } from "react";
import { getStats, listAnalyses } from "@/lib/api";
import type { SystemStats, AnalysisStatus } from "@/lib/api";
import Link from "next/link";

export default function DashboardPage() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [recent, setRecent] = useState<AnalysisStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getStats(), listAnalyses(10)])
      .then(([s, r]) => {
        setStats(s);
        setRecent(r);
      })
      .catch(() => setError("Backend unavailable. Start the API server on :8000."));
  }, []);

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {error && (
        <div className="rounded-lg border border-yellow-700 bg-yellow-900/30 px-4 py-3 text-sm text-yellow-300">
          {error}
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Analyses Today" value={stats?.analyses_today ?? "--"} />
        <StatCard label="Total Analyses" value={stats?.analyses_total ?? "--"} />
        <StatCard label="Active Agents" value={stats?.active_agents ?? "--"} />
        <StatCard
          label="Avg Confidence"
          value={stats ? `${(stats.avg_confidence * 100).toFixed(0)}%` : "--"}
        />
      </div>

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
