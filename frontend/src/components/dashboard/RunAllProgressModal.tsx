"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getBatchStatus,
  type BatchProgress,
  type BatchSignalItem,
} from "@/lib/api";
import { useSignalsStore } from "@/stores/signalsStore";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type TickerStatus = "pending" | "running" | "complete" | "failed";

interface TickerState {
  status: TickerStatus;
  signal?: "BUY" | "SHORT" | "HOLD";
  conviction?: number;
  cost_usd?: number;
  error?: string;
  currentStage?: string;
}

const STAGE_LABELS: Record<string, string> = {
  materialized: "materializing data...",
  screened: "screening tier...",
  thesis_complete: "thesis complete",
  antithesis_complete: "antithesis complete",
  base_rate_complete: "base rate complete",
  synthesis_complete: "synthesis complete",
  risk_complete: "risk assessment done",
  pipeline_complete: "done",
};

type TickerStateMap = Readonly<Record<string, TickerState>>;

interface RunAllProgressModalProps {
  batchId: string;
  initialTickers: readonly string[];
  onClose: () => void;
  onComplete: (finalItems: BatchSignalItem[]) => void;
}

interface TickerDoneEventData {
  ticker?: unknown;
  signal?: unknown;
  conviction?: unknown;
  cost_usd?: unknown;
  error?: unknown;
}

interface TickerStartEventData {
  ticker?: unknown;
}

interface ProgressEventData {
  total?: unknown;
  completed?: unknown;
  failed?: unknown;
  running?: unknown;
  last_ticker?: unknown;
  last_signal?: unknown;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const SIGNAL_COLORS: Record<"BUY" | "SHORT" | "HOLD", string> = {
  BUY: "#3FB950",
  SHORT: "#F85149",
  HOLD: "#8B949E",
};

const POLL_MS = 2_000; // Polling interval for batch progress

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function safeParse(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function asNumber(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

function asSignal(v: unknown): "BUY" | "SHORT" | "HOLD" | undefined {
  return v === "BUY" || v === "SHORT" || v === "HOLD" ? v : undefined;
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatEta(remaining: number, avgMsPerTicker: number): string {
  if (remaining <= 0 || avgMsPerTicker <= 0) return "--:--";
  return formatElapsed(remaining * avgMsPerTicker);
}

function buildInitialTickerStates(tickers: readonly string[]): TickerStateMap {
  const next: Record<string, TickerState> = {};
  for (const t of tickers) {
    next[t] = { status: "pending" };
  }
  return next;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function RunAllProgressModal({
  batchId,
  initialTickers,
  onClose,
  onComplete,
}: RunAllProgressModalProps) {
  const [progress, setProgress] = useState<BatchProgress>({
    total: initialTickers.length,
    completed: 0,
    failed: 0,
    running: 0,
    status: "running",
    last_ticker: null,
    last_signal: null,
  });

  const [tickerStates, setTickerStates] = useState<TickerStateMap>(() =>
    buildInitialTickerStates(initialTickers),
  );
  const [startedAt] = useState<number>(() => Date.now());
  const [elapsedMs, setElapsedMs] = useState<number>(0);
  const [doneAt, setDoneAt] = useState<number | null>(null);

  // Track whether the final onComplete handoff has been fired to avoid
  // double-invocations when both the SSE "complete" event AND the polling
  // fallback converge.
  const completedRef = useRef<boolean>(false);

  /* ---- Elapsed timer ---- */

  useEffect(() => {
    if (doneAt !== null) return;
    const id = window.setInterval(() => {
      setElapsedMs(Date.now() - startedAt);
    }, 500);
    return () => window.clearInterval(id);
  }, [startedAt, doneAt]);

  /* ---- Finalize: fetch full results via /status then hand off ---- */

  const finalize = useCallback(async () => {
    if (completedRef.current) return;
    completedRef.current = true;
    try {
      const status = await getBatchStatus(batchId);
      setProgress((prev) => ({
        ...prev,
        total: status.total,
        completed: status.completed,
        failed: status.failed,
        running: status.running,
        status: status.status,
        last_ticker: status.last_ticker ?? null,
        last_signal: status.last_signal ?? null,
      }));
      setDoneAt(Date.now());
      onComplete(status.results);
    } catch {
      // If status fetch fails, still mark done so UI doesn't hang forever.
      setDoneAt(Date.now());
    }
  }, [batchId, onComplete]);

  /* ---- Polling fallback ---- */

  /* ---- Polling-based progress (replaces SSE which had reconnect issues) ---- */

  useEffect(() => {
    // Poll every 2 seconds for responsive UI

    const tick = async () => {
      if (completedRef.current) return;
      try {
        const status = await getBatchStatus(batchId);

        // Update progress counters
        setProgress((prev) => ({
          total: status.total,
          completed: status.completed,
          failed: status.failed,
          running: status.running,
          status: status.status,
          last_ticker: status.last_ticker ?? prev.last_ticker ?? null,
          last_signal: status.last_signal ?? prev.last_signal ?? null,
          total_cost_usd: status.total_cost_usd,
        }));

        // Reconcile per-ticker states from results
        if (status.results && status.results.length > 0) {
          // First: update ticker states in modal
          setTickerStates((prev) => {
            const next: Record<string, TickerState> = { ...prev };
            for (const item of status.results) {
              const existing = next[item.ticker];
              if (existing && existing.status === "complete") continue;
              const isError = item.data_gaps?.some((g: string) =>
                g.startsWith("pipeline_error"),
              );
              next[item.ticker] = {
                status: isError ? "failed" : "complete",
                signal: item.signal,
                conviction: item.conviction,
                cost_usd: item.cost_usd,
              };
            }
            return next;
          });
          // Second: live-update global store (outside setState to avoid render conflict)
          for (const item of status.results) {
            const isError = item.data_gaps?.some((g: string) =>
              g.startsWith("pipeline_error"),
            );
            if (!isError && item.signal) {
              useSignalsStore.getState().upsertTicker(item.ticker, {
                signal: item.signal,
                conviction: item.conviction ?? 0,
                cost_usd: item.cost_usd,
                cached: false,
              });
            }
          }
        }

        // Check for completion
        if (status.status === "complete" || status.status === "failed") {
          void finalize();
        }
      } catch {
        // Transient network error — next tick retries
      }
    };

    // Initial tick immediately
    void tick();

    // Poll at interval
    const id = window.setInterval(() => void tick(), POLL_MS);

    return () => window.clearInterval(id);
  }, [batchId, finalize]);

  /* ---- Escape key closes ---- */

  useEffect(() => {
    const handleKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  /* ---- Derived values ---- */

  const total = progress.total || initialTickers.length || 1;
  const finishedCount = progress.completed + progress.failed;
  const percent = Math.min(100, Math.round((finishedCount / total) * 100));
  const isDone = progress.status === "complete" || progress.status === "failed";
  const hasFailures = progress.failed > 0;

  const barColor = !isDone
    ? "#58a6ff"
    : hasFailures
      ? "#F85149"
      : "#3FB950";

  const avgMsPerTicker = finishedCount > 0 ? elapsedMs / finishedCount : 0;
  const remaining = Math.max(0, total - finishedCount);
  const etaText = isDone ? "done" : formatEta(remaining, avgMsPerTicker);

  /* ---- Ordered ticker list (same order as initialTickers) ---- */

  const orderedTickers = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const t of initialTickers) {
      if (!seen.has(t)) {
        seen.add(t);
        out.push(t);
      }
    }
    // Append any tickers that appeared via SSE but weren't in the initial set.
    for (const t of Object.keys(tickerStates)) {
      if (!seen.has(t)) {
        seen.add(t);
        out.push(t);
      }
    }
    return out;
  }, [initialTickers, tickerStates]);

  /* ---- Render ---- */

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
      data-testid="run-all-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Run All progress"
    >
      <div
        className="w-full max-w-2xl max-h-[80vh] overflow-hidden rounded-lg border border-white/[0.08] bg-[#0D1117] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-[#E6EDF3]">
              Run All — Fresh Pipeline
            </h2>
            <p className="mt-0.5 text-[10px] text-[#8B949E]">
              batch_id: <span className="font-mono">{batchId}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 py-1 text-lg text-[#8B949E] hover:bg-white/[0.05] hover:text-[#E6EDF3]"
          >
            {"\u00D7"}
          </button>
        </div>

        {/* Stats chips */}
        <div className="grid grid-cols-4 gap-2 border-b border-white/[0.08] px-4 py-3 text-[11px]">
          <div className="rounded border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-[#8B949E]">
              Total
            </div>
            <div className="font-mono text-sm text-[#E6EDF3]">
              {progress.total}
            </div>
          </div>
          <div className="rounded border border-[#3FB950]/30 bg-[#3FB950]/10 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-[#3FB950]">
              Completed
            </div>
            <div className="font-mono text-sm text-[#3FB950]">
              {progress.completed}
            </div>
          </div>
          <div className="rounded border border-[#F85149]/30 bg-[#F85149]/10 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-[#F85149]">
              Failed
            </div>
            <div className="font-mono text-sm text-[#F85149]">
              {progress.failed}
            </div>
          </div>
          <div className="rounded border border-[#58A6FF]/30 bg-[#58A6FF]/10 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-[#58A6FF]">
              Running
            </div>
            <div className="font-mono text-sm text-[#58A6FF]">
              {progress.running}
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <div className="border-b border-white/[0.08] px-4 py-3">
          <div className="mb-1 flex items-center justify-between text-[10px] text-[#8B949E]">
            <span>
              {finishedCount} / {total} ({percent}%)
            </span>
            <span className="font-mono">
              elapsed {formatElapsed(elapsedMs)} · eta {etaText}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-white/[0.05]">
            <div
              className="h-full transition-all"
              style={{
                width: `${percent}%`,
                backgroundColor: barColor,
              }}
              data-testid="run-all-progress-bar"
            />
          </div>
        </div>

        {/* Per-ticker list */}
        <div
          className="max-h-96 divide-y divide-white/[0.03] overflow-y-auto"
          data-testid="run-all-ticker-list"
        >
          {orderedTickers.map((ticker) => {
            const state: TickerState = tickerStates[ticker] ?? {
              status: "pending",
            };
            return (
              <TickerRow key={ticker} ticker={ticker} state={state} />
            );
          })}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-white/[0.08] bg-[#0D1117] px-4 py-2 text-[10px] text-[#8B949E]">
          <span>
            {isDone
              ? hasFailures
                ? `Done with ${progress.failed} failure${progress.failed === 1 ? "" : "s"}`
                : "Done — all tickers processed"
              : progress.last_ticker
                ? `Last: ${progress.last_ticker}${progress.last_signal ? ` (${progress.last_signal})` : ""}`
                : "Starting…"}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-white/[0.08] bg-white/[0.02] px-2 py-1 text-[10px] font-medium text-[#E6EDF3] hover:bg-white/[0.06]"
          >
            {isDone ? "Close" : "Hide"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Ticker row subcomponent                                            */
/* ------------------------------------------------------------------ */

interface TickerRowProps {
  ticker: string;
  state: TickerState;
}

function TickerRow({ ticker, state }: TickerRowProps) {
  const { status, signal, conviction, cost_usd: costUsd, error, currentStage } = state;

  const icon = statusIcon(status);
  const iconColor = statusColor(status);
  const stageLabel = currentStage ? (STAGE_LABELS[currentStage] ?? currentStage) : null;

  return (
    <div
      data-testid={`ticker-row-${ticker}`}
      data-status={status}
      className="flex items-center gap-2 px-4 py-1.5 text-[11px]"
    >
      <span
        className={`inline-flex w-5 justify-center ${status === "running" ? "animate-pulse" : ""}`}
        style={{ color: iconColor }}
        aria-label={status}
      >
        {icon}
      </span>
      <span className="w-16 font-mono font-semibold text-[#E6EDF3]">
        {ticker}
      </span>
      {/* Show current pipeline stage when running */}
      {status === "running" && stageLabel && (
        <span className="font-mono text-[10px] text-[#8B949E] italic">
          {stageLabel}
        </span>
      )}
      {signal && (
        <span
          className="inline-block rounded px-1.5 py-0.5 text-[9px] font-bold"
          style={{
            backgroundColor: SIGNAL_COLORS[signal] + "22",
            color: SIGNAL_COLORS[signal],
            border: `1px solid ${SIGNAL_COLORS[signal]}44`,
          }}
        >
          {signal}
          {typeof conviction === "number" ? ` ${conviction}` : ""}
        </span>
      )}
      {typeof costUsd === "number" && costUsd > 0 && (
        <span className="ml-auto font-mono text-[10px] text-[#8B949E]">
          ${costUsd.toFixed(2)}
        </span>
      )}
      {error && (
        <span
          className="ml-auto truncate text-[10px] text-[#F85149]"
          title={error}
        >
          {error}
        </span>
      )}
    </div>
  );
}

function statusIcon(status: TickerStatus): string {
  switch (status) {
    case "pending":
      return "\u23F3"; // hourglass
    case "running":
      return "\u25CF"; // filled circle (pulses via class)
    case "complete":
      return "\u2713"; // check
    case "failed":
      return "\u2717"; // cross
  }
}

function statusColor(status: TickerStatus): string {
  switch (status) {
    case "pending":
      return "#484F58";
    case "running":
      return "#58A6FF";
    case "complete":
      return "#3FB950";
    case "failed":
      return "#F85149";
  }
}
