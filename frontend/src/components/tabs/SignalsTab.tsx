"use client";

import { useCallback, useRef, useState } from "react";
import { useTicker } from "@/hooks/useTicker";
import {
  startAnalysisV3,
  getAnalysisV3,
  type V3AnalysisStatus,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const SIGNAL_COLORS: Record<string, string> = {
  BUY: "#10b981",
  SHORT: "#e23b4a",
  HOLD: "#ec7e00",
};

const POLL_INTERVAL_MS = 2_000;

/* ------------------------------------------------------------------ */
/*  Row state per ticker                                               */
/* ------------------------------------------------------------------ */

interface RowState {
  status: "idle" | "pending" | "running" | "complete" | "failed";
  analysisId: string | null;
  result: V3AnalysisStatus["result"];
  error: string | null;
  startedAt: number | null;
  latencyMs: number | null;
}

const INITIAL_ROW: RowState = {
  status: "idle",
  analysisId: null,
  result: null,
  error: null,
  startedAt: null,
  latencyMs: null,
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function SignalsTab() {
  const { watchlist: rawWatchlist } = useTicker();
  const watchlist = rawWatchlist ?? [];
  const [rows, setRows] = useState<Map<string, RowState>>(new Map());
  const abortRef = useRef(false);

  /* ---- helpers --------------------------------------------------- */

  const getRow = useCallback(
    (ticker: string): RowState => rows.get(ticker) ?? { ...INITIAL_ROW },
    [rows],
  );

  const patchRow = useCallback(
    (ticker: string, patch: Partial<RowState>) =>
      setRows((prev) => {
        const next = new Map(prev);
        const current = prev.get(ticker) ?? { ...INITIAL_ROW };
        next.set(ticker, { ...current, ...patch });
        return next;
      }),
    [],
  );

  /* ---- poll until terminal state --------------------------------- */

  const pollUntilDone = useCallback(
    async (ticker: string, analysisId: string) => {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        if (abortRef.current) return;

        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        if (abortRef.current) return;

        try {
          const res = await getAnalysisV3(analysisId);

          if (res.status === "complete" || res.status === "failed") {
            const row = getRow(ticker);
            const latencyMs =
              row.startedAt !== null ? Date.now() - row.startedAt : null;

            patchRow(ticker, {
              status: res.status,
              result: res.result,
              error: res.error ?? null,
              latencyMs,
            });
            return;
          }

          patchRow(ticker, { status: res.status });
        } catch (err: unknown) {
          const message =
            err instanceof Error ? err.message : "Poll error";
          patchRow(ticker, { status: "failed", error: message });
          return;
        }
      }
    },
    [getRow, patchRow],
  );

  /* ---- analyze a single ticker ---------------------------------- */

  const analyzeTicker = useCallback(
    async (ticker: string) => {
      patchRow(ticker, {
        ...INITIAL_ROW,
        status: "pending",
        startedAt: Date.now(),
      });

      try {
        const res = await startAnalysisV3({ ticker });
        patchRow(ticker, {
          status: res.status,
          analysisId: res.analysis_id,
        });

        if (res.status === "complete" || res.status === "failed") {
          patchRow(ticker, {
            status: res.status,
            result: res.result,
            error: res.error ?? null,
            latencyMs: 0,
          });
          return;
        }

        await pollUntilDone(ticker, res.analysis_id);
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Start failed";
        patchRow(ticker, { status: "failed", error: message });
      }
    },
    [patchRow, pollUntilDone],
  );

  /* ---- analyze all watchlist ------------------------------------- */

  const analyzeAll = useCallback(async () => {
    abortRef.current = false;
    const promises = watchlist.map((t) => analyzeTicker(t));
    await Promise.allSettled(promises);
  }, [watchlist, analyzeTicker]);

  /* ---- derived --------------------------------------------------- */

  const isAnyRunning = watchlist.some((t) => {
    const s = getRow(t).status;
    return s === "pending" || s === "running";
  });

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[#f7f8f8]">
          Watchlist Signals
        </h2>

        <button
          onClick={analyzeAll}
          disabled={isAnyRunning}
          className="rounded border border-[#5e6ad2]/40 bg-[#5e6ad2]/10 px-3 py-1.5 text-xs font-medium text-[#8b93e6] transition-colors hover:bg-[#5e6ad2]/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isAnyRunning ? "Running..." : "Analyze All"}
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded border border-white/[0.06]">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-white/[0.06] bg-[#0f1011] text-[#8a8f98]">
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Signal</th>
              <th className="px-3 py-2 font-medium">Conviction</th>
              <th className="px-3 py-2 font-medium text-right">Thesis</th>
              <th className="px-3 py-2 font-medium text-right">Antithesis</th>
              <th className="px-3 py-2 font-medium text-right">Base Rate</th>
              <th className="px-3 py-2 font-medium text-right">Shares</th>
              <th className="px-3 py-2 font-medium text-right">Latency</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {watchlist.map((ticker) => {
              const row = getRow(ticker);
              return (
                <SignalRow
                  key={ticker}
                  ticker={ticker}
                  row={row}
                  onAnalyze={() => analyzeTicker(ticker)}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  SignalRow                                                           */
/* ------------------------------------------------------------------ */

interface SignalRowProps {
  ticker: string;
  row: RowState;
  onAnalyze: () => void;
}

function SignalRow({ ticker, row, onAnalyze }: SignalRowProps) {
  const isBusy = row.status === "pending" || row.status === "running";
  const result = row.result;

  const signal = result?.signal?.toUpperCase() ?? null;
  const signalColor = signal ? SIGNAL_COLORS[signal] ?? "#8a8f98" : undefined;

  const conviction = result?.conviction ?? null;
  const thesisScore = result?.thesis?.confidence_score ?? null;
  const antithesisScore = result?.antithesis?.confidence_score ?? null;
  const baseRateUp = result?.base_rate?.base_rate_probability_up ?? null;
  const shares = result?.risk?.final_shares ?? null;
  const latencyMs = row.latencyMs;

  const handleRowClick = () => {
    // eslint-disable-next-line no-console
    console.log("[SignalsTab] row clicked:", ticker, result);
  };

  return (
    <tr
      onClick={handleRowClick}
      className="cursor-pointer border-b border-white/[0.04] transition-colors hover:bg-white/[0.03]"
    >
      {/* Ticker */}
      <td className="px-3 py-2 font-mono font-semibold text-[#f7f8f8]">
        {ticker}
      </td>

      {/* Signal */}
      <td className="px-3 py-2">
        {signal ? (
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-bold"
            style={{
              color: signalColor,
              backgroundColor: `${signalColor}18`,
            }}
          >
            {signal}
          </span>
        ) : (
          <span className="text-[#8a8f98]">&mdash;</span>
        )}
      </td>

      {/* Conviction progress bar */}
      <td className="px-3 py-2">
        {conviction !== null ? (
          <div className="flex items-center gap-2">
            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/[0.08]">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${conviction}%`,
                  backgroundColor: signalColor ?? "#8a8f98",
                }}
              />
            </div>
            <span className="font-mono text-[#d0d6e0]">
              {conviction}
            </span>
          </div>
        ) : (
          <span className="text-[#8a8f98]">&mdash;</span>
        )}
      </td>

      {/* Thesis */}
      <td className="px-3 py-2 text-right font-mono text-[#d0d6e0]">
        {thesisScore !== null ? thesisScore : <span className="text-[#8a8f98]">&mdash;</span>}
      </td>

      {/* Antithesis */}
      <td className="px-3 py-2 text-right font-mono text-[#d0d6e0]">
        {antithesisScore !== null ? antithesisScore : <span className="text-[#8a8f98]">&mdash;</span>}
      </td>

      {/* Base Rate */}
      <td className="px-3 py-2 text-right font-mono text-[#d0d6e0]">
        {baseRateUp !== null ? (
          `${(baseRateUp * 100).toFixed(0)}%`
        ) : (
          <span className="text-[#8a8f98]">&mdash;</span>
        )}
      </td>

      {/* Shares */}
      <td className="px-3 py-2 text-right font-mono text-[#d0d6e0]">
        {shares !== null ? shares : <span className="text-[#8a8f98]">&mdash;</span>}
      </td>

      {/* Latency */}
      <td className="px-3 py-2 text-right font-mono text-[#8a8f98]">
        {latencyMs !== null ? `${(latencyMs / 1000).toFixed(1)}s` : <span>&mdash;</span>}
      </td>

      {/* Status */}
      <td className="px-3 py-2">
        <StatusBadge status={row.status} error={row.error} />
      </td>

      {/* Action */}
      <td className="px-3 py-2">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onAnalyze();
          }}
          disabled={isBusy}
          className="rounded border border-white/[0.08] px-2 py-0.5 text-[10px] text-[#8a8f98] transition-colors hover:bg-white/[0.06] hover:text-[#d0d6e0] disabled:cursor-not-allowed disabled:opacity-30"
        >
          {isBusy ? "..." : "Analyze"}
        </button>
      </td>
    </tr>
  );
}

/* ------------------------------------------------------------------ */
/*  StatusBadge                                                        */
/* ------------------------------------------------------------------ */

interface StatusBadgeProps {
  status: RowState["status"];
  error: string | null;
}

function StatusBadge({ status, error }: StatusBadgeProps) {
  switch (status) {
    case "idle":
      return <span className="text-[#8a8f98]">&mdash;</span>;

    case "pending":
    case "running":
      return (
        <span className="flex items-center gap-1.5 text-[#8b93e6]">
          <span className="inline-block h-2 w-2 animate-spin rounded-sm border border-[#8b93e6] border-t-transparent" />
          Running...
        </span>
      );

    case "complete":
      return <span className="text-[#10b981]">Complete</span>;

    case "failed":
      return (
        <span className="text-[#e23b4a]" title={error ?? undefined}>
          Failed
        </span>
      );

    default:
      return null;
  }
}
