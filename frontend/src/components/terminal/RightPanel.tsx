"use client";

import { useEffect, useState } from "react";
import type { TabId } from "@/app/page";
import { useTicker } from "@/hooks/useTicker";
import {
  getScoredNews,
  getDivergence,
  type ScoredHeadline,
  type DivergenceData,
} from "@/lib/api";
import AgentPipelineMini from "./AgentPipelineMini";

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffSec = Math.max(0, (Date.now() - then) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

const DIRECTION_CHIP_CLASSES: Record<ScoredHeadline["direction"], string> = {
  LONG: "text-[#10b981] bg-[#10b981]/10 border-[#10b981]/30",
  SHORT: "text-[#e23b4a] bg-[#e23b4a]/10 border-[#e23b4a]/30",
  NEUTRAL: "text-[#8a8f98] bg-white/[0.04] border-white/[0.08]",
};

interface Props {
  activeTab: TabId;
}

export default function RightPanel({ activeTab }: Props) {
  return (
    <aside className="flex h-full w-full flex-col bg-[#0d1218]">
      <div className="shrink-0 min-h-[200px]">
        <DivergenceMini />
      </div>
      <div className="shrink-0 min-h-[160px]">
        <AgentPipelineMini />
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        <NewsFeed />
      </div>
    </aside>
  );
}

/* ---- News Feed ---- */

function NewsFeed() {
  const { ticker } = useTicker();
  const [news, setNews] = useState<ScoredHeadline[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getScoredNews(ticker, 20)
      .then(setNews)
      .catch(() => setNews([]))
      .finally(() => setLoading(false));
  }, [ticker]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="border-b border-white/[0.08] px-3 py-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.7px] text-[#6e7a91]">
          News — {ticker}
        </h2>
      </div>

      {loading && (
        <p className="px-3 py-4 text-[11px] text-[#62666d]">Loading news...</p>
      )}

      {!loading && news.length === 0 && (
        <p className="px-3 py-4 text-[11px] text-[#62666d]">
          No news available.
        </p>
      )}

      <div className="divide-y divide-white/[0.03]">
        {news.map((item, i) => {
          const impact = Math.round(item.impact_score * 100);
          const chipClass = DIRECTION_CHIP_CLASSES[item.direction];
          const visibleTags = item.tags.slice(0, 3);
          const extraTags = item.tags.length - visibleTags.length;
          const relativeTime = formatRelativeTime(item.published_at);
          const titleNode = item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[11px] font-medium leading-tight text-[#d0d6e0] hover:text-white"
            >
              {item.title}
            </a>
          ) : (
            <span className="text-[11px] font-medium leading-tight text-[#d0d6e0]">
              {item.title}
            </span>
          );

          return (
            <div key={item.url ?? `${item.title}-${i}`} className="px-3 py-2 hover:bg-white/[0.02]">
              <div className="flex items-start gap-2">
                <span
                  className={`shrink-0 rounded border px-1 py-[1px] font-mono text-[9px] font-bold ${chipClass}`}
                >
                  {item.direction} {impact}
                </span>
                <div className="min-w-0 flex-1">{titleNode}</div>
              </div>

              <div className="mt-1 flex items-center gap-2 text-[9px] text-[#62666d]">
                {item.source && <span>{item.source}</span>}
                {item.source && relativeTime && <span>·</span>}
                {relativeTime && <span>{relativeTime}</span>}
              </div>

              {visibleTags.length > 0 && (
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {visibleTags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded bg-white/[0.04] px-1 py-[1px] text-[9px] text-[#8a8f98]"
                    >
                      {tag}
                    </span>
                  ))}
                  {extraTags > 0 && (
                    <span className="text-[9px] text-[#62666d]">
                      +{extraTags} more
                    </span>
                  )}
                </div>
              )}

              <p className="mt-1 text-[9px] italic text-[#62666d]">
                {item.rationale}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---- Divergence Mini ---- */

function biasLabel(composite: number): { label: string; className: string } {
  if (composite > 0.15)
    return { label: "BULLISH BIAS", className: "text-[#10b981] border-[#10b981]/30" };
  if (composite > 0.05)
    return { label: "BULLISH LEAN", className: "text-[#10b981]/70 border-[#10b981]/20" };
  if (composite >= -0.05)
    return { label: "NEUTRAL", className: "text-[#8a8f98] border-[#8a8f98]/30" };
  if (composite > -0.15)
    return { label: "BEARISH LEAN", className: "text-[#e23b4a]/70 border-[#e23b4a]/20" };
  return { label: "BEARISH BIAS", className: "text-[#e23b4a] border-[#e23b4a]/30" };
}

function confidenceOpacity(confidence: number): string {
  if (confidence >= 0.6) return "opacity-100";
  if (confidence >= 0.3) return "opacity-60";
  return "opacity-35";
}

const DIMENSION_WEIGHTS: Record<string, number> = {
  institutional: 0.35,
  options: 0.25,
  price_action: 0.20,
  news: 0.15,
  retail: 0.05,
};

function DivergenceMini() {
  const { ticker } = useTicker();
  const [data, setData] = useState<DivergenceData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setError(false);
    getDivergence(ticker)
      .then(setData)
      .catch(() => {
        setData(null);
        setError(true);
      });
  }, [ticker]);

  const dims = data
    ? Object.entries(data.dimensions).map(([name, d]) => ({
        name,
        value: d.value,
        confidence: d.confidence,
      }))
    : [];

  const barColor = (v: number) => {
    if (v > 0.15) return "bg-[#10b981]";
    if (v < -0.15) return "bg-[#e23b4a]";
    return "bg-[#ec7e00]";
  };

  const bias = data ? biasLabel(data.composite_score) : null;

  return (
    <div className="shrink-0 border-t border-white/[0.08]" data-testid="divergence-mini">
      <div className="flex items-center justify-between px-3 py-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.7px] text-[#6e7a91]">
          Divergence
        </h2>
        {bias && (
          <span
            data-testid="bias-label"
            className={`rounded-full border px-1.5 py-0.5 text-[9px] font-mono font-bold ${bias.className}`}
          >
            {bias.label}
          </span>
        )}
      </div>

      {data && (
        <div className="px-3 pb-3">
          <div className="mb-2 text-center">
            <span
              className={`font-mono text-[28px] font-bold ${
                data.composite_score > 0.15
                  ? "text-[#10b981]"
                  : data.composite_score < -0.15
                    ? "text-[#e23b4a]"
                    : "text-[#ec7e00]"
              }`}
            >
              {data.composite_score > 0 ? "+" : ""}
              {data.composite_score.toFixed(3)}
            </span>
          </div>

          <div className="space-y-1.5">
            {dims.map((d) => {
              const opacityClass = confidenceOpacity(d.confidence);
              return (
                <div
                  key={d.name}
                  className={`flex items-center gap-2 ${opacityClass}`}
                  data-testid={`dim-row-${d.name}`}
                >
                  <span className="w-16 truncate text-[10px] capitalize text-[#9ba7bb]">
                    {d.name.replace(/_/g, " ")}
                  </span>
                  <div className="relative h-[5px] flex-1 overflow-hidden rounded-full bg-[#1c2230]">
                    <div
                      className={`absolute top-0 h-full rounded-full ${barColor(d.value)}`}
                      style={{
                        left: d.value >= 0 ? "50%" : `${50 + d.value * 50}%`,
                        width: `${Math.abs(d.value) * 50}%`,
                      }}
                    />
                    {/* Center line */}
                    <div className="absolute left-1/2 top-0 h-full w-px bg-white/[0.15]" />
                  </div>
                  <span
                    className={`w-10 text-right font-mono text-[10px] ${
                      d.value > 0 ? "text-[#10b981]" : d.value < 0 ? "text-[#e23b4a]" : "text-[#8a8f98]"
                    }`}
                    data-testid={`dim-value-${d.name}`}
                  >
                    {d.value > 0 ? "+" : ""}
                    {d.value.toFixed(3)}
                  </span>
                </div>
              );
            })}
          </div>

          <p className="mt-2 text-center text-[8px] text-[#62666d]" data-testid="weights-text">
            weights:{" "}
            {Object.entries(DIMENSION_WEIGHTS)
              .map(([k, w]) => `${k.slice(0, 4)} ${w.toFixed(2)}`)
              .join(" \u00B7 ")}
          </p>
        </div>
      )}

      {!data && !error && (
        <p className="px-3 pb-3 text-[10px] text-[#62666d]">Loading...</p>
      )}

      {error && (
        <p className="px-3 pb-3 text-[10px] text-[#e23b4a]">Failed to load divergence</p>
      )}
    </div>
  );
}

export { biasLabel, confidenceOpacity, DivergenceMini as DivergenceMiniComponent };
