import { describe, it, expect } from "vitest";
import { sortValue } from "@/lib/signalSort";
import { volColor } from "@/lib/volColor";
import type { BatchSignalItem } from "@/lib/api";

const baseItem: BatchSignalItem = {
  ticker: "AAPL",
  signal: "BUY",
  conviction: 65,
  tier: 1,
  pipeline_latency_ms: 1234,
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

describe("sortValue(predicted_rv_1d_pct)", () => {
  it("returns the numeric predicted_rv_1d_pct value", () => {
    expect(sortValue(baseItem, "predicted_rv_1d_pct")).toBe(21.4);
  });

  it("returns NEGATIVE_INFINITY when predicted_rv_1d_pct is null", () => {
    const item: BatchSignalItem = { ...baseItem, predicted_rv_1d_pct: null };
    expect(sortValue(item, "predicted_rv_1d_pct")).toBe(
      Number.NEGATIVE_INFINITY,
    );
  });

  it("returns NEGATIVE_INFINITY when predicted_rv_1d_pct is undefined", () => {
    const { predicted_rv_1d_pct: _omit, ...rest } = baseItem;
    expect(sortValue(rest as BatchSignalItem, "predicted_rv_1d_pct")).toBe(
      Number.NEGATIVE_INFINITY,
    );
  });
});

describe("volColor thresholds (shared with RV forecast column)", () => {
  it("returns red for pred > 40%", () => {
    expect(volColor(45)).toBe("#F85149");
  });

  it("returns amber for pred between 20 and 40 inclusive", () => {
    expect(volColor(25)).toBe("#D29922");
    expect(volColor(40)).toBe("#D29922");
  });

  it("returns green for pred < 20%", () => {
    expect(volColor(15)).toBe("#3FB950");
  });

  it("returns neutral gray for null / undefined", () => {
    expect(volColor(null)).toBe("#484F58");
    expect(volColor(undefined)).toBe("#484F58");
  });
});
