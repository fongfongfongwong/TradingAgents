import { describe, it, expect, beforeEach } from "vitest";

import { useSignalsStore } from "../signalsStore";
import type { BatchSignalItem } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Test helpers                                                       */
/* ------------------------------------------------------------------ */

function makeItem(overrides: Partial<BatchSignalItem> = {}): BatchSignalItem {
  return {
    ticker: "AAPL",
    signal: "BUY",
    conviction: 80,
    tier: 1,
    expected_value_pct: 2.5,
    thesis_confidence: 70,
    antithesis_confidence: 30,
    disagreement_score: 0.4,
    final_shares: 100,
    pipeline_latency_ms: 1500,
    data_gaps: [],
    cached: false,
    cost_usd: 0.05,
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("signalsStore", () => {
  beforeEach(() => {
    // Reset store to initial state before each test.
    useSignalsStore.getState().reset();
  });

  it("setItems replaces items array", () => {
    const items = [makeItem({ ticker: "AAPL" }), makeItem({ ticker: "TSLA" })];
    useSignalsStore.getState().setItems(items);

    const state = useSignalsStore.getState();
    expect(state.items).toHaveLength(2);
    expect(state.items[0].ticker).toBe("AAPL");
    expect(state.items[1].ticker).toBe("TSLA");
    expect(state.lastRefreshedAt).toBeTypeOf("number");
  });

  it("snapshotForDiff copies items to prevItems (deep copy, not reference)", () => {
    const items = [makeItem({ ticker: "AAPL", conviction: 80 })];
    useSignalsStore.getState().setItems(items);
    useSignalsStore.getState().snapshotForDiff();

    // Mutate the store's items to prove prevItems is a separate copy.
    useSignalsStore.getState().upsertTicker("AAPL", { conviction: 99 });

    const state = useSignalsStore.getState();
    expect(state.prevItems).toHaveLength(1);
    expect(state.prevItems[0].conviction).toBe(80);
    expect(state.items[0].conviction).toBe(99);
    // Not the same reference.
    expect(state.items).not.toBe(state.prevItems);
  });

  it("upsertTicker updates existing item in-place", () => {
    useSignalsStore
      .getState()
      .setItems([makeItem({ ticker: "AAPL", conviction: 50 })]);

    useSignalsStore
      .getState()
      .upsertTicker("AAPL", { conviction: 90, signal: "SHORT" });

    const state = useSignalsStore.getState();
    expect(state.items).toHaveLength(1);
    expect(state.items[0].conviction).toBe(90);
    expect(state.items[0].signal).toBe("SHORT");
    // Unchanged fields preserved.
    expect(state.items[0].tier).toBe(1);
  });

  it("upsertTicker appends new item if ticker not found", () => {
    useSignalsStore
      .getState()
      .setItems([makeItem({ ticker: "AAPL" })]);

    useSignalsStore
      .getState()
      .upsertTicker("NVDA", { signal: "BUY", conviction: 75 });

    const state = useSignalsStore.getState();
    expect(state.items).toHaveLength(2);
    const nvda = state.items.find((i) => i.ticker === "NVDA");
    expect(nvda).toBeDefined();
    expect(nvda!.signal).toBe("BUY");
    expect(nvda!.conviction).toBe(75);
    // Stub defaults.
    expect(nvda!.tier).toBe(0);
    expect(nvda!.data_gaps).toEqual([]);
  });

  it("setBatchProgress updates progress", () => {
    const progress = { total: 10, completed: 5, failed: 1, running: 4 };
    useSignalsStore.getState().setBatchProgress(progress);

    expect(useSignalsStore.getState().batchProgress).toEqual(progress);
  });

  it("reset clears everything", () => {
    useSignalsStore.getState().setItems([makeItem()]);
    useSignalsStore.getState().snapshotForDiff();
    useSignalsStore.getState().setBatchId("batch-123");
    useSignalsStore
      .getState()
      .setBatchProgress({ total: 5, completed: 3, failed: 0, running: 2 });

    useSignalsStore.getState().reset();

    const state = useSignalsStore.getState();
    expect(state.items).toEqual([]);
    expect(state.prevItems).toEqual([]);
    expect(state.batchId).toBeNull();
    expect(state.batchProgress).toBeNull();
    expect(state.lastRefreshedAt).toBeNull();
  });
});
