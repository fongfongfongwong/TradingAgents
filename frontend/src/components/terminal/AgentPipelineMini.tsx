"use client";

import { useEffect, useRef, useState } from "react";
import { useTicker } from "@/hooks/useTicker";
import { useSSE, type SSEEvent, type SSEEventType } from "@/hooks/useSSE";

/* ------------------------------------------------------------------ */
/*  Pipeline stage definitions (mirrored from AnalysisTab)             */
/* ------------------------------------------------------------------ */

type StageStatus = "pending" | "active" | "complete";

interface MiniStage {
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

const STAGE_SHORT_LABELS: Record<string, string> = {
  materialized: "materialize",
  screened: "screen",
  thesis: "thesis",
  antithesis: "antithesis",
  base_rate: "base_rate",
  synthesis: "synthesis",
  risk: "risk",
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

function buildInitialStages(): MiniStage[] {
  return STAGE_KEYS.map((key) => ({
    key,
    label: STAGE_SHORT_LABELS[key],
    status: "pending" as StageStatus,
    detail: "",
    durationMs: null,
  }));
}

function buildMiniDetail(ev: SSEEvent): string {
  const d = ev.data;
  if (!d) return "done";

  switch (ev.type) {
    case "thesis_complete": {
      const dir = d.direction ?? d.signal ?? "";
      const conf = d.confidence ?? d.score;
      return conf != null ? `${String(dir)} ${Math.round(Number(conf))}` : String(dir) || "done";
    }
    case "antithesis_complete": {
      const dir = d.direction ?? d.signal ?? "";
      const conf = d.confidence ?? d.score;
      return conf != null ? `${String(dir)} ${Math.round(Number(conf))}` : String(dir) || "done";
    }
    case "base_rate_complete": {
      const dir = d.direction ?? d.signal ?? "NEUT";
      const conf = d.confidence ?? d.score;
      return conf != null ? `${String(dir)} ${Math.round(Number(conf))}` : String(dir) || "done";
    }
    case "synthesis_complete": {
      const dir = d.direction ?? d.signal ?? "";
      const conf = d.confidence ?? d.score;
      return conf != null ? `${String(dir)} ${Math.round(Number(conf))}` : String(dir) || "done";
    }
    case "risk_complete": {
      const level = d.risk_level ?? d.level ?? "";
      return String(level) || "done";
    }
    case "screened": {
      const tier = d.tier ?? d.factor_tier;
      return tier ? `Tier ${String(tier)}` : "done";
    }
    case "materialized": {
      const snap = d.snapshot_id;
      return snap ? String(snap).slice(0, 8) : "done";
    }
    default:
      return "done";
  }
}

/* ------------------------------------------------------------------ */
/*  Status icon                                                        */
/* ------------------------------------------------------------------ */

function StatusIcon({ status }: { status: StageStatus }) {
  if (status === "complete") {
    return <span className="text-[#10b981] font-mono text-[9px]">&#10003;</span>;
  }
  if (status === "active") {
    return (
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#5e6ad2] opacity-50" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-[#5e6ad2]" />
      </span>
    );
  }
  return <span className="text-[#62666d] font-mono text-[9px]">&#8226;</span>;
}

/* ------------------------------------------------------------------ */
/*  AgentPipelineMini                                                  */
/* ------------------------------------------------------------------ */

export default function AgentPipelineMini() {
  const { ticker } = useTicker();
  const { events } = useSSE();

  const [stages, setStages] = useState<MiniStage[]>(buildInitialStages);
  const [hasData, setHasData] = useState(false);
  const stageTimestamps = useRef<Record<string, number>>({});
  const connectTime = useRef<number>(Date.now());

  // Reset when ticker changes
  useEffect(() => {
    setStages(buildInitialStages());
    setHasData(false);
    stageTimestamps.current = {};
    connectTime.current = Date.now();
  }, [ticker]);

  // Process SSE events into stages
  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[events.length - 1];
    const stageKey = EVENT_TO_STAGE[latest.type];
    if (!stageKey) return;

    setHasData(true);
    const now = Date.now();

    setStages((prev) => {
      const next = prev.map((s) => ({ ...s }));
      const idx = next.findIndex((s) => s.key === stageKey);
      if (idx === -1) return prev;

      const prevTimestamp =
        idx > 0
          ? stageTimestamps.current[next[idx - 1].key] ?? connectTime.current
          : connectTime.current;
      const duration = now - prevTimestamp;
      stageTimestamps.current[stageKey] = now;

      next[idx] = {
        ...next[idx],
        status: "complete",
        durationMs: duration,
        detail: buildMiniDetail(latest),
      };

      const nextPending = next.findIndex((s, si) => si > idx && s.status === "pending");
      if (nextPending !== -1) {
        next[nextPending] = { ...next[nextPending], status: "active" };
      }

      return next;
    });
  }, [events]);

  return (
    <div className="shrink-0 border-t border-white/[0.08]">
      <div className="flex items-center justify-between px-3 py-2">
        <h2 className="text-[10px] font-semibold uppercase tracking-wider text-[#8a8f98]">
          Pipeline — {ticker}
        </h2>
      </div>

      {!hasData && (
        <p className="px-3 pb-3 text-[10px] text-[#62666d]">
          Run analysis to see pipeline
        </p>
      )}

      {hasData && (
        <div className="px-3 pb-3 font-mono text-[10px]">
          {stages.map((s) => (
            <div
              key={s.key}
              className="flex items-center gap-2 py-[2px]"
            >
              <span className="flex w-3 items-center justify-center">
                <StatusIcon status={s.status} />
              </span>
              <span
                className={`w-[72px] truncate ${
                  s.status === "complete"
                    ? "text-[#f7f8f8]"
                    : s.status === "active"
                      ? "text-[#5e6ad2]"
                      : "text-[#62666d]"
                }`}
              >
                {s.label}
              </span>
              <span className="flex-1 truncate text-[#8a8f98]">
                {s.status === "complete" && s.detail
                  ? `[${s.detail}]`
                  : s.status === "active"
                    ? "..."
                    : ""}
              </span>
              <span className="w-10 text-right text-[#62666d]">
                {s.durationMs !== null
                  ? `${(s.durationMs / 1000).toFixed(1)}s`
                  : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
