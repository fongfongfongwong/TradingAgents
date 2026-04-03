"use client";

import type { AgentReport } from "@/lib/api";

interface AgentCardProps {
  report: AgentReport;
}

export default function AgentCard({ report }: AgentCardProps) {
  const signalColor =
    report.signal === "BUY"
      ? "text-green-400 bg-green-900/30 border-green-800"
      : report.signal === "SELL"
        ? "text-red-400 bg-red-900/30 border-red-800"
        : "text-gray-400 bg-gray-800/30 border-gray-700";

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-800/20 p-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h4 className="font-semibold text-white">{report.agent_name}</h4>
          <p className="text-xs text-gray-500">{report.role}</p>
        </div>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-xs font-bold ${signalColor}`}
        >
          {report.signal}
        </span>
      </div>

      {/* Confidence bar */}
      <div className="mb-3">
        <div className="mb-1 flex justify-between text-xs text-gray-400">
          <span>Confidence</span>
          <span>{(report.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-700">
          <div
            className="h-full rounded-full bg-brand-500"
            style={{ width: `${report.confidence * 100}%` }}
          />
        </div>
      </div>

      {/* Summary */}
      <p className="text-xs leading-relaxed text-gray-400">{report.summary}</p>
    </div>
  );
}
