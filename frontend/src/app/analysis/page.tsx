"use client";

import { useState, type FormEvent } from "react";
import { startAnalysis, getAnalysis } from "@/lib/api";
import type { AnalysisStatus } from "@/lib/api";
import { useSSE, type SSEEvent } from "@/hooks/useSSE";
import AgentCard from "@/components/AgentCard";

export default function AnalysisPage() {
  const [ticker, setTicker] = useState("");
  const [numSteps, setNumSteps] = useState(10);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisStatus | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const { events, isConnected, error: sseError, connect } = useSSE();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!ticker.trim()) return;

    setLoading(true);
    setResult(null);
    setFormError(null);

    try {
      const { id } = await startAnalysis({
        ticker: ticker.toUpperCase().trim(),
        num_steps: numSteps,
      });

      // Connect to SSE stream
      connect(id);

      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const status = await getAnalysis(id);
          if (status.status === "completed" || status.status === "failed") {
            clearInterval(poll);
            setResult(status);
            setLoading(false);
          }
        } catch {
          clearInterval(poll);
          setLoading(false);
          setFormError("Failed to fetch analysis status.");
        }
      }, 3000);
    } catch {
      setLoading(false);
      setFormError("Failed to start analysis. Is the backend running?");
    }
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Run Analysis</h1>

      {/* Form */}
      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap items-end gap-4 rounded-lg border border-gray-800 bg-gray-800/30 p-5"
      >
        <div>
          <label className="mb-1 block text-xs text-gray-400">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            className="w-32 rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs text-gray-400">
            Debate Steps
          </label>
          <input
            type="number"
            value={numSteps}
            onChange={(e) => setNumSteps(Number(e.target.value))}
            min={1}
            max={50}
            className="w-20 rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
          />
        </div>

        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className="rounded-md bg-brand-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
        >
          {loading ? "Running..." : "Analyze"}
        </button>
      </form>

      {formError && (
        <p className="text-sm text-red-400">{formError}</p>
      )}

      {/* SSE Event Stream */}
      {(events.length > 0 || isConnected) && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">
            Live Progress{" "}
            {isConnected && (
              <span className="ml-2 inline-block h-2 w-2 animate-pulse rounded-full bg-green-400" />
            )}
          </h2>

          <div className="max-h-72 space-y-2 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950 p-4 font-mono text-xs">
            {events.map((ev, i) => (
              <EventLine key={i} event={ev} />
            ))}
          </div>

          {sseError && (
            <p className="mt-2 text-xs text-yellow-400">{sseError}</p>
          )}
        </section>
      )}

      {/* Result */}
      {result?.status === "completed" && result.result && (
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Result</h2>

          <div className="rounded-lg border border-gray-800 bg-gray-800/30 p-5">
            <div className="mb-4 flex items-center gap-4">
              <span
                className={`text-3xl font-bold ${
                  result.result.decision === "BUY"
                    ? "text-green-400"
                    : result.result.decision === "SELL"
                      ? "text-red-400"
                      : "text-gray-400"
                }`}
              >
                {result.result.decision}
              </span>
              <span className="text-lg text-gray-400">
                {(result.result.confidence * 100).toFixed(0)}% confidence
              </span>
            </div>
            <p className="text-sm text-gray-300">{result.result.reasoning}</p>
          </div>

          {/* Agent reports */}
          {result.result.agent_reports.length > 0 && (
            <div>
              <h3 className="mb-3 font-semibold">Agent Reports</h3>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {result.result.agent_reports.map((report) => (
                  <AgentCard key={report.agent_name} report={report} />
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {result?.status === "failed" && (
        <div className="rounded-lg border border-red-800 bg-red-900/20 p-4 text-sm text-red-300">
          Analysis failed: {result.error ?? "Unknown error"}
        </div>
      )}
    </div>
  );
}

/* ---------- helpers ---------- */

function EventLine({ event }: { event: SSEEvent }) {
  const colors: Record<string, string> = {
    agent_start: "text-blue-400",
    agent_progress: "text-gray-400",
    agent_complete: "text-green-400",
    debate_round: "text-purple-400",
    final_decision: "text-yellow-300",
    error: "text-red-400",
  };

  return (
    <div className={colors[event.type] ?? "text-gray-500"}>
      <span className="text-gray-600">
        {new Date(event.timestamp).toLocaleTimeString()}
      </span>{" "}
      [{event.type}]{event.agent ? ` (${event.agent})` : ""}: {event.message}
    </div>
  );
}
