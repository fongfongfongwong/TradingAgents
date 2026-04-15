import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { BatchSignalItem } from "@/lib/api";
import {
  matchesPreset,
  computePresetCounts,
  applyPresetFilters,
  INITIAL_PRESETS,
  type PresetKey,
} from "@/lib/presetFilters";

/* ------------------------------------------------------------------ */
/*  Shared fixtures                                                    */
/* ------------------------------------------------------------------ */

const base: BatchSignalItem = {
  ticker: "AAPL",
  signal: "BUY",
  conviction: 80,
  tier: 1,
  pipeline_latency_ms: 1200,
  cost_usd: 0.42,
  cached: false,
  data_gaps: [],
  expected_value_pct: 3.5,
  thesis_confidence: 72,
  antithesis_confidence: 45,
  disagreement_score: 0.6,
  final_shares: 3,
  options_direction: "BULL",
  options_impact: 0.8,
  realized_vol_20d_pct: 22.5,
  atr_pct_of_price: 1.1,
  predicted_rv_1d_pct: 21.4,
  predicted_rv_5d_pct: 22.8,
  rv_forecast_delta_pct: -1.1,
  rv_forecast_model_version: "har_rv_ridge_2026-04-05",
};

function makeItem(overrides: Partial<BatchSignalItem>): BatchSignalItem {
  return { ...base, ...overrides };
}

const items: BatchSignalItem[] = [
  makeItem({ ticker: "AAPL", signal: "BUY", conviction: 80, disagreement_score: 0.6 }),
  makeItem({ ticker: "TSLA", signal: "SHORT", conviction: 90, disagreement_score: 0.3 }),
  makeItem({ ticker: "MSFT", signal: "HOLD", conviction: 50, disagreement_score: 0.1 }),
  makeItem({ ticker: "GOOG", signal: "BUY", conviction: 70, disagreement_score: 0.8 }),
  makeItem({ ticker: "AMZN", signal: "BUY", conviction: 95, disagreement_score: 0.2 }),
];

const emptyPrevMap = new Map<string, BatchSignalItem>();
const freshTimestamp = Date.now(); // just fetched

/* ------------------------------------------------------------------ */
/*  1. LONGS preset filters to BUY-only items                         */
/* ------------------------------------------------------------------ */

describe("LONGS preset", () => {
  it("matches only items with signal=BUY", () => {
    const buys = items.filter((i) => matchesPreset(i, "LONGS", emptyPrevMap, freshTimestamp));
    expect(buys).toHaveLength(3);
    expect(buys.every((i) => i.signal === "BUY")).toBe(true);
  });

  it("does not match SHORT or HOLD", () => {
    const short = makeItem({ signal: "SHORT" });
    const hold = makeItem({ signal: "HOLD" });
    expect(matchesPreset(short, "LONGS", emptyPrevMap, freshTimestamp)).toBe(false);
    expect(matchesPreset(hold, "LONGS", emptyPrevMap, freshTimestamp)).toBe(false);
  });
});

/* ------------------------------------------------------------------ */
/*  2. HIGH CONV >=75 filters correctly                                */
/* ------------------------------------------------------------------ */

describe("HIGH_CONV preset", () => {
  it("matches items with conviction >= 75", () => {
    const highConv = items.filter((i) =>
      matchesPreset(i, "HIGH_CONV", emptyPrevMap, freshTimestamp),
    );
    expect(highConv).toHaveLength(3); // AAPL(80), TSLA(90), AMZN(95)
    expect(highConv.every((i) => i.conviction >= 75)).toBe(true);
  });

  it("excludes items with conviction < 75", () => {
    const low = makeItem({ conviction: 74 });
    expect(matchesPreset(low, "HIGH_CONV", emptyPrevMap, freshTimestamp)).toBe(false);
  });

  it("includes items with conviction exactly 75", () => {
    const exact = makeItem({ conviction: 75 });
    expect(matchesPreset(exact, "HIGH_CONV", emptyPrevMap, freshTimestamp)).toBe(true);
  });
});

/* ------------------------------------------------------------------ */
/*  3. Multiple presets AND together (LONGS + HIGH_CONV)               */
/* ------------------------------------------------------------------ */

describe("multiple presets AND logic", () => {
  it("LONGS + HIGH_CONV returns only BUY items with conviction >= 75", () => {
    const activePresets: Record<PresetKey, boolean> = {
      ...INITIAL_PRESETS,
      LONGS: true,
      HIGH_CONV: true,
    };

    const result = applyPresetFilters(items, activePresets, emptyPrevMap, freshTimestamp, 0, "");
    // AAPL(BUY,80), AMZN(BUY,95) — GOOG(BUY,70) excluded by HIGH_CONV, TSLA(SHORT,90) excluded by LONGS
    expect(result).toHaveLength(2);
    expect(result.every((i) => i.signal === "BUY" && i.conviction >= 75)).toBe(true);
  });

  it("SHORTS + AGENT_DISAGREE returns only SHORT items with disagreement > 0.5", () => {
    const activePresets: Record<PresetKey, boolean> = {
      ...INITIAL_PRESETS,
      SHORTS: true,
      AGENT_DISAGREE: true,
    };

    const result = applyPresetFilters(items, activePresets, emptyPrevMap, freshTimestamp, 0, "");
    // TSLA is SHORT but disagreement_score=0.3, so excluded
    expect(result).toHaveLength(0);
  });
});

/* ------------------------------------------------------------------ */
/*  4. FLIPPED preset uses prevItems to detect changes                 */
/* ------------------------------------------------------------------ */

describe("FLIPPED preset", () => {
  it("detects signal change from previous cycle", () => {
    const prevMap = new Map<string, BatchSignalItem>([
      ["AAPL", makeItem({ ticker: "AAPL", signal: "HOLD", conviction: 80 })],
      ["TSLA", makeItem({ ticker: "TSLA", signal: "SHORT", conviction: 90 })],
    ]);

    // AAPL flipped from HOLD->BUY
    expect(matchesPreset(items[0], "FLIPPED", prevMap, freshTimestamp)).toBe(true);
    // TSLA same signal and conviction
    expect(matchesPreset(items[1], "FLIPPED", prevMap, freshTimestamp)).toBe(false);
  });

  it("detects conviction change even when signal is the same", () => {
    const prevMap = new Map<string, BatchSignalItem>([
      ["AAPL", makeItem({ ticker: "AAPL", signal: "BUY", conviction: 60 })],
    ]);

    // AAPL same signal but conviction changed 60->80
    expect(matchesPreset(items[0], "FLIPPED", prevMap, freshTimestamp)).toBe(true);
  });

  it("returns false when ticker has no previous entry", () => {
    expect(matchesPreset(items[0], "FLIPPED", emptyPrevMap, freshTimestamp)).toBe(false);
  });
});

/* ------------------------------------------------------------------ */
/*  5. Pill counts update when items change                            */
/* ------------------------------------------------------------------ */

describe("computePresetCounts", () => {
  it("returns correct counts for all presets", () => {
    const counts = computePresetCounts(items, emptyPrevMap, freshTimestamp);

    expect(counts.LONGS).toBe(3);      // AAPL, GOOG, AMZN
    expect(counts.SHORTS).toBe(1);     // TSLA
    expect(counts.HOLD).toBe(1);       // MSFT
    expect(counts.HIGH_CONV).toBe(3);  // AAPL(80), TSLA(90), AMZN(95)
    expect(counts.FLIPPED).toBe(0);    // no prev items
    expect(counts.AGENT_DISAGREE).toBe(2); // AAPL(0.6), GOOG(0.8)
    expect(counts.DATA_FRESH).toBe(5); // all fresh (just fetched)
  });

  it("updates counts when items list changes", () => {
    const fewerItems = items.slice(0, 2); // AAPL(BUY), TSLA(SHORT)
    const counts = computePresetCounts(fewerItems, emptyPrevMap, freshTimestamp);

    expect(counts.LONGS).toBe(1);
    expect(counts.SHORTS).toBe(1);
    expect(counts.HOLD).toBe(0);
  });

  it("reflects FLIPPED count when prevItems are provided", () => {
    const prevMap = new Map<string, BatchSignalItem>([
      ["AAPL", makeItem({ ticker: "AAPL", signal: "SHORT", conviction: 80 })],
      ["GOOG", makeItem({ ticker: "GOOG", signal: "HOLD", conviction: 70 })],
    ]);

    const counts = computePresetCounts(items, prevMap, freshTimestamp);
    expect(counts.FLIPPED).toBe(2); // AAPL and GOOG flipped
  });
});

/* ------------------------------------------------------------------ */
/*  6. Toggling a preset off removes the filter                        */
/* ------------------------------------------------------------------ */

describe("toggling preset off removes filter", () => {
  it("with no presets active, all items pass (only conviction slider + search apply)", () => {
    const result = applyPresetFilters(items, INITIAL_PRESETS, emptyPrevMap, freshTimestamp, 0, "");
    expect(result).toHaveLength(5);
  });

  it("activating LONGS then deactivating returns to full list", () => {
    const withLongs: Record<PresetKey, boolean> = { ...INITIAL_PRESETS, LONGS: true };
    const longsOnly = applyPresetFilters(items, withLongs, emptyPrevMap, freshTimestamp, 0, "");
    expect(longsOnly).toHaveLength(3);

    // Toggle off
    const withoutLongs: Record<PresetKey, boolean> = { ...INITIAL_PRESETS, LONGS: false };
    const all = applyPresetFilters(items, withoutLongs, emptyPrevMap, freshTimestamp, 0, "");
    expect(all).toHaveLength(5);
  });

  it("conviction slider still applies even with no presets active", () => {
    const result = applyPresetFilters(items, INITIAL_PRESETS, emptyPrevMap, freshTimestamp, 75, "");
    expect(result).toHaveLength(3); // AAPL(80), TSLA(90), AMZN(95)
  });

  it("search filter still applies even with no presets active", () => {
    const result = applyPresetFilters(items, INITIAL_PRESETS, emptyPrevMap, freshTimestamp, 0, "AAP");
    expect(result).toHaveLength(1);
    expect(result[0].ticker).toBe("AAPL");
  });
});

/* ------------------------------------------------------------------ */
/*  DATA_FRESH with stale timestamp                                    */
/* ------------------------------------------------------------------ */

describe("DATA_FRESH preset", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("matches all items when fetchedAt is recent (< 30s)", () => {
    const now = Date.now();
    vi.setSystemTime(now);
    const recentFetchedAt = now - 5_000; // 5s ago

    const result = items.filter((i) =>
      matchesPreset(i, "DATA_FRESH", emptyPrevMap, recentFetchedAt),
    );
    expect(result).toHaveLength(5);
  });

  it("matches zero items when fetchedAt is stale (>= 30s)", () => {
    const now = Date.now();
    vi.setSystemTime(now);
    const staleFetchedAt = now - 60_000; // 60s ago

    const result = items.filter((i) =>
      matchesPreset(i, "DATA_FRESH", emptyPrevMap, staleFetchedAt),
    );
    expect(result).toHaveLength(0);
  });
});

/* ------------------------------------------------------------------ */
/*  AGENT_DISAGREE preset                                              */
/* ------------------------------------------------------------------ */

describe("AGENT_DISAGREE preset", () => {
  it("matches items with disagreement_score > 0.5", () => {
    const matching = items.filter((i) =>
      matchesPreset(i, "AGENT_DISAGREE", emptyPrevMap, freshTimestamp),
    );
    expect(matching).toHaveLength(2); // AAPL(0.6), GOOG(0.8)
  });

  it("excludes items with null disagreement_score", () => {
    const nullItem = makeItem({ disagreement_score: null });
    expect(matchesPreset(nullItem, "AGENT_DISAGREE", emptyPrevMap, freshTimestamp)).toBe(false);
  });

  it("excludes items with disagreement_score exactly 0.5", () => {
    const exactItem = makeItem({ disagreement_score: 0.5 });
    expect(matchesPreset(exactItem, "AGENT_DISAGREE", emptyPrevMap, freshTimestamp)).toBe(false);
  });
});
