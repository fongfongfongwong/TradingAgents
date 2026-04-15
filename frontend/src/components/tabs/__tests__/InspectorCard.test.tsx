import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import InspectorCard from "../InspectorCard";
import type {
  V3FinalDecision,
  V3ThesisResult,
  V3AntithesisResult,
  V3BaseRateResult,
  V3SynthesisResult,
  V3RiskResult,
  V3VolatilityContext,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Fixture helpers                                                    */
/* ------------------------------------------------------------------ */

function makeThesis(overrides?: Partial<V3ThesisResult>): V3ThesisResult {
  return {
    ticker: "NVDA",
    direction: "BULLISH",
    confidence_score: 72,
    valuation_gap_summary: "Undervalued by 15%",
    momentum_aligned: true,
    momentum_detail: "Strong uptrend",
    catalysts: [],
    must_be_true: [],
    weakest_link: "Macro headwinds",
    confidence_rationale: "Strong fundamentals",
    contrarian_signals: [],
    ...overrides,
  };
}

function makeAntithesis(overrides?: Partial<V3AntithesisResult>): V3AntithesisResult {
  return {
    ticker: "NVDA",
    direction: "BEARISH",
    confidence_score: 41,
    overvaluation_summary: "Slight overvaluation",
    deterioration_present: false,
    deterioration_detail: "",
    risk_catalysts: [],
    must_be_true: [],
    weakest_link: "Earnings risk",
    confidence_rationale: "Limited downside catalysts",
    crowding_fragility: [],
    ...overrides,
  };
}

function makeBaseRate(overrides?: Partial<V3BaseRateResult>): V3BaseRateResult {
  return {
    ticker: "NVDA",
    expected_move_pct: 3.2,
    upside_pct: 8.5,
    downside_pct: -5.3,
    regime: "NORMAL",
    historical_analog: "2023 Q4 rally",
    base_rate_probability_up: 0.55,
    volatility_forecast_20d: 28.0,
    ...overrides,
  };
}

function makeSynthesis(overrides?: Partial<V3SynthesisResult>): V3SynthesisResult {
  return {
    ticker: "NVDA",
    signal: "BUY",
    conviction: 78,
    scenarios: [],
    expected_value_pct: 5.2,
    disagreement_score: 0.3,
    decision_rationale: "Strong momentum with solid fundamentals outweighs bear case.",
    key_evidence: ["AI spending cycle accelerating", "Valuation gap supportive"],
    ...overrides,
  };
}

function makeRisk(): V3RiskResult {
  return {
    ticker: "NVDA",
    signal: "BUY",
    risk_rating: "MEDIUM",
    final_shares: 50,
    position_pct_of_portfolio: 2.5,
    stop_loss_price: 118.0,
    take_profit_price: 145.0,
    risk_reward_ratio: 2.1,
    max_loss_usd: 500,
    risk_flags: [],
    stress_tests: [],
  };
}

function makeVol(overrides?: Partial<V3VolatilityContext>): V3VolatilityContext {
  return {
    realized_vol_5d_pct: 22.5,
    realized_vol_20d_pct: 28.3,
    realized_vol_60d_pct: 25.1,
    atr_14_pct_of_price: 2.1,
    bollinger_band_width_pct: 5.8,
    iv_rank_percentile: 45.0,
    vol_regime: "NORMAL",
    vol_percentile_1y: 55.0,
    kline_last_20: [],
    data_age_seconds: 30,
    predicted_rv_1d_pct: 30.2,
    predicted_rv_5d_pct: 27.8,
    rv_forecast_model_version: "har_rv_ridge_2025-01-01",
    rv_forecast_delta_pct: 1.9,
    ...overrides,
  };
}

function makeDecision(overrides?: Partial<V3FinalDecision>): V3FinalDecision {
  return {
    ticker: "NVDA",
    date: "2025-06-01",
    snapshot_id: "snap_abc123",
    tier: 1,
    signal: "BUY",
    conviction: 78,
    final_shares: 50,
    factor_baseline_score: 0.82,
    pipeline_latency_ms: 12000,
    thesis: makeThesis(),
    antithesis: makeAntithesis(),
    base_rate: makeBaseRate(),
    synthesis: makeSynthesis(),
    risk: makeRisk(),
    data_gaps: [],
    volatility: makeVol(),
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("InspectorCard", () => {
  it("renders BUY verdict with green styling when signal=BUY", () => {
    render(<InspectorCard data={makeDecision()} />);
    const verdictBox = screen.getByTestId("verdict-box");
    // Background uses gradient + border
    expect(verdictBox).toHaveStyle({ background: "linear-gradient(180deg, #062c1f 0%, #041f16 100%)" });
    // The signal text should be present and green
    const signalText = verdictBox.querySelector("span");
    expect(signalText).toHaveTextContent("BUY");
    expect(signalText).toHaveStyle({ color: "#34d399" });
  });

  it("renders SHORT verdict with red styling when signal=SHORT", () => {
    const data = makeDecision({
      signal: "SHORT",
      synthesis: makeSynthesis({ signal: "SHORT", expected_value_pct: -4.1 }),
    });
    render(<InspectorCard data={data} />);
    const verdictBox = screen.getByTestId("verdict-box");
    expect(verdictBox).toHaveStyle({ background: "linear-gradient(180deg, #2c0608 0%, #1c0608 100%)" });
    const signalText = verdictBox.querySelector("span");
    expect(signalText).toHaveTextContent("SHORT");
    expect(signalText).toHaveStyle({ color: "#fca5a5" });
  });

  it("shows conviction number", () => {
    render(<InspectorCard data={makeDecision({ conviction: 85 })} />);
    expect(screen.getByText("85")).toBeInTheDocument();
  });

  it("shows 'Because:' text from decision_rationale", () => {
    render(<InspectorCard data={makeDecision()} />);
    const block = screen.getByTestId("because-block");
    expect(block).toHaveTextContent("Because");
    expect(block).toHaveTextContent(
      "Strong momentum with solid fundamentals outweighs bear case.",
    );
  });

  it("shows 3 agent cards + synthesis card", () => {
    render(<InspectorCard data={makeDecision()} />);
    // Thesis card shows direction and confidence
    expect(screen.getByText("Thesis")).toBeInTheDocument();
    // "BUY" appears multiple times (verdict + thesis direction), so use getAllByText
    expect(screen.getAllByText("BUY").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("72%")).toBeInTheDocument();
    // Antithesis
    expect(screen.getByText("Antithesis")).toBeInTheDocument();
    expect(screen.getAllByText("SHORT").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("41%")).toBeInTheDocument();
    // Base Rate
    expect(screen.getByText("Base Rate")).toBeInTheDocument();
    expect(screen.getByText("55%")).toBeInTheDocument();
    // Synthesis full-width card
    expect(screen.getByText("Synthesis")).toBeInTheDocument();
  });

  it("handles null thesis/antithesis gracefully (shows 'pending' state)", () => {
    const data = makeDecision({ thesis: null, antithesis: null });
    render(<InspectorCard data={data} />);
    expect(screen.getByTestId("thesis-pending")).toBeInTheDocument();
    expect(screen.getByTestId("antithesis-pending")).toBeInTheDocument();
    // "pending" text should appear
    const pendingElements = screen.getAllByText("pending");
    expect(pendingElements.length).toBeGreaterThanOrEqual(2);
  });

  it("shows vol metrics when volatility context present", () => {
    render(<InspectorCard data={makeDecision()} />);
    // RV 20d should show the value
    expect(screen.getByText("28.3%")).toBeInTheDocument();
    // HAR 1d
    expect(screen.getByText("30.2%")).toBeInTheDocument();
    // HAR 5d
    expect(screen.getByText("27.8%")).toBeInTheDocument();
    // IV Rank
    expect(screen.getByText("45.0%")).toBeInTheDocument();
  });

  it("shows 'N/A' when volatility context is null", () => {
    const data = makeDecision({ volatility: null });
    render(<InspectorCard data={data} />);
    const naBlock = screen.getByTestId("vol-na");
    const naTexts = Array.from(naBlock.querySelectorAll("div")).filter(
      (el) => el.textContent === "N/A",
    );
    expect(naTexts.length).toBe(6);
  });

  /* -------------------------------------------------------------- */
  /*  NEW: Sentiment Consensus section                               */
  /* -------------------------------------------------------------- */

  it("renders sentiment placeholder when no sentiment data present", () => {
    render(<InspectorCard data={makeDecision()} />);
    const section = screen.getByTestId("sentiment-section");
    expect(section).toBeInTheDocument();
    expect(section).toHaveTextContent("Sentiment Consensus");
    // Should show placeholder text since makeDecision has no sentiment
    expect(section).toHaveTextContent("Run deep analysis for full data");
  });

  it("renders sentiment grid when sentiment data is attached", () => {
    const data = {
      ...makeDecision(),
      sentiment: {
        news_sentiment: "Bullish",
        reddit_sentiment: "Neutral",
        congress_sentiment: null,
        insider_sentiment: "Bearish",
        fear_greed: "72",
        composite_sentiment: "Bullish",
      },
    } as unknown as V3FinalDecision;
    render(<InspectorCard data={data} />);
    const section = screen.getByTestId("sentiment-section");
    expect(section).toHaveTextContent("Sentiment Consensus");
    expect(section).toHaveTextContent("Bullish");
    expect(section).toHaveTextContent("Neutral");
    expect(section).toHaveTextContent("72");
  });

  /* -------------------------------------------------------------- */
  /*  NEW: Options Context section                                   */
  /* -------------------------------------------------------------- */

  it("renders options placeholder when no options data present", () => {
    render(<InspectorCard data={makeDecision()} />);
    const section = screen.getByTestId("options-section");
    expect(section).toBeInTheDocument();
    expect(section).toHaveTextContent("Options Context");
    expect(section).toHaveTextContent("Run deep analysis for full data");
  });

  it("renders options grid when options data is attached", () => {
    const data = {
      ...makeDecision(),
      options_direction: "BULL",
      options_impact: 3.5,
    } as unknown as V3FinalDecision;
    render(<InspectorCard data={data} />);
    const section = screen.getByTestId("options-section");
    expect(section).toHaveTextContent("Options Context");
    expect(section).toHaveTextContent("BULL");
    expect(section).toHaveTextContent("3.5%");
  });

  /* -------------------------------------------------------------- */
  /*  NEW: Verdict action buttons                                    */
  /* -------------------------------------------------------------- */

  it("renders verdict action buttons when callbacks provided", () => {
    const onRerun = vi.fn();
    const onPin = vi.fn();
    render(
      <InspectorCard
        data={makeDecision()}
        onRerun={onRerun}
        onPin={onPin}
        pinned={false}
      />,
    );
    expect(screen.getByTestId("verdict-actions")).toBeInTheDocument();
    expect(screen.getByTestId("btn-rerun")).toBeInTheDocument();
    expect(screen.getByTestId("btn-pin")).toBeInTheDocument();
    expect(screen.getByTestId("btn-copy")).toBeInTheDocument();
  });

  it("calls onRerun when rerun button clicked", () => {
    const onRerun = vi.fn();
    render(<InspectorCard data={makeDecision()} onRerun={onRerun} />);
    fireEvent.click(screen.getByTestId("btn-rerun"));
    expect(onRerun).toHaveBeenCalledTimes(1);
  });

  it("calls onPin with ticker when pin button clicked", () => {
    const onPin = vi.fn();
    render(<InspectorCard data={makeDecision()} onPin={onPin} />);
    fireEvent.click(screen.getByTestId("btn-pin"));
    expect(onPin).toHaveBeenCalledWith("NVDA");
  });

  it("copy button is always rendered (even without onRerun/onPin)", () => {
    render(<InspectorCard data={makeDecision()} />);
    expect(screen.getByTestId("btn-copy")).toBeInTheDocument();
  });

  it("does not render rerun button when onRerun is not provided", () => {
    render(<InspectorCard data={makeDecision()} />);
    expect(screen.queryByTestId("btn-rerun")).not.toBeInTheDocument();
  });

  it("does not render pin button when onPin is not provided", () => {
    render(<InspectorCard data={makeDecision()} />);
    expect(screen.queryByTestId("btn-pin")).not.toBeInTheDocument();
  });

  /* -------------------------------------------------------------- */
  /*  All sections render (scrollability check)                      */
  /* -------------------------------------------------------------- */

  it("renders all four sub-sections below the verdict", () => {
    render(<InspectorCard data={makeDecision()} />);
    // Debate Rollup
    expect(screen.getByText("Debate Rollup")).toBeInTheDocument();
    // Volatility
    expect(screen.getByTestId("volatility-section")).toBeInTheDocument();
    // Sentiment Consensus
    expect(screen.getByTestId("sentiment-section")).toBeInTheDocument();
    // Options Context
    expect(screen.getByTestId("options-section")).toBeInTheDocument();
  });
});
