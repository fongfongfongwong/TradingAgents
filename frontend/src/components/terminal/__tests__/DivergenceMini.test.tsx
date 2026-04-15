import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  biasLabel,
  confidenceOpacity,
  DivergenceMiniComponent,
} from "../RightPanel";

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock("@/hooks/useTicker", () => ({
  useTicker: () => ({ ticker: "AAPL", setTicker: vi.fn() }),
}));

const mockDivergence = vi.fn();

vi.mock("@/lib/api", () => ({
  getScoredNews: vi.fn().mockResolvedValue([]),
  getDivergence: (...args: unknown[]) => mockDivergence(...args),
}));

function makeDivergenceData(overrides: {
  composite_score?: number;
  dimensions?: Record<
    string,
    { value: number; confidence: number; sources: string[]; raw_data: Record<string, unknown> }
  >;
}) {
  return {
    ticker: "AAPL",
    regime: "RISK_ON",
    composite_score: overrides.composite_score ?? 0,
    dimensions: overrides.dimensions ?? {
      institutional: { value: 0.2, confidence: 0.8, sources: [], raw_data: {} },
      options: { value: -0.1, confidence: 0.5, sources: [], raw_data: {} },
      price_action: { value: 0.05, confidence: 0.9, sources: [], raw_data: {} },
      news: { value: -0.032, confidence: 0.2, sources: [], raw_data: {} },
      retail: { value: 0.0, confidence: 0.0, sources: [], raw_data: {} },
    },
    timestamp: "2026-04-06T00:00:00Z",
  };
}

/* ------------------------------------------------------------------ */
/*  biasLabel pure-function tests                                      */
/* ------------------------------------------------------------------ */

describe("biasLabel", () => {
  it("returns BULLISH BIAS for composite > +0.15", () => {
    expect(biasLabel(0.25).label).toBe("BULLISH BIAS");
  });

  it("returns BULLISH LEAN for composite between +0.05 and +0.15", () => {
    expect(biasLabel(0.10).label).toBe("BULLISH LEAN");
  });

  it("returns NEUTRAL for composite -0.032 (within +/-0.05)", () => {
    expect(biasLabel(-0.032).label).toBe("NEUTRAL");
  });

  it("returns NEUTRAL for composite 0", () => {
    expect(biasLabel(0).label).toBe("NEUTRAL");
  });

  it("returns BEARISH LEAN for composite between -0.15 and -0.05", () => {
    expect(biasLabel(-0.10).label).toBe("BEARISH LEAN");
  });

  it("returns BEARISH BIAS for composite < -0.15", () => {
    expect(biasLabel(-0.30).label).toBe("BEARISH BIAS");
  });
});

/* ------------------------------------------------------------------ */
/*  confidenceOpacity pure-function tests                              */
/* ------------------------------------------------------------------ */

describe("confidenceOpacity", () => {
  it("returns opacity-100 for confidence >= 0.6", () => {
    expect(confidenceOpacity(0.8)).toBe("opacity-100");
    expect(confidenceOpacity(0.6)).toBe("opacity-100");
  });

  it("returns opacity-60 for confidence >= 0.3 and < 0.6", () => {
    expect(confidenceOpacity(0.5)).toBe("opacity-60");
    expect(confidenceOpacity(0.3)).toBe("opacity-60");
  });

  it("returns opacity-35 for confidence < 0.3", () => {
    expect(confidenceOpacity(0.2)).toBe("opacity-35");
    expect(confidenceOpacity(0)).toBe("opacity-35");
  });
});

/* ------------------------------------------------------------------ */
/*  Rendered component tests                                           */
/* ------------------------------------------------------------------ */

describe("DivergenceMini rendered", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows per-dimension values with 3 decimal places", async () => {
    const divergenceData = makeDivergenceData({ composite_score: 0.05 });
    mockDivergence.mockResolvedValue(divergenceData);

    render(<DivergenceMiniComponent />);

    const newsValue = await screen.findByTestId("dim-value-news");
    // -0.032 should render as "-0.032", NOT "-0.0"
    expect(newsValue.textContent).toBe("-0.032");
  });

  it("renders BULLISH BIAS pill for composite > 0.15", async () => {
    mockDivergence.mockResolvedValue(
      makeDivergenceData({ composite_score: 0.25 }),
    );

    render(<DivergenceMiniComponent />);

    const pill = await screen.findByTestId("bias-label");
    expect(pill.textContent).toBe("BULLISH BIAS");
  });

  it("renders NEUTRAL pill for composite -0.032", async () => {
    mockDivergence.mockResolvedValue(
      makeDivergenceData({ composite_score: -0.032 }),
    );

    render(<DivergenceMiniComponent />);

    const pill = await screen.findByTestId("bias-label");
    expect(pill.textContent).toBe("NEUTRAL");
  });

  it("applies low-opacity class for confidence < 0.3", async () => {
    mockDivergence.mockResolvedValue(
      makeDivergenceData({
        composite_score: 0,
        dimensions: {
          news: { value: -0.01, confidence: 0.1, sources: [], raw_data: {} },
        },
      }),
    );

    render(<DivergenceMiniComponent />);

    const row = await screen.findByTestId("dim-row-news");
    expect(row.className).toContain("opacity-35");
  });

  it("renders weights text", async () => {
    mockDivergence.mockResolvedValue(
      makeDivergenceData({ composite_score: 0 }),
    );

    render(<DivergenceMiniComponent />);

    const weightsEl = await screen.findByTestId("weights-text");
    expect(weightsEl.textContent).toContain("weights:");
    expect(weightsEl.textContent).toContain("inst 0.35");
    expect(weightsEl.textContent).toContain("opti 0.25");
  });
});
