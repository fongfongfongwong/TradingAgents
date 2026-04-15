"use client";

import { useCallback, useEffect, useState } from "react";
import { getCostsToday, type CostsToday } from "@/lib/api";
import { useSignalsStore } from "@/stores/signalsStore";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const UNIVERSE_RERANK_INTERVAL_S = 60;
const AGENT_CYCLE_BUDGET_S = 120;
const AGENT_CYCLE_TOTAL = 40;
const TRADE_WINDOW_INTERVAL_MIN = 30;

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type MarketPhase = "PRE" | "RTH" | "POST" | "CLOSED";

interface SourceHealth {
  name: string;
  color: string;
  ok: boolean;
  ageSeconds: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getETTime(): Date {
  return new Date(
    new Date().toLocaleString("en-US", { timeZone: "America/New_York" }),
  );
}

function getMarketPhase(et: Date): MarketPhase {
  const day = et.getDay();
  if (day === 0 || day === 6) return "CLOSED";
  const mins = et.getHours() * 60 + et.getMinutes();
  if (mins < 4 * 60) return "CLOSED";
  if (mins < 9 * 60 + 30) return "PRE";
  if (mins < 16 * 60) return "RTH";
  if (mins < 20 * 60) return "POST";
  return "CLOSED";
}

function getCloseCountdown(et: Date): string | null {
  const phase = getMarketPhase(et);
  if (phase !== "RTH") return null;
  const closeMin = 16 * 60;
  const nowMin = et.getHours() * 60 + et.getMinutes();
  const diff = closeMin - nowMin;
  if (diff <= 0) return null;
  const h = Math.floor(diff / 60);
  const m = diff % 60;
  return `${h}h ${m}m`;
}

function formatETClock(et: Date): string {
  return et.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function secondsUntilNextInterval(intervalMin: number): number {
  const now = new Date();
  const totalSec = now.getMinutes() * 60 + now.getSeconds();
  const intervalSec = intervalMin * 60;
  const remainder = totalSec % intervalSec;
  return remainder === 0 ? intervalSec : intervalSec - remainder;
}

/* ------------------------------------------------------------------ */
/*  Mock source health data                                            */
/*  TODO: Replace with `/api/v3/sources/status` when endpoint exists   */
/* ------------------------------------------------------------------ */

const MOCK_SOURCES: readonly SourceHealth[] = [
  { name: "polygon", color: "#a78bfa", ok: true, ageSeconds: 3 },
  { name: "yfin", color: "#4fc3f7", ok: true, ageSeconds: 8 },
  { name: "finnhub", color: "#10b981", ok: true, ageSeconds: 12 },
  { name: "quiver", color: "#ec7e00", ok: true, ageSeconds: 45 },
  { name: "cboe", color: "#4fc3f7", ok: true, ageSeconds: 22 },
  { name: "apewis", color: "#a78bfa", ok: false, ageSeconds: 310 },
  { name: "fred", color: "#10b981", ok: true, ageSeconds: 60 },
  { name: "f&g", color: "#ec7e00", ok: true, ageSeconds: 120 },
  { name: "anthropic", color: "#a78bfa", ok: true, ageSeconds: 1 },
] as const;

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function LivePill() {
  return (
    <span
      data-testid="live-pill"
      className="inline-flex items-center gap-1 rounded-full bg-[#10b981]/20 px-2 py-0.5 text-[10px] font-bold tracking-wider text-[#10b981]"
    >
      <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[#10b981]" />
      LIVE
    </span>
  );
}

function MarketClock({
  et,
  phase,
}: {
  et: Date;
  phase: MarketPhase;
}) {
  const closeIn = getCloseCountdown(et);
  const phaseColor: Record<MarketPhase, string> = {
    RTH: "#10b981",
    PRE: "#ec7e00",
    POST: "#ec7e00",
    CLOSED: "#8B949E",
  };

  return (
    <div data-testid="market-clock" className="flex items-center gap-2">
      <span
        className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[10px] font-bold"
        style={{ color: phaseColor[phase] }}
      >
        {phase}
      </span>
      <span className="font-mono text-xs text-[#C9D1D9]">
        {formatETClock(et)} ET
      </span>
      {closeIn && (
        <span className="font-mono text-[10px] text-[#8B949E]">
          close in {closeIn}
        </span>
      )}
    </div>
  );
}

function BudgetMeter({
  costs,
}: {
  costs: CostsToday | null;
}) {
  const spent = costs?.total_usd ?? 0;
  const budget = costs?.budget_daily_usd ?? 300;
  const pct = budget > 0 ? Math.min((spent / budget) * 100, 100) : 0;
  const barColor = pct > 90 ? "#e23b4a" : pct > 70 ? "#ec7e00" : "#10b981";

  return (
    <div data-testid="budget-meter" className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] text-[#8B949E]">Budget</span>
      <span className="font-mono text-xs font-bold text-[#C9D1D9]">
        ${spent.toFixed(2)}
      </span>
      <span className="font-mono text-[10px] text-[#8B949E]">
        / ${budget}
      </span>
      <div className="h-1 w-14 overflow-hidden rounded-full bg-[#1c2230]">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: barColor }}
        />
      </div>
    </div>
  );
}

function ErrorBadge({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span
      data-testid="error-badge"
      className="rounded bg-[#e23b4a] px-2.5 py-0.5 font-mono text-[10px] font-bold text-white"
    >
      ERR {count}
    </span>
  );
}

function CountdownSection({
  label,
  value,
  extra,
  testId,
  progressBar,
}: {
  label: string;
  value: string;
  extra?: string;
  testId: string;
  progressBar?: React.ReactNode;
}) {
  return (
    <div data-testid={testId} className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-[#8B949E]">
        {label}
      </span>
      <span className="font-mono text-sm font-bold text-[#4fc3f7]">
        {value}
      </span>
      {progressBar}
      {extra && (
        <span className="font-mono text-[10px] text-[#8B949E]">{extra}</span>
      )}
    </div>
  );
}

function SourceChip({ source }: { source: SourceHealth }) {
  const ageLabel =
    source.ageSeconds < 60
      ? `${source.ageSeconds}s`
      : `${Math.floor(source.ageSeconds / 60)}m`;

  return (
    <div
      data-testid={`source-chip-${source.name}`}
      className="flex items-center gap-1 rounded bg-white/5 px-1.5 py-0.5"
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: source.ok ? "#10b981" : "#ec7e00" }}
      />
      <span className="text-[10px] text-[#C9D1D9]">{source.name}</span>
      <span className="font-mono text-[9px] text-[#8B949E]">{ageLabel}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function TradeTopBar() {
  /* ---- Clock state ---- */
  const [now, setNow] = useState(() => new Date());
  const [etNow, setEtNow] = useState(() => getETTime());

  /* ---- Budget state ---- */
  const [costs, setCosts] = useState<CostsToday | null>(null);

  /* ---- Countdown state ---- */
  const [universeCountdown, setUniverseCountdown] = useState(
    UNIVERSE_RERANK_INTERVAL_S,
  );
  const [tradeWindowCountdown, setTradeWindowCountdown] = useState(() =>
    secondsUntilNextInterval(TRADE_WINDOW_INTERVAL_MIN),
  );

  /* ---- Zustand ---- */
  const batchProgress = useSignalsStore((s) => s.batchProgress);

  /* ---- Error count (count items with data_gaps) ---- */
  const items = useSignalsStore((s) => s.items);
  const errorCount = items.filter((it) =>
    it.data_gaps.some((g) => g.startsWith("pipeline_error")),
  ).length;

  /* ---- SSE mock heartbeat ---- */
  const [sseRate] = useState(42);

  /* ---- Fetch budget ---- */
  const fetchCosts = useCallback(async () => {
    try {
      const data = await getCostsToday();
      setCosts(data);
    } catch {
      /* swallow — budget meter shows $0.00 */
    }
  }, []);

  useEffect(() => {
    void fetchCosts();
    const id = setInterval(() => {
      void fetchCosts();
    }, 30_000);
    return () => clearInterval(id);
  }, [fetchCosts]);

  /* ---- Tick every second ---- */
  useEffect(() => {
    const id = setInterval(() => {
      setNow(new Date());
      setEtNow(getETTime());

      setUniverseCountdown((prev) => (prev <= 1 ? UNIVERSE_RERANK_INTERVAL_S : prev - 1));
      setTradeWindowCountdown(() => secondsUntilNextInterval(TRADE_WINDOW_INTERVAL_MIN));
    }, 1_000);
    return () => clearInterval(id);
  }, []);

  /* ---- Derived ---- */
  const phase = getMarketPhase(etNow);

  const agentCompleted = batchProgress?.completed ?? 0;
  const agentTotal = batchProgress?.total ?? AGENT_CYCLE_TOTAL;
  const agentPct =
    agentTotal > 0 ? Math.round((agentCompleted / agentTotal) * 100) : 0;
  const agentTimeRemaining = Math.max(
    0,
    AGENT_CYCLE_BUDGET_S - Math.round((agentPct / 100) * AGENT_CYCLE_BUDGET_S),
  );

  /* ---- Progress bar percentages ---- */
  const universeElapsed = UNIVERSE_RERANK_INTERVAL_S - universeCountdown;
  const universePct = (universeElapsed / UNIVERSE_RERANK_INTERVAL_S) * 100;

  const agentErrors = batchProgress?.failed ?? 0;
  const agentDonePct = agentTotal > 0 ? (agentCompleted / agentTotal) * 100 : 0;
  const agentErrPct = agentTotal > 0 ? (agentErrors / agentTotal) * 100 : 0;

  const tradeElapsed = TRADE_WINDOW_INTERVAL_MIN * 60 - tradeWindowCountdown;
  const tradePct = (tradeElapsed / (TRADE_WINDOW_INTERVAL_MIN * 60)) * 100;

  /* ---- Render ---- */
  return (
    <div className="shrink-0 border-b border-[#1c2230] bg-[#0a0d13]">
      {/* Row 1: Brand + Clock + Budget + Actions */}
      <div className="flex h-[42px] items-center gap-3 border-b border-[#1c2230] px-4">
        {/* Brand */}
        <h1 className="text-sm font-bold tracking-widest text-[#4fc3f7]">
          FLAB MASA
        </h1>
        <span className="font-mono text-[10px] text-[#8B949E]">
          vol-arb &middot; v3.2
        </span>

        <LivePill />

        <div className="mx-1 h-4 w-px bg-white/[0.08]" />

        <MarketClock et={etNow} phase={phase} />

        <div className="flex-1" />

        <BudgetMeter costs={costs} />

        <ErrorBadge count={errorCount} />

        {/* Fast refresh */}
        <button
          type="button"
          className="flex items-center gap-1.5 rounded border border-[#2a3246] bg-[#10161f] px-2 py-0.5 text-[10px] font-medium text-[#9ba7bb] transition-colors hover:bg-[#161d2a]"
          title="Fast Refresh"
        >
          Refresh
          <kbd className="rounded bg-white/5 px-1 py-px font-mono text-[9px] text-[#8B949E]">
            F
          </kbd>
        </button>

        {/* Deep Debate */}
        <button
          type="button"
          className="flex items-center gap-1.5 rounded bg-gradient-to-b from-[#6b4bf5] to-[#5a3ce0] px-2 py-0.5 text-[10px] font-bold text-white transition-opacity hover:opacity-90"
          title="Deep Debate"
        >
          Deep Debate
          <kbd className="rounded bg-white/20 px-1 py-px font-mono text-[9px] text-white/70">
            {"\u2318"}R
          </kbd>
        </button>
      </div>

      {/* Row 2: 3 countdown timers */}
      <div
        data-testid="countdown-row"
        className="flex h-[36px] items-center gap-6 border-b border-white/[0.04] px-4"
      >
        <CountdownSection
          testId="countdown-universe"
          label="Universe Re-rank"
          value={formatCountdown(universeCountdown)}
          progressBar={
            <div className="h-1 flex-1 max-w-[140px] rounded-full bg-[#10161f] overflow-hidden">
              <div className="h-full bg-[#4fc3f7] transition-all" style={{ width: `${universePct}%` }} />
            </div>
          }
        />

        <div className="h-3 w-px bg-white/[0.08]" />

        <CountdownSection
          testId="countdown-agent"
          label="Agent Cycle"
          value={`${agentCompleted}/${agentTotal}`}
          progressBar={
            <div className="h-1 flex-1 max-w-[140px] rounded-full bg-[#10161f] overflow-hidden relative">
              <div className="absolute h-full bg-[#10b981] transition-all" style={{ width: `${agentDonePct}%` }} />
              <div className="absolute h-full bg-[#e23b4a] transition-all" style={{ left: `${agentDonePct}%`, width: `${agentErrPct}%` }} />
            </div>
          }
          extra={`${formatCountdown(agentTimeRemaining)} left`}
        />

        <div className="h-3 w-px bg-white/[0.08]" />

        <CountdownSection
          testId="countdown-trade"
          label="Next Trade Window"
          value={formatCountdown(tradeWindowCountdown)}
          progressBar={
            <div className="h-1 flex-1 max-w-[140px] rounded-full bg-[#10161f] overflow-hidden">
              <div className="h-full bg-[#a78bfa] transition-all" style={{ width: `${tradePct}%` }} />
            </div>
          }
        />
      </div>

      {/* Row 3: 9-source health strip */}
      <div
        data-testid="source-strip"
        className="flex h-[30px] items-center gap-2 px-4"
      >
        {MOCK_SOURCES.map((src) => (
          <SourceChip key={src.name} source={src} />
        ))}

        <div className="flex-1" />

        {/* SSE heartbeat */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-[#8B949E]">SSE</span>
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[#10b981]" />
          <span className="font-mono text-[10px] text-[#C9D1D9]">
            {sseRate}/s
          </span>
        </div>
      </div>
    </div>
  );
}
