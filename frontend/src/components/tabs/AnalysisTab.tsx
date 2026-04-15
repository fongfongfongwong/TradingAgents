"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTicker } from "@/hooks/useTicker";
import {
  startAnalysisV3,
  getAnalysisV3,
  type BatchSignalItem,
  type V3AnalysisStatus,
  type V3FinalDecision,
  type V3ThesisResult,
  type V3AntithesisResult,
  type V3BaseRateResult,
  type V3SynthesisResult,
  type V3RiskResult,
  type V3CatalystItem,
  type V3MustBeTrue,
  type V3ScenarioItem,
  type V3VolatilityContext,
} from "@/lib/api";
import { useSSE, type SSEEvent, type SSEEventType } from "@/hooks/useSSE";
import { useSignalsStore } from "@/stores/signalsStore";
import InspectorCard from "./InspectorCard";

/* ------------------------------------------------------------------ */
/*  Pipeline stage definitions                                         */
/* ------------------------------------------------------------------ */

type StageStatus = "pending" | "active" | "complete";

interface PipelineStage {
  readonly key: string;
  readonly label: string;
  status: StageStatus;
  detail: string;
  durationMs: number | null;
}

const STAGE_KEYS = [
  "materialized",
  "screened",
  "thesis",
  "antithesis",
  "base_rate",
  "synthesis",
  "risk",
] as const;

const STAGE_LABELS: Record<string, string> = {
  materialized: "Data Materialized",
  screened: "Factor Screen",
  thesis: "Thesis Agent",
  antithesis: "Antithesis Agent",
  base_rate: "Base Rate Agent",
  synthesis: "Synthesis (Judge)",
  risk: "Risk Evaluation",
};

const EVENT_TO_STAGE: Partial<Record<SSEEventType, string>> = {
  materialized: "materialized",
  screened: "screened",
  thesis_complete: "thesis",
  antithesis_complete: "antithesis",
  base_rate_complete: "base_rate",
  synthesis_complete: "synthesis",
  risk_complete: "risk",
};

function buildInitialStages(): PipelineStage[] {
  return STAGE_KEYS.map((key) => ({
    key,
    label: STAGE_LABELS[key],
    status: "pending" as StageStatus,
    detail: "",
    durationMs: null,
  }));
}

/* ------------------------------------------------------------------ */
/*  Collapsible Panel                                                  */
/* ------------------------------------------------------------------ */

interface CollapsibleProps {
  title: string;
  accentClass: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function Collapsible({
  title,
  accentClass,
  defaultOpen = true,
  children,
}: CollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`rounded border ${accentClass} overflow-visible`}>
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center justify-between px-4 py-2.5"
      >
        <span className="text-sm font-semibold text-[#f7f8f8]">{title}</span>
        <span className="text-xs text-[#8a8f98]">{open ? "Hide" : "Show"}</span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Small reusable atoms                                               */
/* ------------------------------------------------------------------ */

function ProgressBar({
  value,
  max = 100,
  color,
}: {
  value: number;
  max?: number;
  color: string;
}) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="h-1.5 w-full rounded-full bg-white/[0.06]">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="inline-block rounded-full border px-3 py-0.5 text-xs font-bold uppercase tracking-wide"
      style={{
        color,
        borderColor: `${color}44`,
        backgroundColor: `${color}18`,
      }}
    >
      {label}
    </span>
  );
}

function KV({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-xs text-[#8a8f98]">{label}</span>
      <span className="font-mono text-sm text-[#f7f8f8]">{children}</span>
    </div>
  );
}

function YesNo({ value }: { value: boolean }) {
  return value ? (
    <span className="text-[#10b981]">Yes</span>
  ) : (
    <span className="text-[#e23b4a]">No</span>
  );
}

/* ------------------------------------------------------------------ */
/*  Pipeline Progress Strip (one-line horizontal indicator)            */
/* ------------------------------------------------------------------ */

function PipelineProgressStrip({
  stages,
  latencyMs,
}: {
  stages: readonly PipelineStage[];
  latencyMs: number | null;
}) {
  const dotColor = (s: StageStatus): string => {
    if (s === "complete") return "#10b981";
    if (s === "active") return "#5e6ad2";
    return "#62666d";
  };

  return (
    <div className="flex items-center gap-2 rounded border border-white/[0.08] bg-white/[0.02] px-3 py-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-[#8a8f98]">
        Pipeline
      </span>
      {stages.map((s) => (
        <span key={s.key} className="flex items-center gap-1">
          <span
            className={`inline-block h-2 w-2 rounded-full${s.status === "active" ? " animate-pulse" : ""}`}
            style={{ backgroundColor: dotColor(s.status) }}
          />
          <span
            className={`text-[10px] ${
              s.status === "complete"
                ? "text-[#f7f8f8]"
                : s.status === "active"
                  ? "text-[#5e6ad2]"
                  : "text-[#62666d]"
            }`}
          >
            {s.label.replace(" Agent", "").replace(" (Judge)", "").replace("Data Materialized", "Data").replace("Factor Screen", "Screen")}
          </span>
        </span>
      ))}
      {latencyMs !== null && (
        <span className="ml-auto font-mono text-[10px] text-[#8a8f98]">
          {(latencyMs / 1000).toFixed(1)}s
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Reasoning sub-atoms (G3)                                           */
/* ------------------------------------------------------------------ */

/** Muted uppercase section label used inside every panel. */
function PanelLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[9px] font-semibold uppercase tracking-wider text-[#62666d]">
      {children}
    </span>
  );
}

/** Short italic prose block used for *_rationale and *_detail fields. */
function RationaleProse({
  label,
  text,
}: {
  label: string;
  text: string | null | undefined;
}) {
  const trimmed = text?.trim();
  if (!trimmed) return null;
  return (
    <div>
      <PanelLabel>{label}</PanelLabel>
      <p className="mt-0.5 text-[11px] italic leading-relaxed text-[#8a8f98]">
        {trimmed}
      </p>
    </div>
  );
}

/** Amber warning pills used for contrarian_signals / crowding_fragility. */
function WarningPills({
  label,
  items,
}: {
  label: string;
  items: readonly string[] | null | undefined;
}) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <PanelLabel>{label}</PanelLabel>
      <div className="mt-1 flex flex-wrap gap-1">
        {items.map((item, i) => (
          <span
            key={`${label}-${i}`}
            className="rounded-full border border-[#f59e0b]/30 bg-[#f59e0b]/10 px-1.5 py-[1px] text-[10px] text-[#fbbf24]"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Bulleted evidence list used for synthesis.key_evidence. */
function EvidenceList({ items }: { items: readonly string[] | null | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <PanelLabel>Key Evidence</PanelLabel>
      <ul className="mt-1 space-y-0.5">
        {items.map((item, i) => (
          <li
            key={`evidence-${i}`}
            className="flex gap-1.5 pb-0.5 pl-3 text-[11px] text-[#d0d6e0]"
          >
            <span aria-hidden className="text-[#62666d]">&bull;</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Agent Panels                                                       */
/* ------------------------------------------------------------------ */

function CatalystList({ items }: { items: V3CatalystItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">Catalysts</span>
      {items.map((c, i) => (
        <div key={i} className="rounded bg-white/[0.03] px-2.5 py-1.5 text-xs">
          <span className="font-medium text-[#f7f8f8]">{c.event}</span>
          <span className="ml-1 text-[#8a8f98]">
            {c.mechanism} ({c.magnitude_estimate})
          </span>
        </div>
      ))}
    </div>
  );
}

function MustBeTrueList({ items }: { items: V3MustBeTrue[] }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">Must Be True</span>
      {items.map((m, i) => (
        <div
          key={i}
          className="flex items-center justify-between rounded bg-white/[0.03] px-2.5 py-1.5 text-xs"
        >
          <span className="text-[#d0d6e0]">{m.condition}</span>
          <span className="font-mono text-[#f7f8f8]">{(m.probability * 100).toFixed(0)}%</span>
        </div>
      ))}
    </div>
  );
}

function ThesisPanel({ data }: { data: V3ThesisResult }) {
  return (
    <Collapsible title="Thesis Agent" accentClass="border-[#10b981]/20 bg-[#10b981]/[0.04]">
      <div className="space-y-3">
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <span className="text-xs text-[#8a8f98]">Confidence</span>
            <span className="font-mono text-sm font-bold text-[#10b981]">
              {data.confidence_score}
              <span className="text-[10px] text-[#8a8f98]">/100</span>
            </span>
          </div>
          <ProgressBar value={data.confidence_score} color="#10b981" />
        </div>
        <KV label="Direction">
          <Badge label={data.direction} color={data.direction === "BULLISH" ? "#10b981" : "#e23b4a"} />
        </KV>
        <KV label="Momentum aligned">
          <YesNo value={data.momentum_aligned} />
        </KV>
        {data.valuation_gap_summary && (
          <div>
            <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">Valuation Gap</span>
            <p className="mt-0.5 text-xs text-[#d0d6e0]">{data.valuation_gap_summary}</p>
          </div>
        )}
        <CatalystList items={data.catalysts} />
        <MustBeTrueList items={data.must_be_true} />
        <div>
          <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">Weakest Link</span>
          <p className="mt-0.5 text-xs text-[#ec7e00]">{data.weakest_link}</p>
        </div>
        <RationaleProse label="Confidence Rationale" text={data.confidence_rationale} />
        <RationaleProse label="Momentum Detail" text={data.momentum_detail} />
        <WarningPills label="Contrarian Signals" items={data.contrarian_signals} />
      </div>
    </Collapsible>
  );
}

function AntithesisPanel({ data }: { data: V3AntithesisResult }) {
  return (
    <Collapsible title="Antithesis Agent" accentClass="border-[#e23b4a]/20 bg-[#e23b4a]/[0.04]">
      <div className="space-y-3">
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <span className="text-xs text-[#8a8f98]">Confidence</span>
            <span className="font-mono text-sm font-bold text-[#e23b4a]">
              {data.confidence_score}
              <span className="text-[10px] text-[#8a8f98]">/100</span>
            </span>
          </div>
          <ProgressBar value={data.confidence_score} color="#e23b4a" />
        </div>
        <KV label="Direction">
          <Badge label={data.direction} color={data.direction === "BEARISH" ? "#e23b4a" : "#10b981"} />
        </KV>
        <KV label="Deterioration present">
          <YesNo value={data.deterioration_present} />
        </KV>
        {data.overvaluation_summary && (
          <div>
            <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">
              Overvaluation Summary
            </span>
            <p className="mt-0.5 text-xs text-[#d0d6e0]">{data.overvaluation_summary}</p>
          </div>
        )}
        <CatalystList items={data.risk_catalysts} />
        <MustBeTrueList items={data.must_be_true} />
        <div>
          <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">Weakest Link</span>
          <p className="mt-0.5 text-xs text-[#ec7e00]">{data.weakest_link}</p>
        </div>
        <RationaleProse label="Confidence Rationale" text={data.confidence_rationale} />
        <RationaleProse label="Deterioration Detail" text={data.deterioration_detail} />
        <WarningPills label="Crowding Fragility" items={data.crowding_fragility} />
      </div>
    </Collapsible>
  );
}

function BaseRatePanel({ data }: { data: V3BaseRateResult }) {
  return (
    <Collapsible title="Base Rate Agent" accentClass="border-[#5e6ad2]/20 bg-[#5e6ad2]/[0.04]">
      <div className="space-y-2">
        <KV label="Probability up">
          <span className="text-[#5e6ad2]">
            {(data.base_rate_probability_up * 100).toFixed(0)}%
          </span>
        </KV>
        <KV label="Expected move">
          <span className={data.expected_move_pct >= 0 ? "text-[#10b981]" : "text-[#e23b4a]"}>
            {data.expected_move_pct >= 0 ? "+" : ""}
            {data.expected_move_pct.toFixed(1)}%
          </span>
        </KV>
        <KV label="Upside / Downside">
          <span>
            <span className="text-[#10b981]">+{data.upside_pct.toFixed(1)}%</span>
            <span className="mx-1 text-[#62666d]">/</span>
            <span className="text-[#e23b4a]">-{Math.abs(data.downside_pct).toFixed(1)}%</span>
          </span>
        </KV>
        <KV label="Regime">
          <Badge label={data.regime} color="#5e6ad2" />
        </KV>
        <KV label="Vol forecast (20d)">{data.volatility_forecast_20d.toFixed(1)}%</KV>
        {data.historical_analog && (
          <div>
            <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">
              Historical Analog
            </span>
            <p className="mt-0.5 text-xs text-[#d0d6e0]">{data.historical_analog}</p>
          </div>
        )}
      </div>
    </Collapsible>
  );
}

function ScenarioTable({ scenarios }: { scenarios: V3ScenarioItem[] }) {
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">Scenarios</span>
      <div className="mt-1.5 space-y-1.5">
        {scenarios.map((sc, i) => (
          <div key={i} className="rounded bg-white/[0.03] px-3 py-2">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="text-[#d0d6e0]">{sc.rationale}</span>
              <span className="ml-2 flex-shrink-0 font-mono text-[#f7f8f8]">
                {(sc.probability * 100).toFixed(0)}%
              </span>
            </div>
            <ProgressBar
              value={sc.probability * 100}
              color={sc.return_pct >= 0 ? "#10b981" : "#e23b4a"}
            />
            <div className="mt-1 flex gap-3 text-[10px] text-[#8a8f98]">
              <span>
                Target:{" "}
                <span className="font-mono text-[#f7f8f8]">${sc.target_price.toFixed(2)}</span>
              </span>
              <span>
                Return:{" "}
                <span
                  className={`font-mono ${sc.return_pct >= 0 ? "text-[#10b981]" : "text-[#e23b4a]"}`}
                >
                  {sc.return_pct >= 0 ? "+" : ""}
                  {sc.return_pct.toFixed(1)}%
                </span>
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SynthesisPanel({ data }: { data: V3SynthesisResult }) {
  const signalColor = (() => {
    const s = data.signal.toUpperCase();
    if (s === "BUY" || s === "LONG") return "#10b981";
    if (s === "SHORT" || s === "SELL") return "#e23b4a";
    return "#8a8f98";
  })();

  return (
    <Collapsible title="Synthesis Decision" accentClass="border-white/[0.08] bg-white/[0.02]">
      <div className="space-y-4">
        <div className="flex items-center gap-4">
          <span
            className="rounded-md border-2 px-5 py-2 text-lg font-black uppercase tracking-widest"
            style={{
              color: signalColor,
              borderColor: `${signalColor}66`,
              backgroundColor: `${signalColor}15`,
            }}
          >
            {data.signal}
          </span>
          <div className="space-y-0.5">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-xl font-bold text-[#f7f8f8]">{data.conviction}</span>
              <span className="text-xs text-[#8a8f98]">conviction</span>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2">
          <KV label="Expected Value">
            <span
              className={data.expected_value_pct >= 0 ? "text-[#10b981]" : "text-[#e23b4a]"}
            >
              {data.expected_value_pct >= 0 ? "+" : ""}
              {data.expected_value_pct.toFixed(1)}%
            </span>
          </KV>
          <KV label="Disagreement">
            <span className={data.disagreement_score > 0.6 ? "text-[#ec7e00]" : "text-[#f7f8f8]"}>
              {data.disagreement_score.toFixed(2)}
            </span>
          </KV>
        </div>
        {data.scenarios.length > 0 && <ScenarioTable scenarios={data.scenarios} />}
        {data.decision_rationale && (
          <div>
            <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">
              Decision Rationale
            </span>
            <p className="mt-1 text-xs leading-relaxed text-[#d0d6e0]">
              {data.decision_rationale}
            </p>
          </div>
        )}
        <EvidenceList items={data.key_evidence} />
      </div>
    </Collapsible>
  );
}

/* ------------------------------------------------------------------ */
/*  Data Attribution Panel (G3)                                        */
/* ------------------------------------------------------------------ */

type DataSourceStatus = "active" | "fallback" | "missing";

interface DataSourceRow {
  readonly key: "price" | "news" | "options" | "macro" | "social";
  readonly label: string;
  readonly status: DataSourceStatus;
  readonly reason: string | null;
}

const DATA_SOURCE_KEYS: readonly DataSourceRow["key"][] = [
  "price",
  "news",
  "options",
  "macro",
  "social",
] as const;

const DATA_SOURCE_LABELS: Record<DataSourceRow["key"], string> = {
  price: "Price",
  news: "News",
  options: "Options",
  macro: "Macro",
  social: "Social",
};

/** Classify each data-source context from a ``data_gaps`` array.
 *
 * Gap strings follow the convention ``"<context>:<reason>"`` (e.g.
 * ``"news:finnhub_fallback:exception"``, ``"options:analytics_fallback"``).
 * A context with ZERO matching gaps is ``active``; a context with a SINGLE
 * matching gap is ``fallback`` (and we surface the reason); a context with
 * ``>= 2`` matching gaps is considered ``missing``.
 */
function classifyDataSources(
  gaps: readonly string[] | null | undefined,
): DataSourceRow[] {
  const safe = gaps ?? [];
  return DATA_SOURCE_KEYS.map((key) => {
    const matches = safe.filter((g) => g.startsWith(`${key}:`));
    if (matches.length === 0) {
      return { key, label: DATA_SOURCE_LABELS[key], status: "active", reason: null };
    }
    if (matches.length === 1) {
      const parts = matches[0].split(":");
      const reason = parts.slice(1).join(":") || "fallback";
      return {
        key,
        label: DATA_SOURCE_LABELS[key],
        status: "fallback",
        reason,
      };
    }
    return { key, label: DATA_SOURCE_LABELS[key], status: "missing", reason: null };
  });
}

function DataAttributionPanel({ decision }: { decision: V3FinalDecision }) {
  const rows = classifyDataSources(decision.data_gaps);
  return (
    <Collapsible
      title="Data Sources"
      accentClass="border-white/[0.08] bg-white/[0.02]"
      defaultOpen={false}
    >
      <div className="space-y-1.5">
        {rows.map((row) => {
          const dotColor =
            row.status === "active"
              ? "#10b981"
              : row.status === "fallback"
                ? "#f59e0b"
                : "#e23b4a";
          const statusText =
            row.status === "active"
              ? "Active"
              : row.status === "fallback"
                ? `Fallback: ${row.reason ?? "unknown"}`
                : "Unavailable";
          const statusColor =
            row.status === "active"
              ? "text-[#10b981]"
              : row.status === "fallback"
                ? "text-[#fbbf24]"
                : "text-[#e23b4a]";
          return (
            <div
              key={row.key}
              className="flex items-center justify-between gap-3 rounded bg-white/[0.03] px-2.5 py-1.5"
            >
              <div className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: dotColor }}
                />
                <span className="text-xs text-[#d0d6e0]">{row.label}</span>
              </div>
              <span className={`font-mono text-[10px] ${statusColor}`}>
                {statusText}
              </span>
            </div>
          );
        })}
        {rows.every((r) => r.status === "active") && (
          <p className="pt-1 text-[10px] italic text-[#62666d]">
            All 5 data contexts fed the decision with no fallbacks.
          </p>
        )}
      </div>
    </Collapsible>
  );
}

function RiskPanel({ data }: { data: V3RiskResult }) {
  const ratingColor = (() => {
    const r = data.risk_rating.toUpperCase();
    if (r === "LOW") return "#10b981";
    if (r === "MEDIUM") return "#ec7e00";
    if (r === "HIGH") return "#e23b4a";
    return "#e23b4a";
  })();

  const riskSignalColor = (() => {
    const s = data.signal.toUpperCase();
    if (s === "BUY" || s === "LONG") return "#10b981";
    if (s === "SHORT" || s === "SELL") return "#e23b4a";
    return "#8a8f98";
  })();

  return (
    <Collapsible title="Risk Assessment" accentClass="border-white/[0.08] bg-white/[0.02]">
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Badge label={data.risk_rating} color={ratingColor} />
          <Badge label={data.signal} color={riskSignalColor} />
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2">
          <KV label="Shares">{data.final_shares}</KV>
          <KV label="Position %">{data.position_pct_of_portfolio.toFixed(1)}%</KV>
          <KV label="Stop loss">
            <span className="text-[#e23b4a]">${data.stop_loss_price.toFixed(2)}</span>
          </KV>
          <KV label="Take profit">
            <span className="text-[#10b981]">${data.take_profit_price.toFixed(2)}</span>
          </KV>
          <KV label="Risk/Reward">{data.risk_reward_ratio.toFixed(2)}</KV>
          <KV label="Max loss">
            <span className="text-[#e23b4a]">${data.max_loss_usd.toFixed(0)}</span>
          </KV>
        </div>
        {data.risk_flags.length > 0 && (
          <div>
            <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">Risk Flags</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {data.risk_flags.map((f, i) => (
                <span
                  key={i}
                  className="rounded bg-[#e23b4a]/10 px-2 py-0.5 text-[10px] text-[#e23b4a]"
                >
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}
        {data.stress_tests.length > 0 && (
          <div>
            <span className="text-[10px] font-semibold uppercase text-[#8a8f98]">
              Stress Tests
            </span>
            <table className="mt-1.5 w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] text-[#8a8f98]">
                  <th className="pb-1 font-normal">Scenario</th>
                  <th className="pb-1 text-right font-normal">Loss ($)</th>
                  <th className="pb-1 text-right font-normal">Loss (%)</th>
                </tr>
              </thead>
              <tbody>
                {data.stress_tests.map((t, i) => (
                  <tr key={i} className="border-t border-white/[0.04]">
                    <td className="py-1 text-[#d0d6e0]">{t.scenario}</td>
                    <td className="py-1 text-right font-mono text-[#e23b4a]">
                      ${t.estimated_loss_usd.toFixed(0)}
                    </td>
                    <td className="py-1 text-right font-mono text-[#e23b4a]">
                      {t.estimated_loss_pct.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Collapsible>
  );
}

/* ------------------------------------------------------------------ */
/*  RV Forecast Panel (HAR-RV Ridge baseline)                          */
/* ------------------------------------------------------------------ */

interface RVMetricProps {
  label: string;
  value: number | null | undefined;
  unit: string;
  format: (v: number) => string;
  colorByValue?: (v: number) => string;
}

function RVMetric({ label, value, unit, format, colorByValue }: RVMetricProps) {
  const hasValue = value !== null && value !== undefined;
  const colorClass = hasValue && colorByValue ? colorByValue(value) : "text-[#d0d6e0]";
  return (
    <div className="rounded border border-white/[0.06] bg-white/[0.02] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-[#62666d]">{label}</div>
      <div className={`mt-1 font-mono text-sm font-semibold ${colorClass}`}>
        {hasValue ? `${format(value)}${unit}` : "\u2014"}
      </div>
    </div>
  );
}

function RVForecastPanel({ volCtx }: { volCtx: V3VolatilityContext | null | undefined }) {
  const modelVersion = volCtx?.rv_forecast_model_version ?? null;
  const hasForecast = modelVersion != null && modelVersion !== "";

  return (
    <Collapsible
      title="RV Forecast (HAR-RV Ridge)"
      accentClass="border-white/[0.08] bg-white/[0.02]"
    >
      {hasForecast && volCtx ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-[10px] text-[#62666d]">
            <span>Model: {modelVersion}</span>
            <span className="font-mono">
              Last trained: {modelVersion?.match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? "\u2014"}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-3">
            <RVMetric
              label="Current RV (20d)"
              value={volCtx.realized_vol_20d_pct}
              unit="%"
              format={(v) => v.toFixed(1)}
            />
            <RVMetric
              label="Pred Next 1d"
              value={volCtx.predicted_rv_1d_pct}
              unit="%"
              format={(v) => v.toFixed(1)}
            />
            <RVMetric
              label="Pred Next 5d"
              value={volCtx.predicted_rv_5d_pct}
              unit="%"
              format={(v) => v.toFixed(1)}
            />
            <RVMetric
              label="Delta (1d)"
              value={volCtx.rv_forecast_delta_pct}
              unit=""
              format={(v) => (v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1))}
              colorByValue={(v) =>
                v > 1.0
                  ? "text-[#e23b4a]"
                  : v < -1.0
                    ? "text-[#10b981]"
                    : "text-[#d0d6e0]"
              }
            />
          </div>

          <p className="text-[11px] italic text-[#8a8f98]">
            {volCtx.rv_forecast_delta_pct != null && volCtx.rv_forecast_delta_pct > 2
              ? "Model forecasts rising volatility — consider defensive sizing."
              : volCtx.rv_forecast_delta_pct != null && volCtx.rv_forecast_delta_pct < -2
                ? "Model forecasts calming volatility — neutral to opportunistic stance."
                : "Model forecasts stable volatility."}
          </p>
        </div>
      ) : (
        <p className="text-[11px] italic text-[#62666d]">
          RV forecast model not trained yet. Run training via POST /api/v3/rv/train.
        </p>
      )}
    </Collapsible>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

const AUTO_RUN_KEY = "analysis-auto-run";

function readAutoRunPref(): boolean {
  if (typeof window === "undefined") return true;
  const stored = localStorage.getItem(AUTO_RUN_KEY);
  return stored === null ? true : stored === "true";
}

export default function AnalysisTab() {
  const { ticker } = useTicker();
  const { events, error: sseError, connectV3, disconnect } = useSSE();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<V3AnalysisStatus | null>(null);
  const [stages, setStages] = useState<PipelineStage[]>(buildInitialStages);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [autoRun, setAutoRun] = useState(readAutoRunPref);
  const [pinnedTickers, setPinnedTickers] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem("pinnedTickers");
      return stored ? new Set(JSON.parse(stored) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });

  const handleTogglePin = useCallback((t: string) => {
    setPinnedTickers((prev) => {
      const next = new Set(prev);
      if (next.has(t)) {
        next.delete(t);
      } else {
        next.add(t);
      }
      try {
        localStorage.setItem("pinnedTickers", JSON.stringify([...next]));
      } catch {
        // localStorage full or unavailable — ignore
      }
      return next;
    });
  }, []);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stageTimestamps = useRef<Record<string, number>>({});
  /** Tracks the ticker that the currently running pipeline belongs to. */
  const runningTickerRef = useRef<string | null>(null);

  /* -- Cached BatchSignalItem from Zustand (instant verdict) ---------- */
  const cachedItem = useSignalsStore((s) =>
    s.items.find((i) => i.ticker === ticker),
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[events.length - 1];
    const stageKey = EVENT_TO_STAGE[latest.type];
    if (!stageKey) return;

    const now = Date.now();

    setStages((prev) => {
      const next = prev.map((s) => ({ ...s }));
      const idx = next.findIndex((s) => s.key === stageKey);
      if (idx === -1) return prev;

      const prevTimestamp =
        idx > 0
          ? stageTimestamps.current[next[idx - 1].key] ?? startTime ?? now
          : startTime ?? now;
      const duration = now - prevTimestamp;
      stageTimestamps.current[stageKey] = now;

      next[idx] = {
        ...next[idx],
        status: "complete",
        durationMs: duration,
        detail: buildStageDetail(latest),
      };

      const nextPending = next.findIndex((s, si) => si > idx && s.status === "pending");
      if (nextPending !== -1) {
        next[nextPending] = { ...next[nextPending], status: "active" };
      }

      return next;
    });
  }, [events, startTime]);

  const startPolling = useCallback(
    (id: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const res = await getAnalysisV3(id);
          if (res.status === "complete" || res.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setStatus(res);
            setLoading(false);
            if (res.result?.pipeline_latency_ms) {
              setLatencyMs(res.result.pipeline_latency_ms);
            } else if (startTime) {
              setLatencyMs(Date.now() - startTime);
            }
          }
        } catch {
          // keep polling
        }
      }, 2000);
    },
    [startTime],
  );

  /** Cancel any in-flight pipeline (SSE + polling). */
  const cancelRunning = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    disconnect();
    runningTickerRef.current = null;
  }, [disconnect]);

  const handleRun = async () => {
    if (!ticker) return;

    // If a pipeline is already running for a *different* ticker, cancel it.
    if (loading && runningTickerRef.current && runningTickerRef.current !== ticker) {
      cancelRunning();
    } else if (loading) {
      // Same ticker already running — skip duplicate.
      return;
    }

    runningTickerRef.current = ticker;
    setLoading(true);
    setError(null);
    setStatus(null);
    setLatencyMs(null);
    setStages(buildInitialStages());
    stageTimestamps.current = {};

    const now = Date.now();
    setStartTime(now);

    try {
      const resp = await startAnalysisV3({ ticker });

      // Guard: user may have switched tickers while awaiting the POST.
      if (runningTickerRef.current !== ticker) return;

      setStages((prev) => {
        const next = prev.map((s) => ({ ...s }));
        next[0] = { ...next[0], status: "active" as StageStatus };
        return next;
      });

      connectV3(resp.analysis_id);
      startPolling(resp.analysis_id);
    } catch {
      if (runningTickerRef.current === ticker) {
        setError("Failed to start V3 analysis. Is the backend running?");
        setLoading(false);
        runningTickerRef.current = null;
      }
    }
  };

  /* -- Auto-trigger pipeline on ticker change -------------------------- */
  const prevTickerRef = useRef<string | null>(null);

  useEffect(() => {
    // Only fire when the ticker actually changes (not on mount with same value).
    if (!ticker || !autoRun) {
      prevTickerRef.current = ticker ?? null;
      return;
    }
    if (prevTickerRef.current === ticker) return;
    prevTickerRef.current = ticker;

    // Cancel any running pipeline for the old ticker, then start new one.
    cancelRunning();
    setLoading(false);

    // Small delay to let React settle (batched state) and avoid rapid-fire.
    const timer = setTimeout(() => {
      handleRun();
    }, 80);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, autoRun]);

  const result = status?.result ?? null;
  const thesis: V3ThesisResult | null = result?.thesis ?? null;
  const antithesis: V3AntithesisResult | null = result?.antithesis ?? null;
  const baseRate: V3BaseRateResult | null = result?.base_rate ?? null;
  const synthesis: V3SynthesisResult | null = result?.synthesis ?? null;
  const risk: V3RiskResult | null = result?.risk ?? null;

  const displayError = error ?? sseError;

  /* ---- Idle state: show cached InspectorCard from Zustand ----------- */
  const isIdle = !loading && !status;

  if (isIdle) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        {/* Cached verdict from Zustand store — fills the entire tab area */}
        {cachedItem ? (
          <div className="flex-1 overflow-y-auto">
            <InspectorCard
              data={buildCachedDecision(cachedItem)}
              onRerun={handleRun}
              onPin={handleTogglePin}
              pinned={pinnedTickers.has(ticker)}
            />
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3">
            <span className="text-xs text-[#62666d]">
              No cached data for {ticker}. Run analysis to see verdict.
            </span>
            <button
              type="button"
              onClick={handleRun}
              disabled={!ticker}
              className="rounded bg-[#5e6ad2] px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[#7170ff] disabled:opacity-50"
            >
              Run V3 Analysis
            </button>
          </div>
        )}
      </div>
    );
  }

  const isRunning = loading || status?.status === "running";

  /* ---- Active / completed pipeline state ------------------------------ */
  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* Error banner */}
      {displayError && (
        <div className="mx-4 mt-4 rounded border border-[#e23b4a]/30 bg-[#e23b4a]/10 px-3 py-2 text-xs text-[#e23b4a]">
          {displayError}
        </div>
      )}

      {/* InspectorCard always first — from result or cached data */}
      {result ? (
        <InspectorCard
          data={result}
          onRerun={handleRun}
          onPin={handleTogglePin}
          pinned={pinnedTickers.has(result.ticker)}
        />
      ) : cachedItem ? (
        <InspectorCard
          data={buildCachedDecision(cachedItem)}
          onRerun={handleRun}
          onPin={handleTogglePin}
          pinned={pinnedTickers.has(cachedItem.ticker)}
        />
      ) : (
        <div className="flex h-32 items-center justify-center">
          <span className="text-xs text-[#62666d]">
            {loading ? "Waiting for agent results..." : `No data for ${ticker}`}
          </span>
        </div>
      )}

      {/* Slim pipeline progress strip — only while running */}
      {isRunning && (
        <div className="px-4 py-2">
          <PipelineProgressStrip stages={stages} latencyMs={latencyMs} />
        </div>
      )}

      {/* Collapsible detail panels — show when pipeline has full data */}
      {result && (
        <div className="space-y-3 px-4 pb-4">
          {thesis && <ThesisPanel data={thesis} />}
          {antithesis && <AntithesisPanel data={antithesis} />}
          {baseRate && <BaseRatePanel data={baseRate} />}
          {synthesis && <SynthesisPanel data={synthesis} />}
          {risk && <RiskPanel data={risk} />}
          <RVForecastPanel volCtx={result.volatility ?? null} />
          <DataAttributionPanel decision={result} />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Build a minimal V3FinalDecision from a cached BatchSignalItem so
 *  InspectorCard can render the verdict instantly while the full pipeline
 *  runs in the background. */
function buildCachedDecision(item: BatchSignalItem): V3FinalDecision {
  return {
    ticker: item.ticker,
    date: new Date().toISOString().slice(0, 10),
    snapshot_id: "cached",
    tier: item.tier,
    signal: item.signal,
    conviction: item.conviction,
    final_shares: item.final_shares,
    factor_baseline_score: 0,
    pipeline_latency_ms: item.pipeline_latency_ms,
    thesis: item.thesis_confidence != null
      ? ({
          ticker: item.ticker,
          direction: "BULLISH",
          confidence_score: item.thesis_confidence,
          valuation_gap_summary: null,
          momentum_aligned: false,
          momentum_detail: null,
          catalysts: [],
          must_be_true: [],
          weakest_link: "",
          confidence_rationale: null,
          contrarian_signals: [],
        } as unknown as V3ThesisResult)
      : null,
    antithesis: item.antithesis_confidence != null
      ? ({
          ticker: item.ticker,
          direction: "BEARISH",
          confidence_score: item.antithesis_confidence,
          overvaluation_summary: null,
          deterioration_present: false,
          deterioration_detail: null,
          risk_catalysts: [],
          must_be_true: [],
          weakest_link: "",
          confidence_rationale: null,
          crowding_fragility: [],
        } as unknown as V3AntithesisResult)
      : null,
    base_rate: null,
    synthesis: item.expected_value_pct != null
      ? ({
          ticker: item.ticker,
          signal: item.signal,
          conviction: item.conviction,
          scenarios: [],
          expected_value_pct: item.expected_value_pct,
          disagreement_score: item.disagreement_score ?? 0,
          decision_rationale: null,
          key_evidence: [],
        } as unknown as V3SynthesisResult)
      : null,
    risk: null,
    data_gaps: item.data_gaps,
    volatility: (item.realized_vol_20d_pct != null || item.predicted_rv_1d_pct != null)
      ? ({
          realized_vol_5d_pct: null,
          realized_vol_20d_pct: item.realized_vol_20d_pct ?? null,
          realized_vol_60d_pct: null,
          atr_14_pct_of_price: item.atr_pct_of_price ?? null,
          bollinger_band_width_pct: null,
          iv_rank_percentile: null,
          vol_regime: "UNKNOWN",
          vol_percentile_1y: null,
          kline_last_20: [],
          data_age_seconds: 0,
          predicted_rv_1d_pct: item.predicted_rv_1d_pct ?? null,
          predicted_rv_5d_pct: item.predicted_rv_5d_pct ?? null,
          rv_forecast_model_version: item.rv_forecast_model_version ?? null,
          rv_forecast_delta_pct: item.rv_forecast_delta_pct ?? null,
        } as V3VolatilityContext)
      : null,
    // Pass options data so InspectorCard can render the Options Context section
    ...(item.options_direction != null || item.options_impact != null
      ? {
          options_direction: item.options_direction ?? null,
          options_impact: item.options_impact ?? null,
        }
      : {}),
  } as V3FinalDecision;
}

function buildStageDetail(ev: SSEEvent): string {
  const d = ev.data;
  if (!d) return "";

  switch (ev.type) {
    case "screened": {
      const tier = d.tier ?? d.factor_tier;
      const screen = d.screen_name ?? d.screen ?? "";
      return tier ? `Tier ${String(tier)} — ${String(screen)}` : String(screen);
    }
    case "materialized":
      return d.snapshot_id ? `snapshot ${String(d.snapshot_id).slice(0, 8)}` : "";
    default:
      return "";
  }
}
