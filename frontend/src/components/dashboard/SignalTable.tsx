"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getBatchSignals,
  getLatestScreener,
  startBatch,
  type BatchSignalItem,
} from "@/lib/api";
import {
  ALL_PRESET_KEYS,
  applyPresetFilters,
  computePresetCounts,
  INITIAL_PRESETS,
  matchesPreset as matchesPresetPure,
  PRESET_META,
  type PresetKey,
} from "@/lib/presetFilters";
import { sortValue, type SortKey } from "@/lib/signalSort";
import {
  computeFlipDelta,
  freshAgeFromLatency,
  freshChipColor,
  formatFreshLabel,
  type FreshColor,
} from "@/lib/signalDiff";
import { volColor } from "@/lib/volColor";
import { useTicker } from "@/hooks/useTicker";
import { useKeyboardNav } from "@/hooks/useKeyboardNav";
import { useUniverseRerank } from "@/hooks/useUniverseRerank";
import { useSignalsStore } from "@/stores/signalsStore";
import RunAllProgressModal from "./RunAllProgressModal";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

// ETFs surfaced in the top-bar market overview. Included in "Run All" so
// the table always reflects the broader market regime alongside the
// watchlist.
const TOP_BAR_ETFS: readonly string[] = ["SPY", "QQQ", "DIA", "IWM"] as const;

/** Well-known ETF tickers used to partition the signal table into
 *  EQUITY and ETF sections via divider rows. */
const KNOWN_ETF_SET: ReadonlySet<string> = new Set([
  "SPY", "QQQ", "DIA", "IWM", "XLF", "XLE", "XLK", "XLV", "XLI",
  "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC", "GLD", "SLV", "TLT",
  "HYG", "LQD", "EEM", "EFA", "VWO", "VEA", "AGG", "BND", "ARKK",
  "SOXL", "TQQQ", "SQQQ", "UVXY", "VXX",
]);

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface SignalTableProps {
  onSelectTicker: (ticker: string) => void;
  onTabSwitch?: (tabIndex: number) => void;
}

type SignalKind = BatchSignalItem["signal"];

type SortDir = "asc" | "desc";

type UniverseSegment = "all" | "equity" | "etf";

/* ------------------------------------------------------------------ */
/*  Color constants                                                    */
/* ------------------------------------------------------------------ */

const SIGNAL_COLORS: Record<SignalKind, string> = {
  BUY: "#6ee7b7",
  SHORT: "#fca5a5",
  HOLD: "#8b98ac",
};

const SIGNAL_BG: Record<SignalKind, string> = {
  BUY: "#052018",
  SHORT: "#1c0608",
  HOLD: "#1a1f28",
};

const SIGNAL_BORDER: Record<SignalKind, string> = {
  BUY: "#0a5d3f",
  SHORT: "#7f1d1d",
  HOLD: "#2a3246",
};

const FRESH_CHIP_HEX: Record<FreshColor, string> = {
  green: "#3FB950",
  gray: "#8B949E",
  amber: "#D29922",
  red: "#F85149",
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNullableNumber(
  value: number | null,
  digits: number,
  suffix = "",
): string {
  if (value === null || value === undefined) return "\u2014";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function SignalTable({ onSelectTicker, onTabSwitch }: SignalTableProps) {
  const { watchlist: defaultWatchlist } = useTicker();

  // --- Global store (source of truth for items & prevItems) ---
  const items = useSignalsStore((s) => s.items);
  const storeSetItems = useSignalsStore((s) => s.setItems);
  const prevItems = useSignalsStore((s) => s.prevItems);
  const snapshotForDiff = useSignalsStore((s) => s.snapshotForDiff);
  const autoRefreshState = useSignalsStore((s) => s.autoRefresh);
  const autoRefreshEnabled = autoRefreshState.autoRefreshEnabled;
  const nextRefreshIn = autoRefreshState.nextRefreshIn;
  const toggleAutoRefresh = autoRefreshState.toggleAutoRefresh ?? (() => {});
  const priceMap = useSignalsStore((s) => s.priceMap);

  // --- Universe rerank: top-20 equity + top-20 ETF tickers refreshed every 60s ---
  const {
    allTickers: universeTickers,
    equityTickers: universeEquity,
    etfTickers: universeEtf,
    loading: universeLoading,
  } = useUniverseRerank();

  // Effective watchlist: prefer universe tickers (40) over the hardcoded default (6).
  const effectiveWatchlist = useMemo(
    () => (universeTickers.length > 0 ? universeTickers : defaultWatchlist),
    [universeTickers, defaultWatchlist],
  );

  // Universe-aware ETF set: if universe data is available, use it for
  // accurate equity/ETF partitioning; otherwise fall back to the static set.
  const dynamicEtfSet = useMemo<ReadonlySet<string>>(() => {
    if (universeEtf.length > 0) {
      return new Set([...KNOWN_ETF_SET, ...universeEtf]);
    }
    return KNOWN_ETF_SET;
  }, [universeEtf]);

  // Segment filter: All | Equity | ETF
  const [segment, setSegment] = useState<UniverseSegment>("all");

  const [loading, setLoading] = useState<boolean>(true);
  const [runningAll, setRunningAll] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Preset filters
  const [presets, setPresets] = useState<Record<PresetKey, boolean>>(INITIAL_PRESETS);

  // Other filters (conviction slider + search kept separate)
  const [minConviction, setMinConviction] = useState(0);
  const [search, setSearch] = useState("");

  // Sort
  const [sortKey, setSortKey] = useState<SortKey>("conviction");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Selected row
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  // Run All async batch + progress modal
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [batchTickers, setBatchTickers] = useState<string[]>([]);

  // Local fetchedAt for "DATA_FRESH" preset (view-specific timing)
  const [fetchedAt, setFetchedAt] = useState<number>(Date.now());

  // Keyboard navigation
  const [kbIndex, setKbIndex] = useState<number>(-1);
  const rowRefs = useRef<Map<number, HTMLTableRowElement>>(new Map());

  /* ---- Fetch ---- */

  const fetchBatch = useCallback(async () => {
    if (effectiveWatchlist.length === 0) {
      storeSetItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const result = await getBatchSignals(effectiveWatchlist);
      snapshotForDiff();
      storeSetItems(result);
      setFetchedAt(Date.now());
      setError(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to load";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [effectiveWatchlist, storeSetItems, snapshotForDiff]);

  useEffect(() => {
    void fetchBatch();
  }, [fetchBatch]);

  /* ---- Run All (cache-bypassing batch over watchlist + ETFs + screener) ---- */

  const handleRunAll = useCallback(async () => {
    setRunningAll(true);
    setError(null);
    try {
      // Fetch latest screener tickers opportunistically. 404 or any other
      // failure is silent -- Run All must never block on an optional source.
      let screenerTickers: string[] = [];
      try {
        const screener = await getLatestScreener();
        screenerTickers = [
          ...screener.equities.map((t) => t.ticker),
          ...screener.etfs.map((t) => t.ticker),
        ];
      } catch {
        screenerTickers = [];
      }

      const combined = Array.from(
        new Set<string>([
          ...effectiveWatchlist,
          ...TOP_BAR_ETFS,
          ...screenerTickers,
        ]),
      );

      if (combined.length === 0) {
        setRunningAll(false);
        return;
      }

      // Snapshot current items so Flip column can detect changes during batch.
      snapshotForDiff();

      // Kick off an async batch and hand control to the progress modal.
      // The modal writes live ticker_done updates directly to the global
      // store so the table updates in real time.
      const { batch_id } = await startBatch(combined, true);
      setBatchTickers(combined);
      setActiveBatchId(batch_id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Run All failed";
      setError(message);
      setRunningAll(false);
    }
  }, [effectiveWatchlist, snapshotForDiff]);

  /* ---- Sort handler ---- */

  const handleSort = useCallback(
    (key: SortKey) => {
      if (sortKey === key) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("desc");
      }
    },
    [sortKey],
  );

  /* ---- Preset toggle ---- */

  const togglePreset = useCallback((key: PresetKey) => {
    setPresets((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  /* ---- Derived: previous-items lookup for FLIPPED detection ---- */

  const prevItemMap = useMemo(() => {
    const map = new Map<string, BatchSignalItem>();
    for (const item of prevItems) {
      map.set(item.ticker, item);
    }
    return map;
  }, [prevItems]);

  /* ---- Preset counts (computed over full items list) ---- */

  const presetCounts = useMemo(
    () => computePresetCounts(items, prevItemMap, fetchedAt),
    [items, prevItemMap, fetchedAt],
  );

  /* ---- Derived data ---- */

  const filtered = useMemo(
    () => applyPresetFilters(items, presets, prevItemMap, fetchedAt, minConviction, search),
    [items, presets, prevItemMap, fetchedAt, minConviction, search],
  );

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    const groupOrder: Record<SignalKind, number> = { BUY: 0, SHORT: 1, HOLD: 2 };

    arr.sort((a, b) => {
      const groupDiff = groupOrder[a.signal] - groupOrder[b.signal];
      if (groupDiff !== 0) return groupDiff;

      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      if (typeof av === "number" && typeof bv === "number") {
        return (av - bv) * dir;
      }
      if (typeof av === "string" && typeof bv === "string") {
        return av.localeCompare(bv) * dir;
      }
      return 0;
    });

    return arr;
  }, [filtered, sortKey, sortDir]);

  /** Partition sorted rows into equity and ETF sections for divider rows. */
  const { equityRows, etfRows } = useMemo(() => {
    const eqRows: typeof sorted = [];
    const etRows: typeof sorted = [];
    for (const item of sorted) {
      if (dynamicEtfSet.has(item.ticker)) {
        etRows.push(item);
      } else {
        eqRows.push(item);
      }
    }
    return { equityRows: eqRows, etfRows: etRows };
  }, [sorted, dynamicEtfSet]);

  /** Apply segment filter (All / Equity / ETF). */
  const segmentedEquityRows = segment === "etf" ? [] : equityRows;
  const segmentedEtfRows = segment === "equity" ? [] : etfRows;

  const summary = useMemo(() => {
    const buyCount = items.filter((s) => s.signal === "BUY").length;
    const shortCount = items.filter((s) => s.signal === "SHORT").length;
    const holdCount = items.filter((s) => s.signal === "HOLD").length;
    const avgConv =
      items.length > 0
        ? Math.round(items.reduce((sum, s) => sum + s.conviction, 0) / items.length)
        : 0;
    return { buyCount, shortCount, holdCount, avgConv };
  }, [items]);

  /* ---- Row click ---- */

  const handleRowClick = useCallback(
    (ticker: string) => {
      setSelectedTicker(ticker);
      onSelectTicker(ticker);
    },
    [onSelectTicker],
  );

  /* ---- Keyboard nav: scroll selected row into view ---- */

  const handleKbSelect = useCallback((index: number) => {
    setKbIndex(index);
    if (index >= 0 && index < sorted.length) {
      setSelectedTicker(sorted[index].ticker);
    } else {
      setSelectedTicker(null);
    }
    // Scroll into view on next frame so the DOM has updated
    requestAnimationFrame(() => {
      const row = rowRefs.current.get(index);
      if (row) {
        row.scrollIntoView({ block: "nearest" });
      }
    });
  }, [sorted]);

  const handleKbOpen = useCallback(
    (ticker: string) => {
      onSelectTicker(ticker);
    },
    [onSelectTicker],
  );

  const handleKbTabSwitch = useCallback(
    (tabIndex: number) => {
      onTabSwitch?.(tabIndex);
    },
    [onTabSwitch],
  );

  useKeyboardNav({
    items: sorted,
    selectedIndex: kbIndex,
    onSelect: handleKbSelect,
    onOpen: handleKbOpen,
    onRefresh: fetchBatch,
    onTogglePreset: togglePreset,
    onTabSwitch: handleKbTabSwitch,
  });

  /* ---- Render helpers ---- */

  const sortArrow = (key: SortKey) => {
    if (sortKey !== key) return null;
    return <span className="ml-1 text-[10px]">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>;
  };

  const thClass =
    "px-1 py-0 text-left text-[9px] font-semibold uppercase tracking-[0.5px] text-[#6e7a91] cursor-pointer select-none hover:text-[#E6EDF3] transition-colors whitespace-nowrap";

  /** Number of visible columns in the mockup layout. */
  const COL_COUNT = 15;

  /* ---- Row renderer (shared by equity & ETF sections) ---- */

  const renderSignalRow = (s: BatchSignalItem, idx: number, rowNum: number) => {
    const color = SIGNAL_COLORS[s.signal];
    const isSelected = selectedTicker === s.ticker;
    const isKbSelected = kbIndex === idx;
    const hasError = s.data_gaps.some((g) => g.startsWith("pipeline_error"));
    const flip = computeFlipDelta(s, prevItemMap.get(s.ticker));
    // Use real price timestamp when available, fall back to pipeline latency
    const priceTs = priceMap[s.ticker]?.ts;
    const freshAge = priceTs
      ? (Date.now() - new Date(priceTs).getTime()) / 1000
      : freshAgeFromLatency(s.pipeline_latency_ms);
    const fColor = freshChipColor(freshAge);
    const freshLabel = formatFreshLabel(freshAge);
    const freshHex = FRESH_CHIP_HEX[fColor];

    // IVR: use options_impact as a proxy until iv_rank lands on BatchSignalItem
    const ivrValue = s.options_impact ?? null;

    return (
      <tr
        key={s.ticker}
        ref={(el) => {
          if (el) {
            rowRefs.current.set(idx, el);
          } else {
            rowRefs.current.delete(idx);
          }
        }}
        onClick={() => {
          setKbIndex(idx);
          handleRowClick(s.ticker);
        }}
        className="cursor-pointer border-b border-[#1c2230]/50 transition-colors"
        style={{
          height: 20,
          backgroundColor: isSelected ? "#142030" : undefined,
          borderLeft: isSelected || isKbSelected ? "3px solid #58A6FF" : "3px solid transparent",
        }}
        onMouseEnter={(e) => {
          if (!isSelected) e.currentTarget.style.backgroundColor = "#0E1218";
        }}
        onMouseLeave={(e) => {
          if (!isSelected) e.currentTarget.style.backgroundColor = "";
        }}
        title={hasError ? s.data_gaps.join("; ") : undefined}
      >
        {/* # (row number) */}
        <td className="px-1 py-0 text-[10px] text-center text-[#484F58] font-mono" style={{ width: 20 }}>
          {rowNum}
        </td>

        {/* TICK */}
        <td className="px-1 py-0 text-[10px] font-mono font-semibold text-[#E6EDF3]" style={{ width: 52 }}>
          {s.ticker}
        </td>

        {/* PX (last price — priceMap > signal item > em-dash) */}
        {(() => {
          const px = priceMap[s.ticker]?.last ?? s.last_price;
          return (
            <td className="px-1 py-0 text-[10px] font-mono text-right text-[#d0d6e0]" style={{ width: 55 }}>
              {px != null ? px.toFixed(2) : "\u2014"}
            </td>
          );
        })()}

        {/* Δ% (daily change — priceMap > signal item > em-dash) */}
        {(() => {
          const chg = priceMap[s.ticker]?.change_pct ?? s.change_pct;
          return (
            <td
              className="px-1 py-0 text-[10px] font-mono text-right"
              style={{
                width: 42,
                color:
                  chg == null
                    ? "#484F58"
                    : chg > 0
                      ? "#3FB950"
                      : chg < 0
                        ? "#F85149"
                        : "#8B949E",
              }}
            >
              {chg != null
                ? `${chg > 0 ? "+" : ""}${chg.toFixed(1)}`
                : "\u2014"}
            </td>
          );
        })()}

        {/* TP (take profit) */}
        <td
          className="px-1 py-0 text-[10px] font-mono text-right"
          style={{ width: 55, color: "#3FB950" }}
          title={s.risk_reward != null ? `R:R ${s.risk_reward.toFixed(1)}` : undefined}
        >
          {s.tp_price != null ? s.tp_price.toFixed(2) : "\u2014"}
        </td>

        {/* SL (stop loss) */}
        <td
          className="px-1 py-0 text-[10px] font-mono text-right"
          style={{ width: 55, color: "#F85149" }}
        >
          {s.sl_price != null ? s.sl_price.toFixed(2) : "\u2014"}
        </td>

        {/* RV20 (realized vol 20d) */}
        <td
          className="px-1 py-0 text-[10px] font-mono"
          style={{ width: 36, color: volColor(s.realized_vol_20d_pct) }}
        >
          {s.realized_vol_20d_pct === null || s.realized_vol_20d_pct === undefined
            ? "\u2014"
            : `${s.realized_vol_20d_pct.toFixed(1)}`}
        </td>

        {/* PRED 1D (HAR-RV Ridge 1d forecast) */}
        <td
          className="px-1 py-0 text-[10px] font-mono"
          style={{ width: 48, color: volColor(s.predicted_rv_1d_pct) }}
        >
          {s.predicted_rv_1d_pct === null || s.predicted_rv_1d_pct === undefined
            ? "\u2014"
            : `${s.predicted_rv_1d_pct.toFixed(1)}`}
        </td>

        {/* \u0394PRED (rv_forecast_delta_pct) */}
        <td
          className="px-1 py-0 text-[10px] font-mono"
          style={{
            width: 40,
            color:
              s.rv_forecast_delta_pct === null || s.rv_forecast_delta_pct === undefined
                ? "#484F58"
                : s.rv_forecast_delta_pct > 0
                  ? "#F85149"
                  : s.rv_forecast_delta_pct < 0
                    ? "#3FB950"
                    : "#8B949E",
          }}
        >
          {s.rv_forecast_delta_pct === null || s.rv_forecast_delta_pct === undefined
            ? "\u2014"
            : `${s.rv_forecast_delta_pct > 0 ? "+" : ""}${s.rv_forecast_delta_pct.toFixed(1)}`}
        </td>

        {/* IVR (iv_rank proxy via options_impact) */}
        <td className="px-1 py-0 text-[10px] font-mono text-[#8B949E]" style={{ width: 28 }}>
          {ivrValue === null ? "\u2014" : ivrValue}
        </td>

        {/* SIG (signal badge) */}
        <td className="px-1 py-0 text-[10px]" style={{ width: 52 }}>
          <span
            className="inline-block rounded px-1 py-0 text-[9px] font-bold leading-tight"
            style={{
              backgroundColor: SIGNAL_BG[s.signal],
              color,
              border: `1px solid ${SIGNAL_BORDER[s.signal]}`,
            }}
          >
            {s.signal}
          </span>
        </td>

        {/* CONV (conviction bar + number) */}
        <td className="px-1 py-0 text-[10px]" style={{ width: 42 }}>
          <div className="flex items-center gap-0.5">
            <div className="h-1 w-6 overflow-hidden rounded-full bg-[#1c2230]">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, Math.max(0, s.conviction))}%`,
                  backgroundColor: color,
                  opacity: 0.4 + (s.conviction / 100) * 0.6,
                }}
              />
            </div>
            <span className="text-[10px] text-[#8B949E]">
              {s.conviction}
            </span>
          </div>
        </td>

        {/* EV% */}
        <td
          className="px-1 py-0 text-[10px] font-mono"
          style={{
            width: 40,
            color:
              s.expected_value_pct === null
                ? "#484F58"
                : s.expected_value_pct >= 0
                  ? "#3FB950"
                  : "#F85149",
          }}
        >
          {formatNullableNumber(s.expected_value_pct, 1, "%")}
        </td>

        {/* DGR (disagreement) */}
        <td className="px-1 py-0 text-[10px] font-mono text-[#8B949E]" style={{ width: 36 }}>
          {s.disagreement_score === null
            ? "\u2014"
            : s.disagreement_score.toFixed(2)}
        </td>

        {/* FLIP -- conviction delta vs previous cycle */}
        <td className="px-1 py-0 text-[10px] text-center whitespace-nowrap" style={{ width: 42 }}>
          {flip.isNew ? (
            <span className="text-[9px] font-bold text-[#58A6FF]">new</span>
          ) : flip.flipped ? (
            <span className="text-[9px] font-bold text-[#F85149]">
              {flip.arrow} FLIP
            </span>
          ) : flip.delta === 0 ? (
            <span className="text-[9px] text-[#484F58]">{flip.arrow}</span>
          ) : (
            <span
              className="text-[9px] font-medium"
              style={{
                color: flip.delta > 0 ? "#3FB950" : "#F85149",
              }}
            >
              {flip.arrow} {flip.delta > 0 ? "+" : ""}{flip.delta}
            </span>
          )}
        </td>

        {/* FRESH -- per-row data freshness chip */}
        <td className="px-1 py-0 text-[10px] text-center" style={{ width: 38 }}>
          <span
            className="inline-block rounded px-1 py-0 text-[8px] font-bold leading-tight"
            style={{
              backgroundColor: freshHex + "22",
              color: freshHex,
              border: `1px solid ${freshHex}44`,
            }}
          >
            {freshLabel}
          </span>
        </td>

        {/* \u270E -- status badges (mock / L1 / streaming dot) */}
        <td className="px-1 py-0 text-[10px] text-center" style={{ width: 28 }}>
          {s.used_mock ? (
            <span
              className="rounded px-0.5 py-0 text-[8px] font-bold leading-none text-[#f85149] bg-[#da3633]/20 border border-[#da3633]/30"
              title="Signal generated with mock data — LLM was unavailable"
            >
              MOCK
            </span>
          ) : s.cached ? (
            <span className="rounded px-0.5 py-0 text-[7px] font-bold leading-none text-[#8B949E] bg-[#8B949E]/15 border border-[#8B949E]/30">
              L1
            </span>
          ) : (
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#3FB950]" title="live" />
          )}
        </td>
      </tr>
    );
  };

  /* ---- Loading / Error states ---- */

  if (loading && items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-[#8B949E] text-sm">
        Running v3 pipeline for {effectiveWatchlist.length} tickers...
      </div>
    );
  }

  if (error && items.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm text-[#F85149]">{error}</p>
        <button
          onClick={() => { void fetchBatch(); }}
          className="rounded border border-[#1c2230] bg-[#161B22] px-3 py-1 text-xs text-[#E6EDF3] hover:bg-[#1C2128]"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ---- Summary bar ---- */}
      <div className="flex items-center gap-3 border-b border-[#1c2230] bg-[#0D1117] px-2 py-1 text-[10px]">
        <span>
          <span style={{ color: SIGNAL_COLORS.BUY }}>BUY: {summary.buyCount}</span>
          {" | "}
          <span style={{ color: SIGNAL_COLORS.SHORT }}>SHORT: {summary.shortCount}</span>
          {" | "}
          <span style={{ color: SIGNAL_COLORS.HOLD }}>HOLD: {summary.holdCount}</span>
          {" | "}
          <span className="text-[#8B949E]">Avg Conv: {summary.avgConv}</span>
        </span>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => { void fetchBatch(); }}
            disabled={loading || runningAll}
            className="rounded border border-[#1c2230] bg-[#161B22] px-2 py-0.5 text-[10px] font-medium text-[#E6EDF3] hover:bg-[#1C2128] disabled:opacity-40"
          >
            {loading ? "Running..." : "Refresh"}
          </button>
          <button
            onClick={() => { void handleRunAll(); }}
            disabled={loading || runningAll}
            title="Run a fresh pipeline for watchlist + top-bar ETFs + latest screener (bypasses cache)"
            className="rounded border border-[#58A6FF]/60 bg-[#161B22] px-2 py-0.5 text-[10px] font-semibold text-[#58A6FF] hover:bg-[#1C2128] disabled:opacity-40"
          >
            {runningAll ? "Running\u2026" : "Run All"}
          </button>

          {/* Auto-refresh toggle + countdown */}
          <button
            onClick={toggleAutoRefresh}
            title={autoRefreshEnabled ? "Disable auto-refresh" : "Enable auto-refresh (30m cycle)"}
            className={`rounded border px-2 py-0.5 text-[10px] font-medium transition-colors ${
              autoRefreshEnabled
                ? "border-[#3FB950]/60 text-[#3FB950] bg-[#161B22] hover:bg-[#1C2128]"
                : "border-[#1c2230] text-[#484F58] bg-[#161B22] hover:bg-[#1C2128]"
            }`}
          >
            {autoRefreshEnabled
              ? `Auto ${Math.floor(nextRefreshIn / 60_000)}:${String(Math.floor((nextRefreshIn % 60_000) / 1000)).padStart(2, "0")}`
              : "Auto Off"}
          </button>
        </div>
      </div>

      {/* ---- Universe header row ---- */}
      <div
        className="flex items-center gap-3 border-b border-[#1c2230] bg-[#10161f] px-2 py-1 text-[10px]"
        data-testid="universe-header"
      >
        <span className="font-mono text-[#6e7a91]">
          Top-Vol Universe{" "}
          <span className="text-[#8B949E]">{"\u00B7"}</span>{" "}
          <span className="text-[#C9D1D9]">{universeTickers.length > 0 ? universeTickers.length : "\u2014"}</span>{" "}
          tickers{" "}
          <span className="text-[#8B949E]">{"\u00B7"}</span>{" "}
          <span className="text-[#C9D1D9]">{universeEquity.length}</span> EQ +{" "}
          <span className="text-[#C9D1D9]">{universeEtf.length}</span> ETF
          {universeLoading && (
            <span className="ml-1 text-[#484F58]">(loading...)</span>
          )}
        </span>

        {/* Segment buttons */}
        <div className="ml-2 flex items-center gap-1">
          {(
            [
              { key: "all" as const, label: `All ${universeTickers.length || effectiveWatchlist.length}` },
              { key: "equity" as const, label: "Equity" },
              { key: "etf" as const, label: "ETF" },
            ] as const
          ).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setSegment(key)}
              className="rounded px-2 py-0.5 text-[10px] font-semibold transition-colors"
              style={{
                backgroundColor: segment === key ? "#58A6FF22" : "transparent",
                color: segment === key ? "#58A6FF" : "#484F58",
                border: `1px solid ${segment === key ? "#58A6FF44" : "#1c2230"}`,
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Rank-by dropdown */}
        <div className="ml-auto flex items-center gap-1">
          <span className="text-[#484F58]">rank by</span>
          <select
            className="rounded border border-[#1c2230] bg-[#161B22] px-1.5 py-0.5 text-[10px] font-mono text-[#C9D1D9] outline-none focus:border-[#58A6FF]"
            defaultValue="predicted_rv_1d"
          >
            <option value="predicted_rv_1d">HAR-RV 1d pred {"\u2193"}</option>
          </select>
        </div>
      </div>

      {/* ---- Preset pill row ---- */}
      <div
        className="flex flex-wrap items-center gap-1 border-b border-[#1c2230] bg-[#0D1117] px-2 py-1"
        data-testid="preset-row"
      >
        {PRESET_META.map(({ key, label }) => {
          const active = presets[key];
          const styles: Record<string, { active: string; inactive: string }> = {
            LONGS:          { active: "border-[#0a5d3f] bg-[#052018] text-[#6ee7b7]", inactive: "border-[#2a3246] bg-transparent text-[#6e7a91]" },
            SHORTS:         { active: "border-[#7f1d1d] bg-[#1c0608] text-[#fca5a5]", inactive: "border-[#2a3246] bg-transparent text-[#6e7a91]" },
            HIGH_CONV:      { active: "border-[#1e3a5f] bg-[#051a2e] text-[#7cc5ff]", inactive: "border-[#2a3246] bg-transparent text-[#6e7a91]" },
            HOLD:           { active: "border-[#3a3a3a] bg-[#1a1a1a] text-[#8B949E]", inactive: "border-[#2a3246] bg-transparent text-[#6e7a91]" },
            FLIPPED:        { active: "border-[#5c3d0e] bg-[#1c1305] text-[#fbbf24]", inactive: "border-[#2a3246] bg-transparent text-[#6e7a91]" },
            AGENT_DISAGREE: { active: "border-[#4c2889] bg-[#170b2e] text-[#d8b4fe]", inactive: "border-[#2a3246] bg-transparent text-[#6e7a91]" },
            DATA_FRESH:     { active: "border-[#0a5d3f] bg-[#052018] text-[#39D353]", inactive: "border-[#2a3246] bg-transparent text-[#6e7a91]" },
          };
          const s = styles[key] ?? styles.HOLD!;
          return (
            <button
              key={key}
              data-testid={`preset-${key}`}
              onClick={() => togglePreset(key)}
              className={`rounded-full px-2.5 py-0.5 text-[10px] font-mono border transition-colors ${active ? s.active : s.inactive}`}
            >
              {label} ({presetCounts[key]})
            </button>
          );
        })}
      </div>

      {/* ---- Filter bar (conviction + search) ---- */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[#1c2230] bg-[#0D1117] px-2 py-1">
        <div className="flex items-center gap-1 text-[10px] text-[#8B949E]">
          <span>Conv &ge;</span>
          <input
            type="range"
            min={0}
            max={100}
            value={minConviction}
            onChange={(e) => setMinConviction(Number(e.target.value))}
            className="h-1 w-16 accent-[#58A6FF]"
          />
          <span className="w-5 text-right">{minConviction}</span>
        </div>

        <input
          type="text"
          placeholder="Search ticker..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="ml-auto rounded border border-[#1c2230] bg-[#161B22] px-2 py-0.5 text-[11px] text-[#E6EDF3] placeholder-[#484F58] outline-none focus:border-[#58A6FF]"
        />
      </div>

      {/* ---- Table ---- */}
      <div className="flex-1 overflow-auto">
        <table className="w-full min-w-max border-collapse text-[10px]">
          <thead className="sticky top-0 z-10 bg-[#0D1117]">
            <tr className="border-b border-[#1c2230]">
              <th className={thClass} style={{ width: 20 }}>#</th>
              <th className={thClass} style={{ width: 52 }} onClick={() => handleSort("ticker")}>
                Tick{sortArrow("ticker")}
              </th>
              <th className={thClass} style={{ width: 55 }}>PX</th>
              <th className={thClass} style={{ width: 42 }}>{"\u0394"}%</th>
              <th className={thClass} style={{ width: 55 }} title="Take Profit target">TP</th>
              <th className={thClass} style={{ width: 55 }} title="Stop Loss level">SL</th>
              <th className={thClass} style={{ width: 36 }} onClick={() => handleSort("realized_vol_20d_pct")}>
                RV20{sortArrow("realized_vol_20d_pct")}
              </th>
              <th className={thClass} style={{ width: 48 }} onClick={() => handleSort("predicted_rv_1d_pct")}>
                Pred 1D{sortArrow("predicted_rv_1d_pct")}
              </th>
              <th className={thClass} style={{ width: 40 }} onClick={() => handleSort("rv_forecast_delta_pct")}>
                {"\u0394"}Pred{sortArrow("rv_forecast_delta_pct")}
              </th>
              <th className={thClass} style={{ width: 28 }} onClick={() => handleSort("options_impact")}>
                IVR{sortArrow("options_impact")}
              </th>
              <th className={thClass} style={{ width: 52 }} onClick={() => handleSort("signal")}>
                Sig{sortArrow("signal")}
              </th>
              <th className={thClass} style={{ width: 42 }} onClick={() => handleSort("conviction")}>
                Conv{sortArrow("conviction")}
              </th>
              <th className={thClass} style={{ width: 40 }} onClick={() => handleSort("expected_value_pct")}>
                EV%{sortArrow("expected_value_pct")}
              </th>
              <th className={thClass} style={{ width: 36 }} onClick={() => handleSort("disagreement_score")}>
                DGR{sortArrow("disagreement_score")}
              </th>
              <th className={thClass} style={{ width: 42 }}>Flip</th>
              <th className={thClass} style={{ width: 38 }}>Fresh</th>
              <th className={thClass} style={{ width: 28 }}>{"\u270E"}</th>
            </tr>
          </thead>
          <tbody>
            {/* Section divider: EQUITY */}
            {segmentedEquityRows.length > 0 && (
              <tr key="__divider-equity">
                <td colSpan={COL_COUNT} className="bg-[#10161f] text-[#6e7a91] text-[9px] uppercase tracking-wider font-semibold px-3 py-1 border-y border-[#1c2230]">
                  {"\u25BE"} EQUITY {"\u00B7"} top {segmentedEquityRows.length} by HAR-RV 1d predicted
                </td>
              </tr>
            )}

            {segmentedEquityRows.map((s, i) => {
              const idx = sorted.indexOf(s);
              return renderSignalRow(s, idx, i + 1);
            })}

            {/* Section divider: ETF */}
            {segmentedEtfRows.length > 0 && (
              <tr key="__divider-etf">
                <td colSpan={COL_COUNT} className="bg-[#10161f] text-[#6e7a91] text-[9px] uppercase tracking-wider font-semibold px-3 py-1 border-y border-[#1c2230]">
                  {"\u25BE"} ETF {"\u00B7"} market regime
                </td>
              </tr>
            )}

            {segmentedEtfRows.map((s, i) => {
              const idx = sorted.indexOf(s);
              return renderSignalRow(s, idx, segmentedEquityRows.length + i + 1);
            })}

            {sorted.length === 0 && !loading && (
              <tr>
                <td colSpan={COL_COUNT} className="py-8 text-center text-sm text-[#484F58]">
                  No signals match your filters
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* ---- Run All progress modal ---- */}
      {activeBatchId && (
        <RunAllProgressModal
          batchId={activeBatchId}
          initialTickers={batchTickers}
          onClose={() => {
            setActiveBatchId(null);
            setRunningAll(false);
          }}
          onComplete={(finalItems) => {
            storeSetItems(finalItems);
            setRunningAll(false);
            // Leave modal open so the user can review per-ticker status;
            // they dismiss via the close button / backdrop / Escape key.
          }}
        />
      )}
    </div>
  );
}
