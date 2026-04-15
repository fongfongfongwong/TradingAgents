"use client";

import { useEffect, useState } from "react";
import { getStats, getPortfolio, type SystemStats, type PortfolioSummary } from "@/lib/api";

export default function StatusBar() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    getPortfolio().then(setPortfolio).catch(() => {});

    const interval = setInterval(() => {
      getStats().then(setStats).catch(() => {});
      getPortfolio().then(setPortfolio).catch(() => {});
    }, 10_000);
    return () => clearInterval(interval);
  }, []);

  const fmt = (n: number) =>
    n.toLocaleString("en-US", { style: "currency", currency: "USD" });

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-white/[0.08] bg-[#0f1011] px-4 text-[10px] text-[#8a8f98]">
      {/* Agents */}
      <span>
        <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-[#10b981]" />
        {stats ? `${stats.active_agents} agents` : "0 agents"}
      </span>

      <div className="h-3 w-px bg-white/[0.08]" />

      {/* Stats */}
      <span>{stats ? `${stats.analyses_total} analyses` : "--"}</span>
      <span>
        Avg conf:{" "}
        {stats ? `${(stats.avg_confidence * 100).toFixed(0)}%` : "--"}
      </span>

      <div className="h-3 w-px bg-white/[0.08]" />

      {/* Portfolio */}
      <span>
        Portfolio:{" "}
        {portfolio ? fmt(portfolio.total_value) : "--"}
      </span>
      {portfolio && portfolio.total_pnl !== 0 && (
        <span
          className={
            portfolio.total_pnl > 0 ? "text-[#10b981]" : "text-[#e23b4a]"
          }
        >
          {portfolio.total_pnl > 0 ? "+" : ""}
          {fmt(portfolio.total_pnl)}
        </span>
      )}

      <div className="flex-1" />

      {/* Right side */}
      <span>v2.0.0</span>
    </footer>
  );
}
