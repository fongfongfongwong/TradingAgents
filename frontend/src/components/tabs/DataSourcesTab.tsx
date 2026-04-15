"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSourceHistory,
  type SourceProbeResult,
  type SourceCoverage,
} from "@/lib/api";
import { useSourceMonitor, type SortKey } from "@/hooks/useSourceMonitor";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const TIER_LABELS: Record<number, string> = {
  1: "Free",
  2: "Basic",
  3: "Pro",
  4: "Premium",
  5: "Enterprise",
};

const ALL_CATEGORIES = [
  "market_data", "news", "sentiment", "fundamentals",
  "macro", "regulatory", "alternative", "divergence", "options",
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  market_data: "Market",
  news: "News",
  sentiment: "Sentiment",
  fundamentals: "Fundamentals",
  macro: "Macro",
  regulatory: "Regulatory",
  alternative: "Alt Data",
  divergence: "Divergence",
  options: "Options",
};

const QUALITY_DIMS = [
  { key: "latency", label: "Latency", extract: (s: SourceProbeResult) => Math.max(0, 100 - s.latency_ms / 50) },
  { key: "freshness", label: "Freshness", extract: (s: SourceProbeResult) => s.freshness_seconds !== null ? Math.max(0, 100 - s.freshness_seconds / 36) : 50 },
  { key: "completeness", label: "Completeness", extract: (s: SourceProbeResult) => s.completeness_pct },
  { key: "rate_headroom", label: "Rate Headroom", extract: (s: SourceProbeResult) => 100 - s.rate_limit_pct },
  { key: "reliability", label: "Reliability", extract: (s: SourceProbeResult) => Math.max(0, 100 - s.error_rate_1h * 20) },
] as const;

const COL_HEADERS: { key: SortKey; label: string; tip: string }[] = [
  { key: "connector_name", label: "Source", tip: "Connector name" },
  { key: "status", label: "Status", tip: "ok / warn / err" },
  { key: "tier", label: "Tier", tip: "Pricing tier (1=Free…5=Enterprise)" },
  { key: "latency_ms", label: "Latency", tip: "Round-trip latency" },
  { key: "freshness_seconds", label: "Fresh", tip: "Data age" },
  { key: "completeness_pct", label: "Complete", tip: "Field completeness %" },
  { key: "rate_limit_pct", label: "Rate %", tip: "Rate limit utilization" },
  { key: "health_score", label: "Health", tip: "Composite 0-100" },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function statusDot(status: string): string {
  switch (status) {
    case "ok": return "bg-[#10b981]";
    case "warn": return "bg-[#ec7e00]";
    case "err": return "bg-[#e23b4a]";
    default: return "bg-[#8a8f98]";
  }
}

function healthColor(score: number): string {
  if (score >= 80) return "text-[#10b981]";
  if (score >= 50) return "text-[#ec7e00]";
  return "text-[#e23b4a]";
}

function healthBg(score: number): string {
  if (score >= 80) return "bg-[#10b981]";
  if (score >= 50) return "bg-[#ec7e00]";
  return "bg-[#e23b4a]";
}

function formatFreshness(seconds: number | null): string {
  if (seconds === null) return "\u2014";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function formatLatency(ms: number, reachable: boolean): string {
  if (!reachable) return "\u2014";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function relativeTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 10) return "just now";
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${(diff / 3600).toFixed(1)}h ago`;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/* ------------------------------------------------------------------ */
/*  Sparkline (pure SVG)                                               */
/* ------------------------------------------------------------------ */

function Sparkline({ data, color = "#10b981", w = 64, h = 20 }: {
  data: number[];
  color?: string;
  w?: number;
  h?: number;
}) {
  if (data.length < 2) return <span className="text-[9px] text-[#8a8f98]">--</span>;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 2) - 1;
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg width={w} height={h} className="inline-block align-middle">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Radar chart (pure SVG)                                             */
/* ------------------------------------------------------------------ */

function RadarChart({ sources, size = 220 }: {
  sources: SourceProbeResult[];
  size?: number;
}) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 24;
  const n = QUALITY_DIMS.length;
  const angleStep = (2 * Math.PI) / n;
  const radarColors = ["#10b981", "#338dff", "#ec7e00", "#e23b4a", "#a78bfa", "#f472b6"];
  const rings = [0.25, 0.5, 0.75, 1.0];

  const axes = QUALITY_DIMS.map((_, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });

  const labels = QUALITY_DIMS.map((dim, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    return { label: dim.label, x: cx + (r + 14) * Math.cos(angle), y: cy + (r + 14) * Math.sin(angle) };
  });

  const polygons = sources.map((src, si) => {
    const pts = QUALITY_DIMS.map((dim, i) => {
      const val = clamp(dim.extract(src), 0, 100) / 100;
      const angle = -Math.PI / 2 + i * angleStep;
      return `${cx + r * val * Math.cos(angle)},${cy + r * val * Math.sin(angle)}`;
    }).join(" ");
    return { name: src.connector_name, pts, color: radarColors[si % radarColors.length] };
  });

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size}>
        {rings.map((pct) => (
          <polygon
            key={pct}
            points={QUALITY_DIMS.map((_, i) => {
              const angle = -Math.PI / 2 + i * angleStep;
              return `${cx + r * pct * Math.cos(angle)},${cy + r * pct * Math.sin(angle)}`;
            }).join(" ")}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={0.5}
          />
        ))}
        {axes.map((a, i) => (
          <line key={i} x1={cx} y1={cy} x2={a.x} y2={a.y} stroke="rgba(255,255,255,0.08)" strokeWidth={0.5} />
        ))}
        {polygons.map((p) => (
          <polygon key={p.name} points={p.pts} fill={`${p.color}18`} stroke={p.color} strokeWidth={1.5} strokeLinejoin="round" />
        ))}
        {labels.map((l, i) => (
          <text key={i} x={l.x} y={l.y} textAnchor="middle" dominantBaseline="middle" className="fill-[#8a8f98] text-[8px]">{l.label}</text>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap justify-center gap-x-3 gap-y-0.5">
        {polygons.map((p) => (
          <span key={p.name} className="flex items-center gap-1 text-[9px] text-[#d1d5db]">
            <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: p.color }} />
            {p.name}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Health bar                                                         */
/* ------------------------------------------------------------------ */

function HealthBar({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1 w-12 rounded-full bg-white/[0.06]">
        <div className={`h-1 rounded-full ${healthBg(score)}`} style={{ width: `${clamp(score, 0, 100)}%` }} />
      </div>
      <span className={`font-mono text-[10px] font-bold ${healthColor(score)}`}>{score.toFixed(0)}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Inspector panel                                                    */
/* ------------------------------------------------------------------ */

function SourceInspector({ source, histories, onProbe, probing }: {
  source: SourceProbeResult;
  histories: SourceProbeResult[];
  onProbe: () => void;
  probing: boolean;
}) {
  // Also fetch fresh history for the selected connector
  const [localHistory, setLocalHistory] = useState<SourceProbeResult[]>(histories);

  useEffect(() => {
    if (histories.length > 0) {
      setLocalHistory(histories);
      return;
    }
    // Fallback: fetch if not in cache
    getSourceHistory(source.connector_name, 30)
      .then(setLocalHistory)
      .catch(() => setLocalHistory([]));
  }, [source.connector_name, source.last_probed_at, histories]);

  const history = localHistory;
  const dims = QUALITY_DIMS.map((d) => ({
    label: d.label,
    value: clamp(d.extract(source), 0, 100),
  }));

  return (
    <div className="shrink-0 border-t border-white/[0.08] bg-white/[0.02] px-3 py-2.5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-xs font-bold text-white">{source.connector_name}</h3>
          <p className="mt-0.5 text-[10px] text-[#8a8f98]">
            Tier {source.tier} ({TIER_LABELS[source.tier] ?? "Unknown"})
            {" \u2022 "}
            {source.categories.map((c) => CATEGORY_LABELS[c] ?? c).join(", ")}
          </p>
        </div>
        <button
          onClick={onProbe}
          disabled={probing}
          className="rounded border border-white/[0.1] bg-white/[0.04] px-2 py-1 text-[10px] text-[#d1d5db] transition hover:bg-white/[0.08] disabled:opacity-40"
        >
          {probing ? "Probing\u2026" : "Re-probe \u25B6"}
        </button>
      </div>

      {/* Metric grid */}
      <div className="mt-2 grid grid-cols-5 gap-3 text-[10px]">
        <MetricCell label="Latency" value={formatLatency(source.latency_ms, source.reachable)} />
        <MetricCell label="Freshness" value={formatFreshness(source.freshness_seconds)} />
        <MetricCell label="Completeness" value={`${source.completeness_pct.toFixed(0)}%`} />
        <MetricCell label="Errors (1h)" value={String(source.error_rate_1h)} color={source.error_rate_1h > 0 ? "text-[#e23b4a]" : undefined} />
        <MetricCell label="Rate Limit" value={`${source.rate_limit_pct.toFixed(0)}%`} color={source.rate_limit_pct > 80 ? "text-[#e23b4a]" : source.rate_limit_pct > 50 ? "text-[#ec7e00]" : undefined} />
      </div>

      {/* Quality dimension bars */}
      <div className="mt-2.5">
        <p className="mb-1 text-[9px] font-medium uppercase tracking-wider text-[#8a8f98]">Quality Dimensions</p>
        <div className="grid grid-cols-5 gap-2">
          {dims.map((d) => (
            <div key={d.label}>
              <div className="flex items-center justify-between text-[9px]">
                <span className="text-[#8a8f98]">{d.label}</span>
                <span className={`font-mono ${healthColor(d.value)}`}>{d.value.toFixed(0)}</span>
              </div>
              <div className="mt-0.5 h-1 w-full rounded-full bg-white/[0.06]">
                <div className={`h-1 rounded-full ${healthBg(d.value)}`} style={{ width: `${d.value}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* History sparklines */}
      {history.length > 1 && (
        <div className="mt-2.5">
          <p className="mb-1 text-[9px] font-medium uppercase tracking-wider text-[#8a8f98]">
            Trend ({history.length} probes)
          </p>
          <div className="grid grid-cols-4 gap-3">
            <div>
              <p className="text-[9px] text-[#8a8f98]">Health</p>
              <Sparkline data={history.map((h) => h.health_score)} color="#10b981" w={90} h={24} />
            </div>
            <div>
              <p className="text-[9px] text-[#8a8f98]">Latency</p>
              <Sparkline data={history.map((h) => h.latency_ms)} color="#338dff" w={90} h={24} />
            </div>
            <div>
              <p className="text-[9px] text-[#8a8f98]">Completeness</p>
              <Sparkline data={history.map((h) => h.completeness_pct)} color="#a78bfa" w={90} h={24} />
            </div>
            <div>
              <p className="text-[9px] text-[#8a8f98]">Rate %</p>
              <Sparkline data={history.map((h) => h.rate_limit_pct)} color="#ec7e00" w={90} h={24} />
            </div>
          </div>
        </div>
      )}

      {/* Detail + meta */}
      <div className="mt-2 text-[10px]">
        <p className="text-[#8a8f98]">Detail</p>
        <p className="font-mono text-[#d1d5db]">{source.detail}</p>
      </div>
      <p className="mt-1.5 text-[9px] text-[#8a8f98]">
        Probed {relativeTime(source.last_probed_at)} {" \u2022 "} Sample: {source.sample_ticker}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Coverage matrix view                                               */
/* ------------------------------------------------------------------ */

function CoverageMatrix({ sources, coverage }: {
  sources: SourceProbeResult[];
  coverage: SourceCoverage | null;
}) {
  // Build from live sources data if coverage endpoint hasn't loaded
  const categories = coverage?.categories ?? [...new Set(sources.flatMap((s) => s.categories))].sort();
  const connectors = coverage?.connectors ?? sources.map((s) => ({
    name: s.connector_name,
    tier: s.tier,
    status: s.status as "ok" | "warn" | "err" | "unknown",
    categories: s.categories,
    health_score: s.health_score,
  }));

  if (connectors.length === 0) {
    return <p className="py-6 text-center text-[10px] text-[#8a8f98]">No data sources registered</p>;
  }

  // Category coverage stats
  const catCounts = categories.map((cat) => ({
    cat,
    label: CATEGORY_LABELS[cat] ?? cat,
    total: connectors.filter((c) => c.categories.includes(cat)).length,
    healthy: connectors.filter((c) => c.categories.includes(cat) && c.status === "ok").length,
  }));

  return (
    <div className="flex flex-col gap-4 overflow-auto px-1">
      {/* Category summary bar */}
      <div>
        <p className="mb-1.5 text-[9px] font-medium uppercase tracking-wider text-[#8a8f98]">
          Category Coverage Summary
        </p>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-9">
          {catCounts.map((cc) => (
            <div key={cc.cat} className="rounded border border-white/[0.06] bg-white/[0.02] px-2 py-1.5 text-center">
              <p className="text-[9px] text-[#8a8f98]">{cc.label}</p>
              <p className={`font-mono text-sm font-bold ${cc.total === 0 ? "text-[#e23b4a]" : cc.healthy === cc.total ? "text-[#10b981]" : "text-[#ec7e00]"}`}>
                {cc.healthy}/{cc.total}
              </p>
              <div className="mt-0.5 h-1 w-full rounded-full bg-white/[0.06]">
                <div
                  className={`h-1 rounded-full ${cc.total === 0 ? "bg-[#e23b4a]" : cc.healthy === cc.total ? "bg-[#10b981]" : "bg-[#ec7e00]"}`}
                  style={{ width: cc.total > 0 ? `${(cc.healthy / cc.total) * 100}%` : "0%" }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Matrix table */}
      <div className="overflow-auto">
        <table className="w-full text-[10px]">
          <thead className="sticky top-0 z-10 bg-[#0a0d13]">
            <tr className="border-b border-white/[0.06]">
              <th className="px-2 py-1.5 text-left font-medium text-[#8a8f98]">Source</th>
              <th className="px-2 py-1.5 text-left font-medium text-[#8a8f98]">Tier</th>
              <th className="px-2 py-1.5 text-left font-medium text-[#8a8f98]">Health</th>
              {categories.map((cat) => (
                <th key={cat} className="px-1.5 py-1.5 text-center font-medium text-[#8a8f98]">
                  {(CATEGORY_LABELS[cat] ?? cat).slice(0, 6)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {connectors.map((conn) => (
              <tr key={conn.name} className="border-b border-white/[0.04] hover:bg-white/[0.04]">
                <td className="px-2 py-1.5 font-mono font-medium text-[#d1d5db]">
                  <span className="flex items-center gap-1.5">
                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${statusDot(conn.status)}`} />
                    {conn.name}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-[#d1d5db]">
                  <span className="rounded bg-white/[0.04] px-1 py-0.5 text-[9px]">T{conn.tier}</span>
                </td>
                <td className="px-2 py-1.5">
                  <HealthBar score={conn.health_score} />
                </td>
                {categories.map((cat) => {
                  const has = conn.categories.includes(cat);
                  return (
                    <td key={cat} className="px-1.5 py-1.5 text-center">
                      {has ? (
                        <span className={`inline-block h-3 w-3 rounded-sm ${conn.status === "ok" ? "bg-[#10b981]/30" : conn.status === "warn" ? "bg-[#ec7e00]/30" : "bg-[#e23b4a]/30"}`}>
                          <span className={`flex h-full items-center justify-center text-[8px] font-bold ${conn.status === "ok" ? "text-[#10b981]" : conn.status === "warn" ? "text-[#ec7e00]" : "text-[#e23b4a]"}`}>
                            {conn.status === "ok" ? "\u2713" : conn.status === "warn" ? "!" : "\u2717"}
                          </span>
                        </span>
                      ) : (
                        <span className="text-[8px] text-white/[0.1]">\u2014</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Gap analysis */}
      {catCounts.some((cc) => cc.total === 0) && (
        <div className="rounded border border-[#e23b4a]/20 bg-[#e23b4a]/5 px-3 py-2">
          <p className="text-[10px] font-medium text-[#e23b4a]">Coverage Gaps</p>
          <p className="mt-0.5 text-[10px] text-[#d1d5db]">
            No connectors registered for:{" "}
            {catCounts.filter((cc) => cc.total === 0).map((cc) => cc.label).join(", ")}
          </p>
        </div>
      )}

      {/* Redundancy analysis */}
      {catCounts.some((cc) => cc.total >= 3) && (
        <div className="rounded border border-[#10b981]/20 bg-[#10b981]/5 px-3 py-2">
          <p className="text-[10px] font-medium text-[#10b981]">Well-Covered Categories</p>
          <p className="mt-0.5 text-[10px] text-[#d1d5db]">
            3+ connectors:{" "}
            {catCounts.filter((cc) => cc.total >= 3).map((cc) => `${cc.label} (${cc.total})`).join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function DataSourcesTab() {
  const m = useSourceMonitor();

  if (m.error && m.sources.length === 0) {
    return <p className="text-xs text-[#e23b4a]">{m.error}</p>;
  }

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden">
      {/* ========== Summary Row ========== */}
      <div className="grid shrink-0 grid-cols-6 gap-2 px-1">
        <SummaryCard label="Sources" value={String(m.stats.total)} sub="registered" />
        <SummaryCard label="Healthy" value={String(m.stats.ok)} sub={`${m.stats.total > 0 ? ((m.stats.ok / m.stats.total) * 100).toFixed(0) : 0}%`} color="#10b981" />
        <SummaryCard label="Warning" value={String(m.stats.warn)} color={m.stats.warn > 0 ? "#ec7e00" : undefined} />
        <SummaryCard label="Error" value={String(m.stats.err)} color={m.stats.err > 0 ? "#e23b4a" : undefined} />
        <SummaryCard label="Avg Health" value={m.stats.avgHealth.toFixed(0)} color={m.stats.avgHealth >= 70 ? "#10b981" : m.stats.avgHealth >= 40 ? "#ec7e00" : "#e23b4a"} />
        <SummaryCard label="Avg Latency" value={m.stats.avgLatency < 1000 ? `${Math.round(m.stats.avgLatency)}ms` : `${(m.stats.avgLatency / 1000).toFixed(1)}s`} />
      </div>

      {/* ========== Toolbar ========== */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-1">
        {/* Probe All */}
        <button
          onClick={m.handleProbeAll}
          disabled={m.probing === "__all__"}
          className="rounded border border-white/[0.1] bg-white/[0.04] px-2.5 py-1 text-[10px] font-medium text-[#d1d5db] transition hover:bg-white/[0.08] disabled:opacity-40"
        >
          {m.probing === "__all__" ? "Probing\u2026" : "Probe All \u25B6"}
        </button>

        {/* View mode toggle */}
        <div className="flex rounded border border-white/[0.08] text-[10px]">
          {(["table", "compare", "coverage"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => m.setViewMode(mode)}
              className={`px-2 py-0.5 capitalize transition ${m.viewMode === mode ? "bg-white/[0.08] text-white" : "text-[#8a8f98] hover:text-white"}`}
            >
              {mode}{mode === "compare" && m.compareSet.size > 0 ? ` (${m.compareSet.size})` : ""}
            </button>
          ))}
        </div>

        <span className="h-3 w-px bg-white/[0.08]" />

        {/* Category filter chips */}
        <div className="flex flex-wrap gap-1">
          <FilterChip label="All" active={m.categoryFilter === null} onClick={() => m.setCategoryFilter(null)} />
          {ALL_CATEGORIES.map((cat) => {
            const stats = m.categoryStats[cat];
            if (!stats) return null;
            return (
              <FilterChip
                key={cat}
                label={`${CATEGORY_LABELS[cat]} (${stats.total})`}
                active={m.categoryFilter === cat}
                onClick={() => m.setCategoryFilter(m.categoryFilter === cat ? null : cat)}
                errCount={stats.err}
              />
            );
          })}
        </div>

        <div className="flex-1" />

        {/* Status filter */}
        <div className="flex gap-1">
          {(["ok", "warn", "err"] as const).map((s) => {
            const count = m.sources.filter((src) => src.status === s).length;
            if (count === 0) return null;
            return (
              <button
                key={s}
                onClick={() => m.setStatusFilter(m.statusFilter === s ? null : s)}
                className={`rounded px-1.5 py-0.5 text-[9px] transition ${
                  m.statusFilter === s
                    ? s === "ok" ? "bg-[#10b981]/20 text-[#10b981]"
                      : s === "warn" ? "bg-[#ec7e00]/20 text-[#ec7e00]"
                      : "bg-[#e23b4a]/20 text-[#e23b4a]"
                    : "text-[#8a8f98] hover:text-white"
                }`}
              >
                {s} ({count})
              </button>
            );
          })}
        </div>

        <span className="text-[9px] text-[#8a8f98]">
          {m.lastFetched ? relativeTime(m.lastFetched) : ""}{m.loading && " \u23F3"}
        </span>
      </div>

      {/* ========== Table View ========== */}
      {m.viewMode === "table" && (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-left text-[10px]">
            <thead className="sticky top-0 z-10 bg-[#0a0d13]">
              <tr className="border-b border-white/[0.06]">
                <th className="w-6 px-1 py-1.5" />
                {COL_HEADERS.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => m.handleSort(col.key)}
                    title={col.tip}
                    className="cursor-pointer select-none px-2 py-1.5 font-medium text-[#8a8f98] transition hover:text-white"
                  >
                    {col.label}
                    {m.sortKey === col.key && (
                      <span className="ml-0.5 text-[8px]">{m.sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>
                    )}
                  </th>
                ))}
                <th className="px-2 py-1.5 font-medium text-[#8a8f98]">Categories</th>
                <th className="w-16 px-2 py-1.5 font-medium text-[#8a8f98]">Trend</th>
              </tr>
            </thead>
            <tbody>
              {m.sorted.map((src) => {
                const isSelected = m.selected === src.connector_name;
                const isCompared = m.compareSet.has(src.connector_name);
                const hist = m.histories[src.connector_name];
                const sparkData = hist && hist.length > 1
                  ? hist.map((h) => h.health_score)
                  : [];

                return (
                  <tr
                    key={src.connector_name}
                    onClick={() => m.setSelected(isSelected ? null : src.connector_name)}
                    className={`cursor-pointer border-b border-white/[0.04] transition hover:bg-white/[0.04] ${isSelected ? "bg-white/[0.06]" : ""}`}
                  >
                    <td className="px-1 py-1.5">
                      <input
                        type="checkbox"
                        checked={isCompared}
                        onChange={(e) => { e.stopPropagation(); m.toggleCompare(src.connector_name); }}
                        onClick={(e) => e.stopPropagation()}
                        className="h-3 w-3 cursor-pointer accent-[#338dff]"
                      />
                    </td>
                    <td className="px-2 py-1.5 font-mono font-medium text-[#d1d5db]">{src.connector_name}</td>
                    <td className="px-2 py-1.5">
                      <span className="flex items-center gap-1">
                        <span className={`inline-block h-1.5 w-1.5 rounded-full ${statusDot(src.status)}`} />
                        <span className="text-[#d1d5db]">{src.status}</span>
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-[#d1d5db]">
                      <span className="rounded bg-white/[0.04] px-1 py-0.5 text-[9px]">T{src.tier}</span>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[#d1d5db]">{formatLatency(src.latency_ms, src.reachable)}</td>
                    <td className="px-2 py-1.5 font-mono text-[#d1d5db]">{formatFreshness(src.freshness_seconds)}</td>
                    <td className="px-2 py-1.5 font-mono text-[#d1d5db]">{src.reachable ? `${src.completeness_pct.toFixed(0)}%` : "\u2014"}</td>
                    <td className="px-2 py-1.5 font-mono">
                      <span className={src.rate_limit_pct > 80 ? "text-[#e23b4a]" : src.rate_limit_pct > 50 ? "text-[#ec7e00]" : "text-[#d1d5db]"}>
                        {src.rate_limit_pct.toFixed(0)}%
                      </span>
                    </td>
                    <td className="px-2 py-1.5"><HealthBar score={src.health_score} /></td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-wrap gap-0.5">
                        {src.categories.slice(0, 2).map((c) => (
                          <span key={c} className="rounded bg-white/[0.04] px-1 py-0.5 text-[8px] text-[#8a8f98]">{CATEGORY_LABELS[c] ?? c}</span>
                        ))}
                        {src.categories.length > 2 && <span className="text-[8px] text-[#8a8f98]">+{src.categories.length - 2}</span>}
                      </div>
                    </td>
                    <td className="px-2 py-1.5">
                      <Sparkline
                        data={sparkData}
                        color={src.status === "ok" ? "#10b981" : src.status === "warn" ? "#ec7e00" : "#e23b4a"}
                        w={48}
                        h={16}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {m.sorted.length === 0 && (
            <p className="py-6 text-center text-[10px] text-[#8a8f98]">
              {m.sources.length === 0 ? "No data sources registered" : "No sources match filters"}
            </p>
          )}
        </div>
      )}

      {/* ========== Compare View ========== */}
      {m.viewMode === "compare" && (
        <div className="flex-1 overflow-auto px-2">
          {m.compareSources.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2">
              <p className="text-xs text-[#8a8f98]">Select sources to compare using checkboxes in Table view</p>
              <button
                onClick={() => m.setViewMode("table")}
                className="rounded border border-white/[0.1] bg-white/[0.04] px-3 py-1 text-[10px] text-[#d1d5db] transition hover:bg-white/[0.08]"
              >
                Go to Table
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-[1fr_auto] gap-4">
              <div className="flex items-center justify-center">
                <RadarChart sources={m.compareSources} size={240} />
              </div>
              <div className="min-w-[300px] overflow-auto">
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="px-2 py-1.5 text-left font-medium text-[#8a8f98]">Metric</th>
                      {m.compareSources.map((s) => (
                        <th key={s.connector_name} className="px-2 py-1.5 text-right font-mono font-medium text-[#d1d5db]">{s.connector_name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <CompareRow label="Health" values={m.compareSources.map((s) => ({ v: s.health_score.toFixed(0), color: healthColor(s.health_score) }))} />
                    <CompareRow label="Status" values={m.compareSources.map((s) => ({ v: s.status, color: s.status === "ok" ? "text-[#10b981]" : s.status === "warn" ? "text-[#ec7e00]" : "text-[#e23b4a]" }))} />
                    <CompareRow label="Latency" values={m.compareSources.map((s) => ({ v: formatLatency(s.latency_ms, s.reachable) }))} />
                    <CompareRow label="Freshness" values={m.compareSources.map((s) => ({ v: formatFreshness(s.freshness_seconds) }))} />
                    <CompareRow label="Complete" values={m.compareSources.map((s) => ({ v: `${s.completeness_pct.toFixed(0)}%` }))} />
                    <CompareRow label="Rate %" values={m.compareSources.map((s) => ({ v: `${s.rate_limit_pct.toFixed(0)}%`, color: s.rate_limit_pct > 80 ? "text-[#e23b4a]" : s.rate_limit_pct > 50 ? "text-[#ec7e00]" : undefined }))} />
                    <CompareRow label="Errors/h" values={m.compareSources.map((s) => ({ v: String(s.error_rate_1h), color: s.error_rate_1h > 0 ? "text-[#e23b4a]" : undefined }))} />
                    <CompareRow label="Tier" values={m.compareSources.map((s) => ({ v: `T${s.tier} ${TIER_LABELS[s.tier] ?? ""}` }))} />
                    {QUALITY_DIMS.map((dim) => (
                      <CompareRow
                        key={dim.key}
                        label={dim.label}
                        values={m.compareSources.map((s) => {
                          const v = clamp(dim.extract(s), 0, 100);
                          return { v: v.toFixed(0), color: healthColor(v) };
                        })}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========== Coverage View ========== */}
      {m.viewMode === "coverage" && (
        <div className="flex-1 overflow-auto">
          <CoverageMatrix sources={m.sources} coverage={m.coverage} />
        </div>
      )}

      {/* ========== Detail Inspector ========== */}
      {m.selectedSource && m.viewMode === "table" && (
        <SourceInspector
          source={m.selectedSource}
          histories={m.histories[m.selectedSource.connector_name] ?? []}
          onProbe={() => m.handleProbeOne(m.selectedSource!.connector_name)}
          probing={m.probing === m.selectedSource.connector_name}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Small sub-components                                               */
/* ------------------------------------------------------------------ */

function SummaryCard({ label, value, sub, color }: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="rounded border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5">
      <p className="text-[9px] text-[#8a8f98]">{label}</p>
      <p className="font-mono text-sm font-bold" style={color ? { color } : { color: "#d1d5db" }}>{value}</p>
      {sub && <p className="text-[9px] text-[#8a8f98]">{sub}</p>}
    </div>
  );
}

function MetricCell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <p className="text-[#8a8f98]">{label}</p>
      <p className={`font-mono font-bold ${color ?? "text-white"}`}>{value}</p>
    </div>
  );
}

function FilterChip({ label, active, onClick, errCount }: {
  label: string;
  active: boolean;
  onClick: () => void;
  errCount?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded px-1.5 py-0.5 text-[9px] transition ${
        active ? "bg-[#338dff]/20 text-[#338dff]" : "text-[#8a8f98] hover:bg-white/[0.04] hover:text-white"
      }`}
    >
      {label}
      {(errCount ?? 0) > 0 && <span className="ml-0.5 text-[#e23b4a]">{errCount}</span>}
    </button>
  );
}

function CompareRow({ label, values }: {
  label: string;
  values: { v: string; color?: string }[];
}) {
  return (
    <tr className="border-b border-white/[0.04]">
      <td className="px-2 py-1 text-[#8a8f98]">{label}</td>
      {values.map((val, i) => (
        <td key={i} className={`px-2 py-1 text-right font-mono ${val.color ?? "text-[#d1d5db]"}`}>{val.v}</td>
      ))}
    </tr>
  );
}
