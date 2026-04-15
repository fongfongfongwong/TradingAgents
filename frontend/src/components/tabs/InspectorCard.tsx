"use client";

import { useCallback, useState } from "react";
import type {
  V3FinalDecision,
  V3VolatilityContext,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Colour helpers                                                     */
/* ------------------------------------------------------------------ */

function signalColor(signal: string): string {
  const s = signal.toUpperCase();
  if (s === "BUY" || s === "LONG") return "#34d399";
  if (s === "SHORT" || s === "SELL") return "#fca5a5";
  return "#8b98ac";
}

function signalBg(signal: string): string {
  const s = signal.toUpperCase();
  if (s === "BUY" || s === "LONG") return "#041f16";
  if (s === "SHORT" || s === "SELL") return "#1c0608";
  return "#1a1f28";
}

function signalBgGradient(signal: string): string {
  const s = signal.toUpperCase();
  if (s === "BUY" || s === "LONG") return "linear-gradient(180deg, #062c1f 0%, #041f16 100%)";
  if (s === "SHORT" || s === "SELL") return "linear-gradient(180deg, #2c0608 0%, #1c0608 100%)";
  return "linear-gradient(180deg, #1a1f28 0%, #151a22 100%)";
}

function signalBorder(signal: string): string {
  const s = signal.toUpperCase();
  if (s === "BUY" || s === "LONG") return "#0a5d3f";
  if (s === "SHORT" || s === "SELL") return "#7f1d1d";
  return "#2a3246";
}

function directionToShortLabel(direction: string | undefined): string {
  if (!direction) return "?";
  const d = direction.toUpperCase();
  if (d === "BULLISH") return "BUY";
  if (d === "BEARISH") return "SHORT";
  return "NEUT";
}

function directionColor(direction: string | undefined): string {
  const d = (direction ?? "").toUpperCase();
  if (d === "BULLISH") return "#10b981";
  if (d === "BEARISH") return "#e23b4a";
  return "#8a8f98";
}

/* ------------------------------------------------------------------ */
/*  Metric cell                                                        */
/* ------------------------------------------------------------------ */

interface MetricCellProps {
  readonly label: string;
  readonly value: string;
  readonly muted?: boolean;
}

function MetricCell({ label, value, muted }: MetricCellProps) {
  return (
    <div className="rounded border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-[#62666d]">
        {label}
      </div>
      <div
        className={`mt-0.5 font-mono text-xs font-semibold ${muted ? "text-[#62666d]" : "text-[#d0d6e0]"}`}
      >
        {value}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Agent mini-card (Thesis / Antithesis / Base Rate)                  */
/* ------------------------------------------------------------------ */

interface AgentMiniCardProps {
  readonly label: string;
  readonly direction: string;
  readonly confidence: number;
  readonly color: string;
}

function AgentMiniCard({ label, direction, confidence, color }: AgentMiniCardProps) {
  return (
    <div
      className="flex-1 rounded border px-3 py-2"
      style={{
        borderColor: `${color}33`,
        backgroundColor: `${color}0a`,
      }}
    >
      <div className="text-[9px] uppercase tracking-wider text-[#8a8f98]">
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span
          className="text-xs font-bold uppercase"
          style={{ color }}
        >
          {direction}
        </span>
        <span className="font-mono text-xs text-[#d0d6e0]">
          {confidence}%
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Volatility grid                                                    */
/* ------------------------------------------------------------------ */

function VolatilityGrid({ vol }: { readonly vol: V3VolatilityContext }) {
  const fmt = (v: number | null | undefined): string =>
    v != null ? `${v.toFixed(1)}%` : "N/A";

  return (
    <div data-testid="volatility-section">
      <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
        Volatility
      </div>
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        <MetricCell label="RV 20d" value={fmt(vol.realized_vol_20d_pct)} />
        <MetricCell label="HAR 1d" value={fmt(vol.predicted_rv_1d_pct)} />
        <MetricCell label="HAR 5d" value={fmt(vol.predicted_rv_5d_pct)} />
        <MetricCell label="IV Rank" value={fmt(vol.iv_rank_percentile)} />
        <MetricCell label="RV 5d" value={fmt(vol.realized_vol_5d_pct)} />
        <MetricCell label="RV 60d" value={fmt(vol.realized_vol_60d_pct)} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sentiment consensus grid                                           */
/* ------------------------------------------------------------------ */

interface SentimentData {
  readonly news_sentiment?: string | null;
  readonly reddit_sentiment?: string | null;
  readonly congress_sentiment?: string | null;
  readonly insider_sentiment?: string | null;
  readonly fear_greed?: string | null;
  readonly composite_sentiment?: string | null;
}

function SentimentGrid({ sentiment }: { readonly sentiment: SentimentData }) {
  const cells: Array<{ label: string; value: string }> = [
    { label: "News", value: sentiment.news_sentiment ?? "N/A" },
    { label: "Reddit", value: sentiment.reddit_sentiment ?? "N/A" },
    { label: "Congress", value: sentiment.congress_sentiment ?? "N/A" },
    { label: "Insider", value: sentiment.insider_sentiment ?? "N/A" },
    { label: "F&G", value: sentiment.fear_greed ?? "N/A" },
    { label: "Composite", value: sentiment.composite_sentiment ?? "N/A" },
  ];

  return (
    <div data-testid="sentiment-section">
      <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
        Sentiment Consensus
      </div>
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        {cells.map((c) => (
          <MetricCell
            key={c.label}
            label={c.label}
            value={c.value}
            muted={c.value === "N/A"}
          />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Options context grid                                               */
/* ------------------------------------------------------------------ */

interface OptionsData {
  readonly options_direction?: "BULL" | "BEAR" | "NEUTRAL" | string | null;
  readonly options_impact?: number | null;
  readonly put_call_ratio?: number | null;
  readonly iv_rank?: number | null;
  readonly skew?: number | null;
  readonly max_pain?: number | null;
}

function OptionsGrid({ options }: { readonly options: OptionsData }) {
  const fmt = (v: number | null | undefined): string =>
    v != null ? v.toFixed(2) : "N/A";
  const pctFmt = (v: number | null | undefined): string =>
    v != null ? `${v.toFixed(1)}%` : "N/A";

  return (
    <div data-testid="options-section">
      <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
        Options Context
      </div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        <MetricCell
          label="Direction"
          value={options.options_direction ?? "N/A"}
          muted={!options.options_direction}
        />
        <MetricCell
          label="Impact"
          value={pctFmt(options.options_impact)}
          muted={options.options_impact == null}
        />
        <MetricCell
          label="PCR"
          value={fmt(options.put_call_ratio)}
          muted={options.put_call_ratio == null}
        />
        <MetricCell
          label="Max Pain"
          value={options.max_pain != null ? `$${options.max_pain.toFixed(0)}` : "N/A"}
          muted={options.max_pain == null}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Placeholder for missing sections                                   */
/* ------------------------------------------------------------------ */

function PlaceholderSection({
  title,
  testId,
}: {
  readonly title: string;
  readonly testId: string;
}) {
  return (
    <div data-testid={testId}>
      <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
        {title}
      </div>
      <div className="rounded border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[10px] italic text-[#62666d]">
        Run deep analysis for full data
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Rerun / Pin / Copy buttons                                         */
/* ------------------------------------------------------------------ */

function VerdictActions({
  ticker,
  signal,
  rationale,
  onRerun,
  onPin,
  pinned,
}: {
  readonly ticker: string;
  readonly signal: string;
  readonly rationale: string | null;
  readonly onRerun?: () => void;
  readonly onPin?: (ticker: string) => void;
  readonly pinned: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    const text = `${ticker}: ${signal}${rationale ? ` — ${rationale}` : ""}`;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [ticker, signal, rationale]);

  return (
    <div className="flex items-center gap-1" data-testid="verdict-actions">
      {onRerun && (
        <button
          type="button"
          data-testid="btn-rerun"
          onClick={onRerun}
          title="Rerun analysis"
          className="rounded p-1 text-[#8a8f98] transition-colors hover:bg-white/[0.06] hover:text-[#f7f8f8]"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 8a6 6 0 0 1 10.3-4.2M14 8a6 6 0 0 1-10.3 4.2" strokeLinecap="round" />
            <path d="M12 1v3h-3M4 15v-3h3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
      {onPin && (
        <button
          type="button"
          data-testid="btn-pin"
          onClick={() => onPin(ticker)}
          title={pinned ? "Unpin" : "Pin"}
          className={`rounded p-1 transition-colors hover:bg-white/[0.06] ${
            pinned ? "text-[#f59e0b]" : "text-[#8a8f98] hover:text-[#f7f8f8]"
          }`}
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill={pinned ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5">
            <path d="M8 1v6M5 7l-1 5 4-2 4 2-1-5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
      <button
        type="button"
        data-testid="btn-copy"
        onClick={handleCopy}
        title="Copy verdict"
        className="rounded p-1 text-[#8a8f98] transition-colors hover:bg-white/[0.06] hover:text-[#f7f8f8]"
      >
        {copied ? (
          <svg className="h-3.5 w-3.5 text-[#10b981]" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 8.5l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="5" y="5" width="9" height="9" rx="1" />
            <path d="M3 11V3a1 1 0 0 1 1-1h8" strokeLinecap="round" />
          </svg>
        )}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  InspectorCard props                                                */
/* ------------------------------------------------------------------ */

export interface InspectorCardProps {
  readonly data: V3FinalDecision;
  readonly onRerun?: () => void;
  readonly onPin?: (ticker: string) => void;
  readonly pinned?: boolean;
}

/* ------------------------------------------------------------------ */
/*  InspectorCard                                                      */
/* ------------------------------------------------------------------ */

export default function InspectorCard({
  data,
  onRerun,
  onPin,
  pinned = false,
}: InspectorCardProps) {
  const sig = data.signal.toUpperCase();
  const color = signalColor(sig);
  const bg = signalBg(sig);

  const synthesis = data.synthesis;
  const thesis = data.thesis;
  const antithesis = data.antithesis;
  const baseRate = data.base_rate;
  const vol = data.volatility ?? null;

  const evPct = synthesis?.expected_value_pct ?? null;
  const conviction = data.conviction;
  const disagreement = synthesis?.disagreement_score ?? null;
  const rationale = synthesis?.decision_rationale ?? null;

  // Agreement = 1 - disagreement  (displayed as %)
  const agreementPct =
    disagreement != null ? ((1 - disagreement) * 100).toFixed(0) : null;

  // Extract sentiment from the decision (may be attached by full pipeline)
  const sentiment: SentimentData | null =
    (data as unknown as Record<string, unknown>).sentiment as SentimentData | null ?? null;

  // Extract options data — from top-level fields or nested object
  const optionsRaw = (data as unknown as Record<string, unknown>).options as OptionsData | undefined;
  const optionsData: OptionsData = {
    options_direction:
      optionsRaw?.options_direction ??
      ((data as unknown as Record<string, unknown>).options_direction as string | null | undefined) ??
      null,
    options_impact:
      optionsRaw?.options_impact ??
      ((data as unknown as Record<string, unknown>).options_impact as number | null | undefined) ??
      null,
    put_call_ratio: optionsRaw?.put_call_ratio ?? null,
    iv_rank: optionsRaw?.iv_rank ?? null,
    skew: optionsRaw?.skew ?? null,
    max_pain: optionsRaw?.max_pain ?? null,
  };

  const hasOptionsData =
    optionsData.options_direction != null || optionsData.options_impact != null;

  const hasSentimentData = sentiment != null && Object.values(sentiment).some((v) => v != null);

  return (
    <div
      data-testid="inspector-card"
      className="rounded-lg border border-white/[0.08] bg-[#0d1218] p-4 space-y-4"
    >
      {/* ---- Header: ticker + signal ---- */}
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-bold text-[#f7f8f8]">
            {data.ticker}
          </span>
          <span className="text-xs text-[#8a8f98]">
            Tier {data.tier}
          </span>
        </div>
        <span className="font-mono text-xs text-[#8a8f98]">
          {data.date}
        </span>
      </div>

      {/* ---- Verdict box ---- */}
      <div
        data-testid="verdict-box"
        className="relative flex items-center gap-4 rounded-md px-4 py-3"
        style={{ background: signalBgGradient(sig), border: `1px solid ${signalBorder(sig)}` }}
      >
        <span
          className="font-mono text-[32px] font-extrabold uppercase tracking-widest"
          style={{ color }}
        >
          {sig}
        </span>

        <div className="flex flex-wrap items-baseline gap-4 text-sm">
          <span className="font-mono text-[11px] text-[#f7f8f8]">
            <span className="font-bold">{conviction}</span>
            <span className="text-[10px] text-[#8a8f98]">/100</span>
          </span>

          {evPct != null && (
            <span className="font-mono" style={{ color }}>
              EV {evPct >= 0 ? "+" : ""}{evPct.toFixed(1)}%
            </span>
          )}

          {agreementPct != null && (
            <span className="font-mono text-[#d0d6e0]">
              {agreementPct}% agree
            </span>
          )}
        </div>

        {/* Coloured conviction bar */}
        <div className="ml-auto hidden w-28 sm:block">
          <div className="h-1.5 w-full rounded-full bg-white/[0.06]">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(100, Math.max(0, conviction))}%`,
                backgroundColor: color,
              }}
            />
          </div>
        </div>

        {/* ---- Rerun / Pin / Copy ---- */}
        <div className="absolute right-2 top-2">
          <VerdictActions
            ticker={data.ticker}
            signal={sig}
            rationale={rationale}
            onRerun={onRerun}
            onPin={onPin}
            pinned={pinned}
          />
        </div>
      </div>

      {/* ---- Because ---- */}
      {rationale && (
        <div
          data-testid="because-block"
          className="border-l-[3px] border-[#4fc3f7] bg-[#041824] rounded-r pl-3 py-2 pr-3"
        >
          <span className="text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
            Because
          </span>
          <p className="mt-0.5 text-xs leading-relaxed text-[#d0d6e0]">
            {rationale}
          </p>
        </div>
      )}

      {/* ---- Debate rollup ---- */}
      <div className="space-y-1.5">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
          Debate Rollup
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {thesis ? (
            <AgentMiniCard
              label="Thesis"
              direction={directionToShortLabel(thesis.direction)}
              confidence={thesis.confidence_score}
              color={directionColor(thesis.direction)}
            />
          ) : (
            <div
              data-testid="thesis-pending"
              className="flex-1 rounded border border-white/[0.06] bg-white/[0.02] px-3 py-2"
            >
              <div className="text-[9px] uppercase tracking-wider text-[#62666d]">
                Thesis
              </div>
              <div className="mt-1 text-[10px] italic text-[#62666d]">
                pending
              </div>
            </div>
          )}

          {antithesis ? (
            <AgentMiniCard
              label="Antithesis"
              direction={directionToShortLabel(antithesis.direction)}
              confidence={antithesis.confidence_score}
              color={directionColor(antithesis.direction)}
            />
          ) : (
            <div
              data-testid="antithesis-pending"
              className="flex-1 rounded border border-white/[0.06] bg-white/[0.02] px-3 py-2"
            >
              <div className="text-[9px] uppercase tracking-wider text-[#62666d]">
                Antithesis
              </div>
              <div className="mt-1 text-[10px] italic text-[#62666d]">
                pending
              </div>
            </div>
          )}

          {baseRate ? (
            <AgentMiniCard
              label="Base Rate"
              direction={
                baseRate.base_rate_probability_up >= 0.55
                  ? "BUY"
                  : baseRate.base_rate_probability_up <= 0.45
                    ? "SHORT"
                    : "NEUT"
              }
              confidence={Math.round(baseRate.base_rate_probability_up * 100)}
              color={
                baseRate.base_rate_probability_up >= 0.55
                  ? "#10b981"
                  : baseRate.base_rate_probability_up <= 0.45
                    ? "#e23b4a"
                    : "#8a8f98"
              }
            />
          ) : (
            <div className="flex-1 rounded border border-white/[0.06] bg-white/[0.02] px-3 py-2">
              <div className="text-[9px] uppercase tracking-wider text-[#62666d]">
                Base Rate
              </div>
              <div className="mt-1 text-[10px] italic text-[#62666d]">
                pending
              </div>
            </div>
          )}
        </div>

        {/* Synthesis full-width card */}
        {synthesis && (
          <div
            className="rounded border px-3 py-2"
            style={{
              borderColor: `${color}33`,
              backgroundColor: `${color}0a`,
            }}
          >
            <div className="flex items-center justify-between">
              <div className="text-[9px] uppercase tracking-wider text-[#8a8f98]">
                Synthesis
              </div>
              <span
                className="text-xs font-bold uppercase"
                style={{ color }}
              >
                {synthesis.signal}
              </span>
            </div>
            {synthesis.key_evidence && synthesis.key_evidence.length > 0 && (
              <p className="mt-1 text-[10px] text-[#8a8f98]">
                Sided with {synthesis.signal.toUpperCase()} based on{" "}
                {synthesis.key_evidence[0].toLowerCase()}
              </p>
            )}
          </div>
        )}
      </div>

      {/* ---- Volatility ---- */}
      {vol ? (
        <VolatilityGrid vol={vol} />
      ) : (
        <div data-testid="volatility-section">
          <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
            Volatility
          </div>
          <div
            data-testid="vol-na"
            className="grid grid-cols-3 gap-1.5 sm:grid-cols-6"
          >
            {["RV 20d", "HAR 1d", "HAR 5d", "IV Rank", "RV 5d", "RV 60d"].map(
              (label) => (
                <MetricCell key={label} label={label} value="N/A" muted />
              ),
            )}
          </div>
        </div>
      )}

      {/* ---- Sentiment Consensus ---- */}
      {hasSentimentData ? (
        <SentimentGrid sentiment={sentiment} />
      ) : (
        <PlaceholderSection
          title="Sentiment Consensus"
          testId="sentiment-section"
        />
      )}

      {/* ---- Options Context ---- */}
      {hasOptionsData ? (
        <OptionsGrid options={optionsData} />
      ) : (
        <PlaceholderSection
          title="Options Context"
          testId="options-section"
        />
      )}
    </div>
  );
}
