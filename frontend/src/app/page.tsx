"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./trading-console.css";

import { useTicker } from "@/hooks/useTicker";
import { useSignalsStore } from "@/stores/signalsStore";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { usePricePolling } from "@/hooks/usePricePolling";
import { useUniverseRerank } from "@/hooks/useUniverseRerank";
import { useKeyboardNav } from "@/hooks/useKeyboardNav";
import {
  getBatchSignals,
  startBatch,
  getDivergence,
  getScoredNews,
  getCostsToday,
  startAnalysisV3,
  getSourcesStatus,
  type BatchSignalItem,
  type DivergenceData,
  type ScoredHeadline,
  type V3FinalDecision,
  type CostsToday,
  type SourceProbeResult,
} from "@/lib/api";
import { useSSE, type SSEEvent, type SSEEventType } from "@/hooks/useSSE";
import {
  type PresetKey,
  ALL_PRESET_KEYS,
  INITIAL_PRESETS,
  PRESET_META,
  applyPresetFilters,
  computePresetCounts,
} from "@/lib/presetFilters";
import {
  computeFlipDelta,
  freshChipColor,
  formatFreshLabel,
  freshAgeFromLatency,
} from "@/lib/signalDiff";
import { sortValue, type SortKey } from "@/lib/signalSort";

/* ---- Tab components ---- */
import RunAllProgressModal from "@/components/dashboard/RunAllProgressModal";
import ChartTab from "@/components/tabs/ChartTab";
import OptionsTab from "@/components/tabs/OptionsTab";
import HoldingsTab from "@/components/tabs/HoldingsTab";
import AnalysisTab from "@/components/tabs/AnalysisTab";
import BacktestTab from "@/components/tabs/BacktestTab";
import SettingsTab from "@/components/tabs/SettingsTab";
import DataSourcesTab from "@/components/tabs/DataSourcesTab";

/* ------------------------------------------------------------------ */
/*  Shared TabId type (re-exported for terminal components)            */
/* ------------------------------------------------------------------ */

export type TabId =
  | "chart"
  | "analysis"
  | "signals"
  | "options"
  | "holdings"
  | "backtest"
  | "settings"
  | "sources";

/* ------------------------------------------------------------------ */
/*  Tab definitions for the bottom-left detail area                    */
/* ------------------------------------------------------------------ */

const DETAIL_TABS: { id: TabId; label: string; shortcut: string }[] = [
  { id: "analysis", label: "Inspector", shortcut: "1" },
  { id: "chart", label: "Chart", shortcut: "2" },
  { id: "options", label: "Options", shortcut: "3" },
  { id: "holdings", label: "Debate Full", shortcut: "4" },
  { id: "backtest", label: "Backtest", shortcut: "5" },
  { id: "settings", label: "Settings", shortcut: "6" },
  { id: "sources", label: "Sources", shortcut: "7" },
];

/* ------------------------------------------------------------------ */
/*  Source health chip data                                            */
/* ------------------------------------------------------------------ */

function formatSourceAge(probe: SourceProbeResult): string {
  if (!probe.reachable) return "down";
  if (probe.rate_limit_pct > 80) return `${probe.rate_limit_pct.toFixed(0)}% rpm`;
  if (probe.freshness_seconds !== null) {
    if (probe.freshness_seconds < 60) return `${Math.round(probe.freshness_seconds)}s`;
    if (probe.freshness_seconds < 3600) return `${Math.round(probe.freshness_seconds / 60)}m`;
    return `${(probe.freshness_seconds / 3600).toFixed(1)}h`;
  }
  return `${Math.round(probe.latency_ms)}ms`;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function signalClass(signal: string): string {
  const s = signal.toUpperCase();
  if (s === "BUY" || s === "LONG") return "buy";
  if (s === "SHORT" || s === "SELL") return "sell";
  return "hold";
}

/** Classify news source credibility: 1 = top-tier, 2 = established, 3 = low/unknown. */
const _TIER1_SOURCES = new Set([
  "reuters", "bloomberg", "wsj", "wall street journal", "financial times",
  "ft", "ap", "associated press", "cnbc", "sec", "federal reserve",
  "barrons", "barron's", "economist", "nyt", "new york times",
]);
const _TIER2_SOURCES = new Set([
  "yahoo finance", "yahoo", "marketwatch", "seeking alpha", "benzinga",
  "investing.com", "zacks", "thestreet", "morningstar", "motley fool",
  "insider monkey", "tipranks", "nasdaq", "cnn business", "forbes",
  "business insider", "fortune", "guardian",
]);

function newsSourceTier(source: string | null): number {
  if (!source) return 3;
  const s = source.toLowerCase().trim();
  if (_TIER1_SOURCES.has(s)) return 1;
  for (const t of _TIER1_SOURCES) { if (s.includes(t)) return 1; }
  if (_TIER2_SOURCES.has(s)) return 2;
  for (const t of _TIER2_SOURCES) { if (s.includes(t)) return 2; }
  return 3;
}

function formatClock(): { time: string; state: string; closeIn: string } {
  const now = new Date();
  const et = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const h = et.getHours();
  const m = et.getMinutes();
  const s = et.getSeconds();
  const timeStr = `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")} ET`;

  const isRTH = (h > 9 || (h === 9 && m >= 30)) && h < 16;
  const isPre = (h >= 4 && h < 9) || (h === 9 && m < 30);
  const state = isRTH ? "RTH" : isPre ? "PRE" : "AH";

  let closeIn = "";
  if (isRTH) {
    const closeMinutes = 16 * 60 - (h * 60 + m);
    const ch = Math.floor(closeMinutes / 60);
    const cm = closeMinutes % 60;
    closeIn = `close in ${ch}h ${cm}m`;
  } else if (isPre) {
    const openMinutes = 9 * 60 + 30 - (h * 60 + m);
    const oh = Math.floor(openMinutes / 60);
    const om = openMinutes % 60;
    closeIn = `opens in ${oh}h ${om}m`;
  } else {
    closeIn = "market closed";
  }

  return { time: timeStr, state, closeIn };
}

function formatCountdown(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffSec = Math.max(0, (Date.now() - then) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  return `${diffHr}h ${diffMin % 60}m`;
}

/* ------------------------------------------------------------------ */
/*  Pipeline stage tracking for agent pipeline (right panel)          */
/* ------------------------------------------------------------------ */

const EVENT_TO_STAGE: Partial<Record<SSEEventType, string>> = {
  materialized: "materialize",
  screened: "screen",
  thesis_complete: "thesis",
  antithesis_complete: "antithesis",
  base_rate_complete: "base_rate",
  synthesis_complete: "synthesis",
  risk_complete: "risk",
};

interface PipeStage {
  key: string;
  label: string;
  status: "queue" | "run" | "done" | "err";
  detail: string;
  time: string;
}

function buildInitialPipeStages(): PipeStage[] {
  return [
    { key: "materialize", label: "materialize", status: "queue", detail: "", time: "" },
    { key: "thesis", label: "thesis", status: "queue", detail: "", time: "" },
    { key: "antithesis", label: "antithesis", status: "queue", detail: "", time: "" },
    { key: "base_rate", label: "base_rate", status: "queue", detail: "", time: "" },
    { key: "synthesis", label: "synthesis", status: "queue", detail: "", time: "" },
    { key: "har-rv", label: "har-rv", status: "queue", detail: "", time: "" },
    { key: "risk", label: "risk", status: "queue", detail: "", time: "" },
  ];
}

/* ------------------------------------------------------------------ */
/*  Divergence helpers                                                 */
/* ------------------------------------------------------------------ */

function divBiasTag(composite: number): { label: string; cls: string } {
  if (composite > 0.15) return { label: "BULLISH BIAS", cls: "bull" };
  if (composite > 0.05) return { label: "BULLISH LEAN", cls: "bull-lean" };
  if (composite >= -0.05) return { label: "NEUTRAL", cls: "neutral" };
  if (composite > -0.15) return { label: "BEARISH LEAN", cls: "bear-lean" };
  return { label: "BEARISH BIAS", cls: "bear" };
}

function divSegClass(value: number): string {
  if (value > 0.15) return "bull";
  if (value > 0.05) return "bull-lean";
  if (value >= -0.05) return "neutral";
  if (value > -0.15) return "bear-lean";
  return "bear";
}

const DIMENSION_WEIGHTS: Record<string, number> = {
  institutional: 0.35,
  options: 0.25,
  price_action: 0.20,
  news: 0.15,
  retail: 0.05,
};

/* ================================================================== */
/*  MAIN PAGE COMPONENT                                                */
/* ================================================================== */

export default function DashboardPage() {
  const { ticker, setTicker } = useTicker();
  const {
    items: rawItems, prevItems, lastRefreshedAt, setItems,
    snapshotForDiff, upsertTicker,
    batchProgress, priceMap, setAutoRefresh,
  } = useSignalsStore();

  // Merge priceMap into items so SignalRow sees last_price / change_pct
  const items = useMemo(
    () =>
      rawItems.map((it) => {
        const snap = priceMap[it.ticker];
        if (!snap) return it;
        return { ...it, last_price: snap.last, change_pct: snap.change_pct };
      }),
    [rawItems, priceMap],
  );
  const { allTickers, equityTickers, etfTickers } = useUniverseRerank();
  usePricePolling(); // Poll prices every 30s, merge into signalsStore
  const equitySet = useMemo(() => new Set(equityTickers), [equityTickers]);
  const etfSet = useMemo(() => new Set(etfTickers), [etfTickers]);
  const { events, connectV3 } = useSSE();

  // ---- State ----
  const [activeTab, setActiveTab] = useState<TabId>("analysis");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [segment, setSegment] = useState<"all" | "equity" | "etf">("all");
  const [activePresets, setActivePresets] = useState<Record<PresetKey, boolean>>(INITIAL_PRESETS);
  const [sortKey, setSortKey] = useState<SortKey>("predicted_rv_1d_pct");
  const [refreshInterval, setRefreshInterval] = useState(30 * 60 * 1000);
  const [clock, setClock] = useState(formatClock);
  const [divData, setDivData] = useState<DivergenceData | null>(null);
  const [divError, setDivError] = useState(false);
  const divRetryRef = useRef(0);
  const divRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [news, setNews] = useState<ScoredHeadline[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [expandedNews, setExpandedNews] = useState<string | null>(null);
  const [pipeStages, setPipeStages] = useState<PipeStage[]>(buildInitialPipeStages);
  const [fullDecision, setFullDecision] = useState<V3FinalDecision | null>(null);
  const [costs, setCosts] = useState<CostsToday | null>(null);
  const [sourcesStatus, setSourcesStatus] = useState<SourceProbeResult[]>([]);
  const errCount = useMemo(
    () => items.filter((i) => i.data_gaps?.some((g) => g.startsWith("pipeline_error"))).length,
    [items],
  );
  const [universeCountdown, setUniverseCountdown] = useState(60);
  const [tradeWindow, setTradeWindow] = useState(0);
  const [sseEventCount, setSseEventCount] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [backendAlive, setBackendAlive] = useState(true);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [batchTickers, setBatchTickers] = useState<string[]>([]);

  // ---- Inspector button state (P0-4) ----
  const [pinnedTickers, setPinnedTickers] = useState<Set<string>>(new Set());
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleInspectorRerun = useCallback(async (tk: string) => {
    // Reset pipeline stages so user sees fresh progress
    setPipeStages(buildInitialPipeStages());

    try {
      const signals = await getBatchSignals([tk]);
      if (signals.length > 0) {
        upsertTicker(tk, signals[0]);
      }
    } catch (err) {
      console.error("Inspector rerun getBatchSignals:", err);
    }
    // Start V3 pipeline and connect SSE so pipeline stages update
    try {
      const resp = await startAnalysisV3({ ticker: tk });
      connectV3(resp.analysis_id);
    } catch (err) {
      console.error("Inspector rerun startAnalysisV3:", err);
    }
  }, [upsertTicker, connectV3]);

  const handleInspectorPin = useCallback((tk: string) => {
    setPinnedTickers((prev) => {
      const next = new Set(prev);
      if (next.has(tk)) {
        next.delete(tk);
      } else {
        next.add(tk);
      }
      return next;
    });
  }, []);

  const handleInspectorCopy = useCallback((it: BatchSignalItem) => {
    const text = `${it.ticker}: ${it.signal} conv=${it.conviction} EV=${it.expected_value_pct != null ? `${it.expected_value_pct.toFixed(1)}%` : "N/A"}`;
    navigator.clipboard.writeText(text).then(() => {
      setCopyFeedback("\u2713 Copied");
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopyFeedback(null), 1500);
    }).catch(() => {
      setCopyFeedback("Failed");
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopyFeedback(null), 1500);
    });
  }, []);

  // ---- Command palette keyboard shortcut ----
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // ---- Backend health check (BUG-023) ----
  useEffect(() => {
    const check = () =>
      fetch("http://localhost:8000/health")
        .then((r) => setBackendAlive(r.ok))
        .catch(() => setBackendAlive(false));
    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, []);

  // ---- Clock tick + countdown timers ----
  useEffect(() => {
    const id = setInterval(() => {
      setClock(formatClock());
      // Universe countdown: 60s cycle
      setUniverseCountdown((prev) => (prev <= 0 ? 60 : prev - 1));
      // Trade window: next 5-min bar
      const nowMs = Date.now();
      const fiveMin = 5 * 60 * 1000;
      const nextBar = Math.ceil(nowMs / fiveMin) * fiveMin;
      setTradeWindow(nextBar - nowMs);
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // ---- Costs (poll every 30s, pause when tab hidden — BUG-019) ----
  useEffect(() => {
    const fetchCosts = () => getCostsToday().then(setCosts).catch(() => setCosts(null));
    fetchCosts();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchCosts();
      }
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  // ---- Sources status (poll every 60s) ----
  useEffect(() => {
    const fetchSources = () =>
      getSourcesStatus().then(setSourcesStatus).catch(() => {});
    fetchSources();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchSources();
      }
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  // ---- Fetch signals when universe changes ----
  const fetchSignals = useCallback(() => {
    if (allTickers.length === 0) return;
    getBatchSignals(allTickers)
      .then((data) => { setFetchError(null); setItems(data); })
      .catch((err) => {
        console.error("Failed to fetch batch signals:", err);
        setFetchError(err instanceof Error ? err.message : "Failed to fetch signals");
      });
  }, [allTickers, setItems]);

  useEffect(() => {
    fetchSignals();
  }, [fetchSignals]);

  // ---- Run All / Deep Debate ----
  const FALLBACK_TICKERS = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT", "META"];
  const effectiveTickers = allTickers.length > 0 ? allTickers : FALLBACK_TICKERS;

  const handleRunAll = useCallback(async () => {
    if (effectiveTickers.length === 0) return;

    snapshotForDiff();
    try {
      const { batch_id } = await startBatch(effectiveTickers, true);
      setBatchTickers([...effectiveTickers]);
      setActiveBatchId(batch_id);
    } catch (err) {
      console.error("handleRunAll start:", err);
      setFetchError(err instanceof Error ? `Deep Debate failed: ${err.message}` : "Deep Debate failed to start");
    }
  }, [effectiveTickers, snapshotForDiff]);

  // ---- Deep Debate keyboard shortcut (Cmd+R / Ctrl+R) ----
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "r") {
        e.preventDefault();
        handleRunAll();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleRunAll]);

  // ---- Auto-refresh ----
  const autoRefresh = useAutoRefresh({
    intervalMs: refreshInterval,
    enabled: true,
    onRefresh: fetchSignals,
  });

  // Sync auto-refresh state into the Zustand store so TopBar and
  // SignalTable can read countdown / toggle without prop drilling.
  useEffect(() => {
    setAutoRefresh({
      autoRefreshEnabled: autoRefresh.isEnabled,
      nextRefreshIn: autoRefresh.nextRefreshIn,
      toggleAutoRefresh: autoRefresh.toggle,
      refreshNow: autoRefresh.refreshNow,
    });
  }, [autoRefresh.isEnabled, autoRefresh.nextRefreshIn, autoRefresh.toggle, autoRefresh.refreshNow, setAutoRefresh]);

  // ---- Fetch divergence when ticker changes (with auto-retry) ----
  const fetchDivergence = useCallback(
    (tk: string, attempt = 0) => {
      setDivError(false);
      getDivergence(tk)
        .then(setDivData)
        .catch(() => {
          setDivData(null);
          if (attempt < 3) {
            const delay = 1000 * Math.pow(2, attempt); // 1s, 2s, 4s
            divRetryRef.current = attempt + 1;
            divRetryTimerRef.current = setTimeout(
              () => fetchDivergence(tk, attempt + 1),
              delay,
            );
          } else {
            divRetryRef.current = 0;
            setDivError(true);
          }
        });
    },
    [],
  );

  useEffect(() => {
    divRetryRef.current = 0;
    if (divRetryTimerRef.current) {
      clearTimeout(divRetryTimerRef.current);
      divRetryTimerRef.current = null;
    }
    fetchDivergence(ticker);
    return () => {
      if (divRetryTimerRef.current) {
        clearTimeout(divRetryTimerRef.current);
        divRetryTimerRef.current = null;
      }
    };
  }, [ticker, fetchDivergence]);

  // ---- Fetch news when ticker changes ----
  useEffect(() => {
    setNewsLoading(true);
    getScoredNews(ticker, 20)
      .then(setNews)
      .catch(() => setNews([]))
      .finally(() => setNewsLoading(false));
  }, [ticker]);

  // ---- Pipeline stage tracking from SSE events ----
  const pipeTimestamps = useRef<Record<string, number>>({});
  const pipeConnectTime = useRef(Date.now());
  const lastProcessedEventIdx = useRef(0);
  const selectedTicker = ticker;

  useEffect(() => {
    setPipeStages(buildInitialPipeStages());
    pipeTimestamps.current = {};
    pipeConnectTime.current = Date.now();
    lastProcessedEventIdx.current = events.length;
  }, [selectedTicker]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (events.length === 0) return;
    // Process ALL new events since last processed index
    const startIdx = lastProcessedEventIdx.current;
    if (startIdx >= events.length) return;
    lastProcessedEventIdx.current = events.length;

    for (let ei = startIdx; ei < events.length; ei++) {
      const evt = events[ei];
      // Skip events that belong to a different ticker
      if (evt.data?.ticker && String(evt.data.ticker) !== selectedTicker) continue;
      const stageLabel = EVENT_TO_STAGE[evt.type];
      if (!stageLabel) continue;
      const now = Date.now();

      setPipeStages((prev) => {
        const next = prev.map((s) => ({ ...s }));
        const idx = next.findIndex((s) => s.label === stageLabel);
        if (idx === -1) return prev;

        const prevTs = idx > 0
          ? pipeTimestamps.current[next[idx - 1].key] ?? pipeConnectTime.current
          : pipeConnectTime.current;
        const dur = ((now - prevTs) / 1000).toFixed(1);
        pipeTimestamps.current[next[idx].key] = now;

        const d = evt.data;
        let detail = "done";
        if (d) {
          const dir = d.direction ?? d.signal ?? "";
          const conf = d.confidence ?? d.score;
          if (conf != null) detail = `${String(dir)} ${Math.round(Number(conf))}`;
          else if (dir) detail = String(dir);
          if (evt.type === "risk_complete") detail = String(d.risk_level ?? d.level ?? "done");
        }

        next[idx] = { ...next[idx], status: "done", detail: `\u2713 ${detail}`, time: `${dur}s` };

        const nextPending = next.findIndex((s, si) => si > idx && s.status === "queue");
        if (nextPending !== -1) {
          next[nextPending] = { ...next[nextPending], status: "run" };
        }
        return next;
      });
    }
  }, [events, selectedTicker]);

  // ---- Filter & sort items ----
  const prevItemMap = useMemo(
    () => new Map(prevItems.map((it) => [it.ticker, it])),
    [prevItems],
  );

  const filteredItems = useMemo(() => {
    let pool = items;
    if (segment === "equity") {
      pool = items.filter((it) => equitySet.has(it.ticker));
    } else if (segment === "etf") {
      pool = items.filter((it) => etfSet.has(it.ticker));
    }
    const filtered = applyPresetFilters(pool, activePresets, prevItemMap, lastRefreshedAt ?? 0, 0, "");
    return [...filtered].sort((a, b) => {
      const va = sortValue(a, sortKey);
      const vb = sortValue(b, sortKey);
      if (typeof va === "number" && typeof vb === "number") return vb - va;
      if (typeof va === "string" && typeof vb === "string") return va.localeCompare(vb);
      return 0;
    });
  }, [items, segment, activePresets, prevItemMap, lastRefreshedAt, equitySet, etfSet, sortKey]);

  const presetCounts = useMemo(
    () => computePresetCounts(items, prevItemMap, lastRefreshedAt ?? 0),
    [items, prevItemMap, lastRefreshedAt],
  );

  // ---- Clamp selectedIndex when filtered list shrinks ----
  useEffect(() => {
    setSelectedIndex((i) => Math.min(i, Math.max(0, filteredItems.length - 1)));
  }, [filteredItems.length]);

  // ---- Selected item & full decision ----
  const selectedItem = filteredItems[selectedIndex] ?? null;

  useEffect(() => {
    if (selectedItem) {
      setTicker(selectedItem.ticker);
    }
  }, [selectedItem, setTicker]);

  // ---- Hydrate pipeline stages from cached signal data ----
  // When selecting a ticker that already has completed analysis (from cache or
  // a prior batch run), SSE events won't fire. Detect the all-queue state and
  // populate stages from the BatchSignalItem so the panel shows completed info.
  useEffect(() => {
    if (!selectedItem) return;
    setPipeStages((prev) => {
      const allQueue = prev.every((s) => s.status === "queue");
      if (!allQueue) return prev;
      if (!selectedItem.signal) return prev;

      const latMs = selectedItem.pipeline_latency_ms;
      const stageCount = prev.length;
      const avgPerStage = stageCount > 0 ? latMs / stageCount : 0;

      return prev.map((s) => {
        let detail = "\u2713 done";
        const time = avgPerStage > 0 ? `${(avgPerStage / 1000).toFixed(1)}s` : "";

        if (s.key === "materialize") {
          detail = "\u2713 cached";
        } else if (s.key === "thesis" && selectedItem.thesis_confidence != null) {
          detail = `\u2713 ${selectedItem.signal} ${Math.round(selectedItem.thesis_confidence)}`;
        } else if (s.key === "antithesis" && selectedItem.antithesis_confidence != null) {
          detail = `\u2713 ${Math.round(selectedItem.antithesis_confidence)}`;
        } else if (s.key === "base_rate") {
          detail = "\u2713 done";
        } else if (s.key === "synthesis" && selectedItem.conviction != null) {
          detail = `\u2713 ${selectedItem.signal} ${Math.round(selectedItem.conviction)}`;
        } else if (s.key === "har-rv") {
          detail = selectedItem.predicted_rv_1d_pct != null
            ? `\u2713 ${selectedItem.predicted_rv_1d_pct.toFixed(1)}%`
            : "\u2713 done";
        } else if (s.key === "risk") {
          detail = `\u2713 ${selectedItem.final_shares} shr`;
        }

        return { ...s, status: "done" as const, detail, time };
      });
    });
  }, [selectedItem]);

  // ---- Keyboard nav ----
  const handleSelectTicker = useCallback((idx: number) => {
    setSelectedIndex(idx);
  }, []);

  const handleOpenTicker = useCallback((t: string) => {
    setTicker(t);
    setActiveTab("analysis");
  }, [setTicker]);

  const handleTogglePreset = useCallback((key: string) => {
    const pk = key as PresetKey;
    setActivePresets((prev) => ({ ...prev, [pk]: !prev[pk] }));
  }, []);

  const handleTabSwitch = useCallback((tabIndex: number) => {
    if (tabIndex >= 1 && tabIndex <= DETAIL_TABS.length) {
      setActiveTab(DETAIL_TABS[tabIndex - 1].id);
    }
  }, []);

  useKeyboardNav({
    items: filteredItems,
    selectedIndex,
    onSelect: handleSelectTicker,
    onOpen: handleOpenTicker,
    onRefresh: fetchSignals,
    onTogglePreset: handleTogglePreset,
    onTabSwitch: handleTabSwitch,
  });

  // ---- Divergence dimensions ----
  const divDims = divData
    ? Object.entries(divData.dimensions).map(([name, d]) => ({
        name,
        value: d.value,
        confidence: d.confidence,
      }))
    : [];

  const divBias = divData ? divBiasTag(divData.composite_score) : null;

  // ---- Equities and ETFs split for separator rows ----
  const equityItems = useMemo(
    () => filteredItems.filter((it) => equitySet.has(it.ticker)),
    [filteredItems, equitySet],
  );
  const etfItems = useMemo(
    () => filteredItems.filter((it) => etfSet.has(it.ticker)),
    [filteredItems, etfSet],
  );

  // ---- Now ----
  const now = Date.now();

  // ================================================================
  // RENDER
  // ================================================================

  return (
    <>
      <div className="top-stripe" />

      <header className="topbar">
        {/* Row 1: brand, clock, budget, actions */}
        <div className="topbar-row1">
          <div className="logo-block">
            <div className="logo">FM</div>
            <div className="logo-text">
              <div className="name">FLAB MASA</div>
              <div className="sub">vol-arb &middot; v3.2</div>
            </div>
          </div>

          <div className={backendAlive ? "live-pill" : "live-pill offline"}>{backendAlive ? "\u2022 LIVE" : "\u2022 OFFLINE"}</div>

          <div className="clock">
            <span className="state">{clock.state}</span>
            <span className="sep">&vert;</span>
            <span>{clock.time}</span>
            <span className="sep">&vert;</span>
            <span className="dim">{clock.closeIn}</span>
          </div>

          <div className="budget-block" title="Daily Anthropic spend / cap">
            <span className="lbl">$</span>
            <span className={`val ${costs && costs.pct_of_daily_budget > 50 ? "amber" : ""}`}>
              {costs ? costs.total_usd.toFixed(2) : "\u2014"}
            </span>
            <span className="dim">/ {costs ? costs.budget_daily_usd : 300}</span>
            <div className="bar">
              <i style={{ width: `${costs ? Math.min(100, costs.pct_of_daily_budget) : 0}%` }} />
            </div>
            <span className="proj">
              proj {autoRefresh.isEnabled ? formatCountdown(autoRefresh.nextRefreshIn) : "off"}
            </span>
          </div>

          <div className="err-dock">ERR {errCount}</div>

          <button className="btn" onClick={fetchSignals}>
            <span>&loz;</span> Fast <span className="kbd">F</span>
          </button>
          <button className="btn deep" onClick={handleRunAll}>
            <span>&#9654;</span> Deep Debate <span className="kbd">⌘R</span>
          </button>
          <button
            className={`btn ${autoRefresh.isEnabled ? "go" : ""}`}
            onClick={autoRefresh.toggle}
            title={autoRefresh.isEnabled ? "Disable auto-refresh" : "Enable auto-refresh"}
          >
            Auto {autoRefresh.isEnabled ? formatCountdown(autoRefresh.nextRefreshIn) : "OFF"}
          </button>
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(Number(e.target.value))}
            className="interval-select"
            title="Auto-refresh interval"
            style={{ fontSize: "9px", padding: "2px 4px", background: "var(--bg2, #1a1a1a)", color: "inherit", border: "1px solid var(--border, #333)", borderRadius: "3px" }}
          >
            <option value={300000}>5 min</option>
            <option value={900000}>15 min</option>
            <option value={1800000}>30 min</option>
            <option value={3600000}>60 min</option>
          </select>
        </div>

        {/* Row 2: three live countdowns */}
        <div className="topbar-row2">
          <div className="countdown accent">
            <span className="ic">&loz;</span>
            <div>
              <div className="lbl">Universe Re-rank</div>
              <div>
                <span className="val">{universeCountdown}s</span>{" "}
                <span className="sub">&middot; next 1-min tick</span>
              </div>
            </div>
            <div className="pbar"><i className="u" style={{ width: `${((60 - universeCountdown) / 60) * 100}%` }} /></div>
          </div>
          <div className="countdown ok">
            <span className="ic">&bull;</span>
            <div>
              <div className="lbl">
                Agent Cycle &middot;{" "}
                {batchProgress
                  ? `${batchProgress.completed} / ${batchProgress.total} done`
                  : `${items.length} / ${allTickers.length} done`}
              </div>
              <div>
                <span className="val">{formatCountdown(autoRefresh.nextRefreshIn)}</span>
                <span className="sub"> / {formatCountdown(refreshInterval)} cycle</span>
              </div>
            </div>
            <div className="pbar">
              <i className="a" style={{
                width: batchProgress && batchProgress.total > 0
                  ? `${(batchProgress.completed / batchProgress.total) * 100}%`
                  : `${autoRefresh.nextRefreshIn > 0 ? ((refreshInterval - autoRefresh.nextRefreshIn) / refreshInterval) * 100 : 0}%`
              }} />
            </div>
          </div>
          <div className="countdown">
            <span className="ic">&diams;</span>
            <div>
              <div className="lbl">Next Trade Window</div>
              <div>
                <span className="val">{formatCountdown(tradeWindow)}</span>{" "}
                <span className="sub">&middot; 5-min bar</span>
              </div>
            </div>
            <div className="pbar"><i className="t" style={{ width: `${Math.max(0, (5 * 60 * 1000 - tradeWindow) / (5 * 60 * 1000) * 100)}%` }} /></div>
          </div>
          <div className="countdown" style={{ padding: "7px 16px", cursor: "pointer" }} onClick={() => setPaletteOpen(true)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPaletteOpen(true); } }}>
            <span className="ic">⌘K</span>
            <div>
              <div className="lbl">Palette</div>
              <div className="sub">/ticker &middot; 1-9 nav</div>
            </div>
          </div>
        </div>

        {/* Row 3: source health strip */}
        <div className="topbar-row3">
          <span className="hs-lbl">Sources</span>
          <div className="src-chips">
            {sourcesStatus.map((probe) => (
              <div key={probe.connector_name} className={`src-chip ${probe.status}`}>
                <span className="dot" />
                <span className="name">{probe.connector_name}</span>
                <span className="age">{formatSourceAge(probe)}</span>
              </div>
            ))}
            <div className={`src-chip ${costs && costs.pct_of_daily_budget > 80 ? "err" : costs && costs.pct_of_daily_budget > 50 ? "warn" : "ok"}`}>
              <span className="dot" />
              <span className="name">anthropic</span>
              <span className="age">{costs ? `$${costs.total_usd.toFixed(2)}` : "\u2014"}</span>
            </div>
          </div>
          <span className="dim" style={{ fontFamily: "var(--mono)", fontSize: "9px" }}>
            SSE &bull;{sseEventCount} events
          </span>
        </div>
      </header>

      {fetchError && (
        <div className="error-banner" style={{ background: "#1c0608", border: "1px solid #7f1d1d", color: "#fca5a5", padding: "6px 14px", fontSize: "11px", fontFamily: "var(--mono)" }}>
          &#9888; {fetchError}{" "}
          <button onClick={() => setFetchError(null)} style={{ marginLeft: 8, textDecoration: "underline", cursor: "pointer", background: "none", border: "none", color: "inherit", fontSize: "inherit", fontFamily: "inherit" }}>dismiss</button>
        </div>
      )}

      <div className="body">
        {/* ================ LEFT COLUMN ================ */}
        <div className="left">
          {/* Universe table header */}
          <div className="univ-head">
            <h2>
              Top-Vol Universe{" "}
              <span className="count">
                {allTickers.length} tickers &middot; {equityTickers.length} EQ + {etfTickers.length} ETF
              </span>
            </h2>
            <div className="seg">
              <button className={segment === "all" ? "on" : ""} onClick={() => setSegment("all")}>
                All {allTickers.length}
              </button>
              <button className={segment === "equity" ? "on" : ""} onClick={() => setSegment("equity")}>
                Equity
              </button>
              <button className={segment === "etf" ? "on" : ""} onClick={() => setSegment("etf")}>
                ETF
              </button>
            </div>
            <div className="rank-by">
              rank by{" "}
              <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
                <option value="predicted_rv_1d_pct">HAR-RV 1d pred &darr;</option>
                <option value="conviction">Conviction &darr;</option>
                <option value="expected_value_pct">EV% &darr;</option>
                <option value="disagreement_score">Disagreement &darr;</option>
                <option value="realized_vol_20d_pct">RV20 &darr;</option>
                <option value="options_impact">Options Impact &darr;</option>
              </select>
            </div>
          </div>

          {/* Preset row */}
          <div className="preset-row">
            <span className="dim" style={{ fontFamily: "var(--mono)", fontSize: "9px", textTransform: "uppercase", letterSpacing: ".5px" }}>
              presets
            </span>
            {PRESET_META.map((pm) => {
              const isOn = activePresets[pm.key];
              const colorCls = pm.key === "LONGS" ? "buy" : pm.key === "SHORTS" ? "sell" : "";
              return (
                <button
                  key={pm.key}
                  className={`preset ${isOn ? "on" : ""} ${isOn ? colorCls : ""}`}
                  onClick={() => handleTogglePreset(pm.key)}
                  aria-pressed={isOn}
                >
                  {pm.label} {presetCounts[pm.key] > 0 ? `(${presetCounts[pm.key]})` : ""}
                </button>
              );
            })}
          </div>

          {/* Signal table */}
          <div className="tbl-wrap">
            <table className="vol">
              <thead>
                <tr>
                  <th>#</th>
                  <th>TICK</th>
                  <th className="r" title="Last price (Databento real-time / yfinance fallback)">PX</th>
                  <th className="r" title="Daily price change % (Databento / yfinance)">&Delta;%</th>
                  <th className="r" title="Take Profit target">TP</th>
                  <th className="r" title="Stop Loss level">SL</th>
                  <th className="r">RV20</th>
                  <th className={`r ${sortKey === "predicted_rv_1d_pct" ? "sort" : ""}`}>PRED 1d</th>
                  <th className="r">&Delta;pred</th>
                  <th className="r" title="Options Impact score (0-100) — proxy for IV Rank">OPT</th>
                  <th className="c">SIG</th>
                  <th className="r">CONV</th>
                  <th className="r">EV%</th>
                  <th className="c">DGR</th>
                  <th className="c">FLIP</th>
                  <th className="r">FRESH</th>
                  <th className="c">&#9998;</th>
                </tr>
              </thead>
              <tbody>
                {/* Equity separator */}
                {(segment === "all" || segment === "equity") && equityItems.length > 0 && (
                  <tr>
                    <td colSpan={15} className="sep-row">
                      &#9662; EQUITY &middot; top {equityItems.length} by HAR-RV 1d predicted
                    </td>
                  </tr>
                )}
                {(segment === "all" || segment === "equity") &&
                  equityItems.map((item, i) => {
                    const globalIdx = filteredItems.indexOf(item);
                    return (
                      <SignalRow
                        key={item.ticker}
                        item={item}
                        index={i}
                        isSelected={globalIdx === selectedIndex}
                        prevItem={prevItemMap.get(item.ticker)}
                        fetchedAt={lastRefreshedAt ?? 0}
                        now={now}
                        onClick={() => {
                          handleSelectTicker(globalIdx);
                          handleOpenTicker(item.ticker);
                        }}
                      />
                    );
                  })}

                {/* ETF separator */}
                {(segment === "all" || segment === "etf") && etfItems.length > 0 && (
                  <tr>
                    <td colSpan={15} className="sep-row">
                      &#9662; ETF &middot; top {etfItems.length} by HAR-RV 1d predicted
                    </td>
                  </tr>
                )}
                {(segment === "all" || segment === "etf") &&
                  etfItems.map((item, i) => {
                    const globalIdx = filteredItems.indexOf(item);
                    return (
                      <SignalRow
                        key={item.ticker}
                        item={item}
                        index={i}
                        isSelected={globalIdx === selectedIndex}
                        prevItem={prevItemMap.get(item.ticker)}
                        fetchedAt={lastRefreshedAt ?? 0}
                        now={now}
                        onClick={() => {
                          handleSelectTicker(globalIdx);
                          handleOpenTicker(item.ticker);
                        }}
                      />
                    );
                  })}
              </tbody>
            </table>
          </div>

          {/* Tab bar */}
          <div className="tabbar">
            {DETAIL_TABS.map((tab) => (
              <button
                key={tab.id}
                className={`tab ${activeTab === tab.id ? "on" : ""}`}
                onClick={() => setActiveTab(tab.id)}
                aria-selected={activeTab === tab.id}
              >
                {tab.label} <span className="k">⌘{tab.shortcut}</span>
              </button>
            ))}
          </div>

          {/* Tab content: Inspector card */}
          <div className="tab-content">
            {activeTab === "analysis" && selectedItem && (
              <InspectorSection
                item={selectedItem}
                onRerun={handleInspectorRerun}
                onPin={handleInspectorPin}
                isPinned={pinnedTickers.has(selectedItem.ticker)}
                copyFeedback={copyFeedback}
                onCopy={handleInspectorCopy}
              />
            )}
            {activeTab === "analysis" && !selectedItem && (
              <div className="inspector">
                <p className="dim">Select a ticker to view the inspector.</p>
              </div>
            )}
            {activeTab === "chart" && <ChartTab />}
            {activeTab === "options" && <OptionsTab />}
            {activeTab === "holdings" && <AnalysisTab />}
            {activeTab === "backtest" && <BacktestTab />}
            {activeTab === "settings" && <SettingsTab />}
            {activeTab === "sources" && <DataSourcesTab />}
          </div>
        </div>

        {/* ================ RIGHT COLUMN ================ */}
        <div className="right">
          {/* DIVERGENCE panel */}
          <div className="right-sect div-panel" style={{ padding: "14px" }}>
            <h3>
              <span>Divergence &middot; {ticker}</span>
              {divBias && <span className={`tag ${divBias.cls}`}>{divBias.label}</span>}
            </h3>
            {divData && (
              <>
                <div className="div-comp">
                  <div className={`val ${divData.composite_score > 0.001 ? "bull" : divData.composite_score < -0.001 ? "bear" : "neutral"}`}>
                    {divData.composite_score > 0 ? "+" : ""}{divData.composite_score.toFixed(3)}
                  </div>
                  <div className="dim" style={{ fontFamily: "var(--mono)", fontSize: "9px" }}>
                    composite &middot; weighted 5-dim z-score
                  </div>
                </div>
                <div className="div-bars">
                  {divDims.map((d) => {
                    const segCls = divSegClass(d.value);
                    const left = d.value >= 0 ? 50 : 50 + d.value * 50;
                    const width = Math.abs(d.value) * 50;
                    return (
                      <div key={d.name} className="div-row">
                        <span className="dlbl">{d.name.replace(/_/g, " ")}</span>
                        <div className="dtrack">
                          <div className={`dseg ${segCls}`} style={{ left: `${left}%`, width: `${width}%` }} />
                        </div>
                        <span className={`dval ${d.value > 0 ? "bull" : d.value < 0 ? "bear" : "neutral"}`}>
                          {d.value > 0 ? "+" : ""}{d.value.toFixed(3)}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div className="div-weights">
                  <span>
                    weights:{" "}
                    {Object.entries(DIMENSION_WEIGHTS)
                      .map(([k, w]) => `${k.slice(0, 4)} ${w.toFixed(2)}`)
                      .join(" \u00B7 ")}
                  </span>
                </div>
              </>
            )}
            {!divData && !divError && <p className="dim">Loading...</p>}
            {divError && (
              <div
                style={{
                  color: "var(--sell)",
                  fontSize: "10px",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                }}
              >
                Failed to load divergence.
                <button
                  className="btn"
                  style={{ fontSize: "9px", padding: "2px 8px" }}
                  onClick={() => {
                    setDivError(false);
                    divRetryRef.current = 0;
                    fetchDivergence(ticker);
                  }}
                >
                  Retry
                </button>
              </div>
            )}
          </div>

          {/* AGENT PIPELINE */}
          <div className="right-sect">
            <h3>
              <span>Agent Pipeline &middot; {ticker}</span>
              <span className="dim" style={{ fontFamily: "var(--mono)", fontSize: "9px" }}>
                {selectedItem ? `${(selectedItem.pipeline_latency_ms / 1000).toFixed(1)}s` : "\u2014"}
                {selectedItem?.cost_usd ? ` \u00B7 $${selectedItem.cost_usd.toFixed(3)}` : ""}
              </span>
            </h3>
            <div className="pipe-status">
              {pipeStages.map((s) => (
                <div key={s.key} className="pipe-row">
                  <span className="plbl">{s.label}</span>
                  <span className={`pstate ${s.status}`}>{s.detail || (s.status === "run" ? "..." : "\u2022")}</span>
                  <span className="ptime">{s.time}</span>
                </div>
              ))}
            </div>
          </div>

          {/* NEWS FEED */}
          <div className="right-sect" style={{ flex: 1, overflow: "auto" }}>
            <h3>
              <span>News &middot; {selectedTicker || "UNIVERSE"}</span>
              <span className="dim" style={{ fontFamily: "var(--mono)", fontSize: "9px" }}>
                {news.length} items &middot; composite ranked
              </span>
            </h3>
            <div className="news-list">
              {newsLoading && <p className="dim" style={{ padding: "8px 0", fontSize: "10px" }}>Loading news...</p>}
              {!newsLoading && news.length === 0 && (
                <p className="dim" style={{ padding: "8px 0", fontSize: "10px" }}>No news available.</p>
              )}
              {news.map((item, i) => {
                const score = Math.round(item.impact_score * 100);
                const scoreClass = score >= 80 ? "" : score >= 60 ? "mid" : "low";
                const isBreaking = score >= 85;
                const relTime = formatRelativeTime(item.published_at);
                const dirTag = item.direction === "LONG" ? "up" : item.direction === "SHORT" ? "down" : "";
                const dirPillCls = item.direction === "LONG" ? "long" : item.direction === "SHORT" ? "short" : "neutral";
                const dirLabel = item.direction === "LONG" ? "\u25B2 LONG" : item.direction === "SHORT" ? "\u25BC SHORT" : "\u25CF NEUT";
                const confPct = Math.min(100, Math.abs(item.confidence) * 100);
                const confFillCls = item.confidence > 0 ? "pos" : item.confidence < 0 ? "neg" : "neu";
                const srcTier = newsSourceTier(item.source);
                const srcTierCls = srcTier <= 1 ? "t1" : srcTier <= 2 ? "t2" : "t3";
                const srcTierLabel = srcTier <= 1 ? "\u2605" : srcTier <= 2 ? "\u2606" : "";
                const newsExpandKey = `news-${i}`;
                const isExpanded = expandedNews === newsExpandKey;

                return (
                  <div key={`news-${i}-${item.url ?? item.title?.slice(0, 30)}`}>
                    <div
                      className={`news-row ${isBreaking ? "brk" : ""}`}
                      style={{ cursor: "pointer" }}
                      onClick={() => setExpandedNews(isExpanded ? null : newsExpandKey)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setExpandedNews(isExpanded ? null : newsExpandKey);
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      aria-expanded={isExpanded}
                      aria-label={`${item.title ?? "news item"} (press Enter to ${isExpanded ? "collapse" : "expand"})`}
                    >
                      <div className={`score ${scoreClass}`}>{score}</div>
                      <div>
                        <div className="hl">
                          {item.tags.includes("EARN") || item.tags.includes("FDA") ? (
                            <span className="hl-sym">{ticker}</span>
                          ) : null}
                          {item.title}
                        </div>
                        <div className="meta">
                          {/* Direction pill */}
                          <span className={`dir-pill ${dirPillCls}`}>{dirLabel}</span>
                          {/* Confidence bar */}
                          <span className="conf-bar">
                            <span className={`conf-fill ${confFillCls}`} style={{ width: `${confPct}%` }} />
                          </span>
                          <span>{item.confidence > 0 ? "+" : ""}{item.confidence.toFixed(2)}</span>
                          <span style={{ color: "var(--line2)" }}>&middot;</span>
                          {/* Source + credibility */}
                          <span className={`src-badge ${srcTierCls}`}>
                            {srcTierLabel}{srcTierLabel ? " " : ""}{item.source ?? "unknown"}
                          </span>
                          {/* Content tags */}
                          {item.tags.slice(0, 2).map((tag) => (
                            <span key={tag} className={`tag-inline ${tag === "FDA" ? "fda" : dirTag}`}>{tag}</span>
                          ))}
                        </div>
                      </div>
                      <div className="age">{relTime}</div>
                    </div>
                    {isExpanded && (
                      <div
                        style={{
                          padding: "6px 12px 10px 40px",
                          borderBottom: "1px solid var(--line1)",
                          background: "rgba(255,255,255,0.02)",
                          fontSize: "11px",
                          lineHeight: "1.5",
                        }}
                      >
                        {item.rationale && (
                          <p style={{ color: "#9ba7bb", margin: "0 0 6px" }}>
                            <span style={{ color: "#6e7681", fontWeight: 600, marginRight: 6 }}>Rationale:</span>
                            {item.rationale}
                          </p>
                        )}
                        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                          <span style={{ color: "#6e7681" }}>
                            Impact: <span style={{ color: "#d0d6e0", fontWeight: 600 }}>{score}%</span>
                          </span>
                          <span style={{ color: "#6e7681" }}>
                            Relevance: <span style={{ color: "#d0d6e0" }}>{(item.relevance * 100).toFixed(0)}%</span>
                          </span>
                          <span style={{ color: "#6e7681" }}>
                            Tags: {item.tags.map((t) => (
                              <span key={t} className={`tag-inline ${t === "FDA" ? "fda" : dirTag}`} style={{ marginLeft: 3 }}>{t}</span>
                            ))}
                          </span>
                          {item.url && (
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ color: "#828fff", textDecoration: "none", fontWeight: 500 }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              Read article &rarr;
                            </a>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Command Palette */}
      {paletteOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] bg-black/50" onClick={() => setPaletteOpen(false)}>
          <div className="w-[400px] rounded-lg border border-[#2a3246] bg-[#0d1218] p-3 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <input autoFocus value={paletteQuery} onChange={(e) => setPaletteQuery(e.target.value)}
              className="w-full rounded bg-[#10161f] border border-[#1c2230] px-3 py-2 text-sm text-[#e6edf3] font-mono placeholder:text-[#47536a]"
              placeholder="/ticker search..."
            />
            <div className="mt-2 max-h-[300px] overflow-y-auto">
              {allTickers.filter(t => t.toLowerCase().includes(paletteQuery.toLowerCase())).slice(0, 10).map(t => (
                <div key={t} onClick={() => { setTicker(t); setPaletteOpen(false); setPaletteQuery(""); }}
                  className="cursor-pointer rounded px-3 py-1.5 text-sm text-[#9ba7bb] font-mono hover:bg-[#10161f] hover:text-[#e6edf3]">
                  {t}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="footer">
        <span><b>1-20</b> nav ticker</span><span className="sep">&middot;</span>
        <span><b>j/k</b> row</span><span className="sep">&middot;</span>
        <span><b>Enter</b> open inspector</span><span className="sep">&middot;</span>
        <span><b>F</b> fast refresh</span><span className="sep">&middot;</span>
        <span><b>⌘R</b> deep debate</span><span className="sep">&middot;</span>
        <span><b>L/S</b> longs/shorts filter</span><span className="sep">&middot;</span>
        <span><b>⌘K</b> palette</span>
        <span className="sep">&middot;</span>
        <span className="ko">FLAB MASA &middot; connected</span>
        <span className="sep">&middot;</span>
        <span>agents parallelized &middot; sem=20 &middot; sonnet-4-5 synth &middot; Tier 0</span>
      </div>

      {activeBatchId && (
        <RunAllProgressModal
          batchId={activeBatchId}
          initialTickers={batchTickers}
          onClose={() => setActiveBatchId(null)}
          onComplete={(finalItems) => { setItems(finalItems); setActiveBatchId(null); }}
        />
      )}
    </>
  );
}

/* ================================================================== */
/*  SIGNAL TABLE ROW                                                   */
/* ================================================================== */

interface SignalRowProps {
  item: BatchSignalItem;
  index: number;
  isSelected: boolean;
  prevItem: BatchSignalItem | undefined;
  fetchedAt: number;
  now: number;
  onClick: () => void;
}

function SignalRow({ item, index, isSelected, prevItem, fetchedAt, now, onClick }: SignalRowProps) {
  const sig = signalClass(item.signal);
  // Freshness = wall-clock age since last refresh + pipeline latency proxy
  const wallAgeSec = fetchedAt > 0 ? (now - fetchedAt) / 1000 : 0;
  const freshAgeSec = wallAgeSec + freshAgeFromLatency(item.pipeline_latency_ms);
  const freshColor = freshChipColor(freshAgeSec);
  const freshLbl = formatFreshLabel(freshAgeSec);
  // Map freshColor to CSS class: green->hot, gray->warm, amber->stale, red->cold
  const freshCls = freshColor === "green" ? "hot" : freshColor === "gray" ? "warm" : freshColor === "amber" ? "stale" : "cold";

  // Flip detection via signalDiff utility
  const flip = computeFlipDelta(item, prevItem);
  const flipIcon = flip.isNew ? "eq" : flip.delta > 0 ? "up" : flip.delta < 0 ? "dn" : "eq";

  const predDelta = item.rv_forecast_delta_pct ?? null;
  const predDeltaClass = predDelta !== null && Math.abs(predDelta) < 1 ? "calm" : "";

  return (
    <tr
      className={`${isSelected ? "sel" : ""} ${flip.flipped ? "flipped" : ""}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
    >
      <td className="dim">{index + 1}</td>
      <td className="sym">{item.ticker}</td>
      <td className="num">{item.last_price != null ? item.last_price.toFixed(2) : "\u2014"}</td>
      <td className={`num ${item.change_pct != null ? (item.change_pct > 0 ? "buy" : item.change_pct < 0 ? "sell" : "") : "dim"}`}>
        {item.change_pct != null ? `${item.change_pct > 0 ? "+" : ""}${item.change_pct.toFixed(1)}` : "\u2014"}
      </td>
      <td className="num" style={{ color: "#3FB950" }} title={item.risk_reward != null ? `R:R ${item.risk_reward.toFixed(1)}` : undefined}>
        {item.tp_price != null ? item.tp_price.toFixed(2) : "\u2014"}
      </td>
      <td className="num" style={{ color: "#F85149" }}>
        {item.sl_price != null ? item.sl_price.toFixed(2) : "\u2014"}
      </td>
      <td className="num">
        {item.realized_vol_20d_pct != null ? `${Math.round(item.realized_vol_20d_pct)}%` : "\u2014"}
      </td>
      <td className={`num ${item.predicted_rv_1d_pct != null && item.predicted_rv_1d_pct > (item.realized_vol_20d_pct ?? 0) ? "amber" : ""}`}>
        {item.predicted_rv_1d_pct != null ? `${Math.round(item.predicted_rv_1d_pct)}%` : "\u2014"}
      </td>
      <td className="num">
        {predDelta !== null ? (
          <span className={`pred-delta ${predDeltaClass}`}>
            {predDelta > 0 ? "+" : ""}{predDelta.toFixed(1)}
          </span>
        ) : "\u2014"}
      </td>
      <td className="num">
        {item.options_impact != null ? item.options_impact : "\u2014"}
      </td>
      <td className="c">
        <span className={`sig-pill ${sig}`}>{item.signal}</span>
      </td>
      <td className="num">
        <div className={`conv-cell ${sig}`}>
          <div className="conv-bar">
            <i style={{ width: `${item.conviction}%` }} />
          </div>
          {item.conviction}
        </div>
      </td>
      <td className={`num ${item.expected_value_pct != null && item.expected_value_pct > 0 ? "buy" : item.expected_value_pct != null && item.expected_value_pct < 0 ? "sell" : "dim"}`}>
        {item.expected_value_pct != null
          ? `${item.expected_value_pct > 0 ? "+" : ""}${item.expected_value_pct.toFixed(1)}`
          : "\u2014"}
      </td>
      <td className={`num ${item.disagreement_score != null && item.disagreement_score > 0.5 ? "amber" : ""}`}>
        {item.disagreement_score != null ? item.disagreement_score.toFixed(2) : "\u2014"}
      </td>
      <td className={`flip-cell ${flipIcon}`}>
        {flip.isNew ? "NEW" : flip.arrow}
        {!flip.isNew && flip.delta !== 0 && (
          <span className="flip-delta">
            {flip.delta > 0 ? "+" : ""}{flip.delta}
          </span>
        )}
      </td>
      <td className="num">
        <span className={`fresh-chip ${freshCls}`}>{freshLbl}</span>
      </td>
      <td className="c">
        {item.cached && <span className="cached-badge">L1</span>}
        {item.used_mock && <span className="mock-badge" title="Signal generated with mock data — LLM was unavailable" style={{ color: "#f85149", backgroundColor: "rgba(218,54,51,0.2)", borderColor: "rgba(218,54,51,0.3)" }}>MOCK</span>}
      </td>
    </tr>
  );
}

/* ================================================================== */
/*  INSPECTOR SECTION                                                  */
/* ================================================================== */

interface InspectorSectionProps {
  item: BatchSignalItem;
  onRerun: (ticker: string) => void;
  onPin: (ticker: string) => void;
  isPinned: boolean;
  copyFeedback: string | null;
  onCopy: (item: BatchSignalItem) => void;
}

function InspectorSection({ item, onRerun, onPin, isPinned, copyFeedback, onCopy }: InspectorSectionProps) {
  const sig = signalClass(item.signal);

  return (
    <div className="inspector">
      {/* Head */}
      <div className="insp-head">
        <div className="insp-tk">{item.ticker}</div>
        <div className="insp-sep">&middot;</div>
        <div className="insp-meta">{item.rv_forecast_model_version ?? "agent-set-v1"}</div>
        <div className="insp-px">
          &mdash; <span className={`insp-chg ${sig}`}>&mdash;</span>
        </div>
      </div>

      {/* Verdict box */}
      <div className={`verdict-box ${sig}`}>
        <div className="actions">
          <button className="btn" style={{ padding: "4px 8px", fontSize: "10px" }} onClick={() => onRerun(item.ticker)} title="Re-fetch signal for this ticker">Rerun</button>
          <button className="btn" style={{ padding: "4px 8px", fontSize: "10px" }} onClick={() => onPin(item.ticker)} title={isPinned ? "Unpin ticker" : "Pin ticker to top"}>{isPinned ? "\u2605 Pinned" : "Pin"}</button>
          <button className="btn" style={{ padding: "4px 8px", fontSize: "10px" }} onClick={() => onCopy(item)} title="Copy verdict to clipboard">{copyFeedback ?? "Copy"}</button>
        </div>
        <div className="vlbl">VERDICT &middot; synthesis agent</div>
        <div className="vsig">{item.signal}</div>
        {item.used_mock && (
          <div className="mt-1 rounded border border-[#da3633]/30 bg-[#da3633]/10 px-2 py-1 text-[10px] text-[#f85149]">
            Warning: This signal was generated with mock data. LLM analysis was unavailable.
          </div>
        )}
        <div className="vstats">
          <span>conviction <b>{item.conviction}</b> / 100</span>
          {item.expected_value_pct != null && (
            <span>
              EV <b className={sig}>
                {item.expected_value_pct > 0 ? "+" : ""}{item.expected_value_pct.toFixed(1)}%
              </b>
            </span>
          )}
          {item.disagreement_score != null && (
            <>
              <span>agreement <b>{(1 - item.disagreement_score).toFixed(2)}</b></span>
              <span>disagreement score <b>{item.disagreement_score.toFixed(2)}</b></span>
            </>
          )}
        </div>
        <div className="vbar">
          <i style={{ width: `${item.conviction}%` }} />
        </div>
      </div>

      {/* Because block */}
      <div className="because">
        <b>Because:</b>{" "}
        {item.data_gaps.length > 0
          ? `Data gaps: ${item.data_gaps.join(", ")}`
          : "Run deep analysis for full reasoning"}
      </div>

      {/* Debate rollup (from BatchSignalItem fields) */}
      <div className="sect">
        <div className="sect-head">
          DEBATE ROLLUP (3 arguers + judge){" "}
          <span className="src">&middot; {item.models_used?.join(", ") ?? "sonnet-4-5"} &middot; {(item.pipeline_latency_ms / 1000).toFixed(1)}s</span>
        </div>
        <div className="debate-row">
          <div className="ag-card bull">
            <div className="ag-lbl">Thesis</div>
            <div className="ag-stance">{item.signal === "SHORT" ? "SHORT" : item.signal === "HOLD" ? "NEUT" : "BUY"}</div>
            <div className="ag-conf">
              conf <b>{item.thesis_confidence != null ? `${Math.round(item.thesis_confidence)}%` : "\u2014"}</b>
            </div>
            <div className="ag-bar">
              <i style={{ width: `${item.thesis_confidence ?? 0}%` }} />
            </div>
          </div>
          <div className="ag-card bear">
            <div className="ag-lbl">Antithesis</div>
            <div className="ag-stance">{item.signal === "BUY" ? "SHORT" : item.signal === "HOLD" ? "NEUT" : "BUY"}</div>
            <div className="ag-conf">
              conf <b>{item.antithesis_confidence != null ? `${Math.round(item.antithesis_confidence)}%` : "\u2014"}</b>
            </div>
            <div className="ag-bar">
              <i style={{ width: `${item.antithesis_confidence ?? 0}%` }} />
            </div>
          </div>
          <div className="ag-card base">
            <div className="ag-lbl">Base Rate</div>
            <div className="ag-stance">NEUT</div>
            <div className="ag-conf">P(up)=<b>&mdash;</b></div>
            <div className="ag-bar"><i style={{ width: "50%" }} /></div>
          </div>
          <div className="ag-card synth">
            <div className="ag-lbl">Synthesis &middot; judge</div>
            <div className="ag-stance">{item.signal} &middot; conv {item.conviction}</div>
            <div className="ag-bar">
              <i style={{ width: `${item.conviction}%` }} />
            </div>
          </div>
        </div>
      </div>

      {/* Volatility section (from batch item fields) */}
      {(item.realized_vol_20d_pct != null || item.predicted_rv_1d_pct != null) && (
        <div className="sect">
          <div className="sect-head">
            VOLATILITY &middot; predicted vs current{" "}
            <span className="src">&middot; {item.rv_forecast_model_version ?? "HAR-RV Ridge"} &middot; tier{item.tier}</span>
          </div>
          <div className="vol-kv">
            <div className="row">
              <span className="k">RV 20d (GK)</span>
              <span className="v">{item.realized_vol_20d_pct != null ? `${Math.round(item.realized_vol_20d_pct)}%` : "\u2014"}</span>
            </div>
            <div className="row">
              <span className="k">HAR-RV 1d forecast</span>
              <span className={`v ${item.rv_forecast_delta_pct != null && item.rv_forecast_delta_pct > 0 ? "amber" : ""}`}>
                {item.predicted_rv_1d_pct != null ? `${Math.round(item.predicted_rv_1d_pct)}%` : "\u2014"}
                {item.rv_forecast_delta_pct != null ? ` (${item.rv_forecast_delta_pct > 0 ? "+" : ""}${item.rv_forecast_delta_pct.toFixed(1)})` : ""}
              </span>
            </div>
            {item.predicted_rv_5d_pct != null && (
              <div className="row">
                <span className="k">HAR-RV 5d forecast</span>
                <span className="v amber">{Math.round(item.predicted_rv_5d_pct)}%</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
