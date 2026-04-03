"use client";

import { useState, type FormEvent } from "react";
import { startAnalysis, getAnalysis } from "@/lib/api";
import type { AnalysisStatus } from "@/lib/api";
import { useSSE, type SSEEvent } from "@/hooks/useSSE";
import AgentCard from "@/components/AgentCard";

const ANALYSTS = [
  {
    name: "Market Analyst",
    key: "market",
    tier: "Extract",
    tierColor: "bg-blue-900/40 text-blue-300 border-blue-700",
    description:
      "Analyzes price action, technical indicators, volume patterns, and market microstructure signals.",
  },
  {
    name: "Social Analyst",
    key: "social",
    tier: "Extract",
    tierColor: "bg-blue-900/40 text-blue-300 border-blue-700",
    description:
      "Monitors Reddit, Twitter/X, StockTwits sentiment and retail trader positioning via social media.",
  },
  {
    name: "News Analyst",
    key: "news",
    tier: "Extract",
    tierColor: "bg-blue-900/40 text-blue-300 border-blue-700",
    description:
      "Processes breaking news, earnings reports, and press releases through Google News and Finnhub.",
  },
  {
    name: "Fundamentals Analyst",
    key: "fundamentals",
    tier: "Reason",
    tierColor: "bg-purple-900/40 text-purple-300 border-purple-700",
    description:
      "Evaluates financial statements, valuation ratios, earnings quality, and SEC filings.",
  },
  {
    name: "Options Analyst",
    key: "options",
    tier: "Reason",
    tierColor: "bg-purple-900/40 text-purple-300 border-purple-700",
    description:
      "Reads options flow, put/call ratios, unusual activity, and implied volatility surfaces.",
  },
  {
    name: "Macro Analyst",
    key: "macro",
    tier: "Reason",
    tierColor: "bg-purple-900/40 text-purple-300 border-purple-700",
    description:
      "Assesses macroeconomic indicators, Fed policy, yield curves, and cross-asset correlations.",
  },
];

const PIPELINE_TIERS = [
  { name: "Extract", color: "text-blue-400", desc: "Raw data collection and signal extraction" },
  { name: "Reason", color: "text-purple-400", desc: "Deep analysis and cross-signal reasoning" },
  { name: "Decide", color: "text-yellow-300", desc: "Bull/Bear debate and final trade decision" },
];

export default function AnalysisPage() {
  const [ticker, setTicker] = useState("");
  const [numSteps, setNumSteps] = useState(10);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisStatus | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [selectedAnalysts, setSelectedAnalysts] = useState<Set<string>>(
    new Set(ANALYSTS.map((a) => a.key))
  );

  const { events, isConnected, error: sseError, connect } = useSSE();

  function toggleAnalyst(key: string) {
    setSelectedAnalysts((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

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
      <div>
        <h1 className="text-2xl font-bold">Run Analysis</h1>
        <p className="mt-1 text-sm text-gray-400">
          Configure and launch a multi-agent analysis with the 3-tier pipeline.
        </p>
      </div>

      {/* Pipeline Tiers Overview */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
          Analysis Pipeline
        </h2>
        <div className="flex items-center gap-2">
          {PIPELINE_TIERS.map((tier, idx) => (
            <div key={tier.name} className="flex items-center gap-2">
              <div className="rounded-md border border-gray-700 bg-gray-800/50 px-3 py-2 text-center">
                <p className={`text-sm font-bold ${tier.color}`}>{tier.name}</p>
                <p className="text-xs text-gray-500">{tier.desc}</p>
              </div>
              {idx < PIPELINE_TIERS.length - 1 && (
                <span className="text-gray-600">&#8594;</span>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Analyst Selection */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
          Available Analysts ({selectedAnalysts.size} / {ANALYSTS.length} selected)
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ANALYSTS.map((analyst) => {
            const selected = selectedAnalysts.has(analyst.key);
            return (
              <button
                key={analyst.key}
                type="button"
                onClick={() => toggleAnalyst(analyst.key)}
                className={`rounded-lg border p-4 text-left transition-all ${
                  selected
                    ? "border-brand-600 bg-brand-900/20 ring-1 ring-brand-600/50"
                    : "border-gray-800 bg-gray-800/20 opacity-60 hover:opacity-80"
                }`}
              >
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white">{analyst.name}</h3>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs font-medium ${analyst.tierColor}`}
                  >
                    {analyst.tier}
                  </span>
                </div>
                <p className="text-xs leading-relaxed text-gray-400">
                  {analyst.description}
                </p>
                <div className="mt-2 flex items-center gap-1.5">
                  <div
                    className={`h-3 w-3 rounded-sm border ${
                      selected
                        ? "border-brand-500 bg-brand-500"
                        : "border-gray-600 bg-transparent"
                    }`}
                  >
                    {selected && (
                      <svg viewBox="0 0 12 12" className="h-3 w-3 text-white" fill="none">
                        <path
                          d="M2.5 6L5 8.5L9.5 3.5"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </div>
                  <span className="text-xs text-gray-500">
                    {selected ? "Enabled" : "Disabled"}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </section>

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

        <span className="text-xs text-gray-500">
          {selectedAnalysts.size} analysts active
        </span>
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
