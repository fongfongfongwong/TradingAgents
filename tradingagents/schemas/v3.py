"""V3 Debate System — Shared Pydantic Schemas.

This file is the SINGLE SOURCE OF TRUTH for all data structures
in the v3 pipeline. Every agent, every function, every test must
use these schemas. No agent may add fields, change types, or
deviate from these definitions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ============================================================
# Enums
# ============================================================


class Signal(str, Enum):
    BUY = "BUY"
    SHORT = "SHORT"
    HOLD = "HOLD"


class Regime(str, Enum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    TRANSITIONING = "TRANSITIONING"
    CRISIS = "CRISIS"
    BULLISH_BIAS = "BULLISH_BIAS"
    BEARISH_BIAS = "BEARISH_BIAS"


class Tier(int, Enum):
    FULL = 1
    QUICK = 2
    SCREEN = 3


# ============================================================
# Stage 0: Data Materialization
# ============================================================


class PriceContext(BaseModel):
    """Technical price data, pre-computed from OHLCV."""

    price: float
    change_1d_pct: float
    change_5d_pct: float
    change_20d_pct: float
    sma_20: float
    sma_50: float
    sma_200: float
    rsi_14: float
    macd_above_signal: bool
    macd_crossover_days: int
    bollinger_position: Literal["upper_third", "middle_third", "lower_third"]
    volume_vs_avg_20d: float
    atr_14: float
    # Annualized realized volatility of log returns over the last 20 trading
    # days, expressed as a percent (e.g. ``32.5`` means 32.5%). ``None`` when
    # fewer than 20 bars are available.
    realized_vol_20d_pct: float | None = None
    # ``atr_14`` divided by current price, expressed as a percent
    # (e.g. ``2.4`` means 2.4%). ``None`` when price or atr is unavailable.
    atr_pct_of_price: float | None = None
    # Intraday (5-min bars, last trading day)
    intraday_rsi_14: float | None = None
    intraday_macd_above_signal: bool | None = None
    intraday_vwap_position: Literal["above", "below"] | None = None
    intraday_change_pct: float | None = None  # change from open
    data_age_seconds: int


class OptionsContext(BaseModel):
    """Options market summary.

    Fields come from two cascading providers:

    * **OI-based fields** (``put_call_ratio``, ``iv_rank_percentile``,
      ``iv_skew_25d``, ``max_pain_price``, ``unusual_activity_summary``) come
      from yfinance option chains. Free, lagging up to 1 day.
    * **Trade-flow fields** (``flow_put_call_ratio``, ``large_trade_bias``)
      come from Databento OPRA trades when the paid feed is available. They
      reflect real-time institutional flow and are more predictive than
      OI-based PCR for same-day direction.
    * ``trade_flow_source`` tags the origin of the flow data
      (``"databento"`` / ``"yfinance"`` / ``None``) so downstream agents can
      weight it appropriately.
    """

    put_call_ratio: float | None = None
    iv_rank_percentile: float | None = None
    iv_skew_25d: float | None = None
    max_pain_price: float | None = None
    unusual_activity_summary: str = ""
    data_age_seconds: int = 0
    # --- Trade-flow enrichment (Databento OPRA, optional) -----------------
    flow_put_call_ratio: float | None = None
    large_trade_bias: float | None = None
    trade_flow_source: str | None = None


class VolRegime(str, Enum):
    """Realized-volatility regime classification.

    Thresholds are expressed on the annualized percent scale so they can be
    compared directly against ``VolatilityContext.realized_vol_20d_pct``.
    """

    LOW = "LOW"  # realized_vol < 15%
    NORMAL = "NORMAL"  # 15% - 30%
    HIGH = "HIGH"  # 30% - 60%
    EXTREME = "EXTREME"  # > 60%


class KlineBar(BaseModel):
    """Single daily OHLCV bar for mini-chart rendering."""

    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


class VolatilityContext(BaseModel):
    """Rich volatility + K-line summary alongside PriceContext/OptionsContext.

    All fields default to ``None`` / empty so older briefings without a
    ``volatility`` block continue to parse via ``default_factory`` on
    ``TickerBriefing.volatility``.
    """

    realized_vol_5d_pct: float | None = None  # annualized stdev * sqrt(252) * 100
    realized_vol_20d_pct: float | None = None
    realized_vol_60d_pct: float | None = None
    atr_14_pct_of_price: float | None = None
    bollinger_band_width_pct: float | None = None  # (upper - lower) / middle * 100
    iv_rank_percentile: float | None = None  # 0-100, copied from OptionsContext
    vol_regime: VolRegime = VolRegime.NORMAL
    vol_percentile_1y: float | None = None  # current 20d vol vs own 1y history (0-100)
    kline_last_20: list[KlineBar] = Field(default_factory=list)  # most recent 20 daily bars
    data_age_seconds: int = 0

    # HAR-RV Ridge forecast fields (P0 baseline integration).
    # All fields default to ``None`` so older cached briefings remain parseable.
    predicted_rv_1d_pct: float | None = Field(
        default=None,
        description=(
            "Predicted next-day realized volatility (annualized, in percent). "
            "``None`` if no model loaded."
        ),
    )
    predicted_rv_5d_pct: float | None = Field(
        default=None,
        description=(
            "Predicted next-5-day realized volatility (annualized, in percent). "
            "``None`` if no model loaded."
        ),
    )
    rv_forecast_model_version: str | None = Field(
        default=None,
        description=(
            "Model metadata identifier: e.g. "
            "'har_rv_ridge_v1_trained_2026-04-05'. ``None`` if unavailable."
        ),
    )
    rv_forecast_delta_pct: float | None = Field(
        default=None,
        description=(
            "Predicted minus current realized volatility (1d horizon). "
            "Positive values indicate expectation of higher future vol."
        ),
    )
    rv_forecast_feature_set_version: str | None = Field(
        default=None,
        description=(
            "Identifier for the feature set the loaded RV-forecast model was "
            "trained on (e.g. 'tier0', 'tier1'). Used by the UI and audit "
            "trail to disambiguate predictions across model generations. "
            "``None`` for legacy models that predate feature-set tagging."
        ),
    )


class NewsContext(BaseModel):
    """News summary with sentiment scores."""

    top_headlines: list[str] = Field(default_factory=list, max_length=5)
    headline_sentiment_avg: float = 0.0
    event_flags: list[str] = Field(default_factory=list)
    data_age_seconds: int = 0


class SocialContext(BaseModel):
    """Social media sentiment summary."""

    mention_volume_vs_avg: float = 1.0
    sentiment_score: float = 0.0
    trending_narratives: list[str] = Field(default_factory=list, max_length=3)
    data_age_seconds: int = 0


class InstitutionalContext(BaseModel):
    """Institutional alternative-data signals from QuiverQuant.

    Aggregates congressional trading, federal contracts, lobbying spend, and
    SEC Form 4 insider transactions into a single compact block for the
    debate agents. All numeric fields default to zero/empty lists when
    Quiver is unavailable so downstream code can always read the shape.
    """

    # Congressional (US Congress member trades via Quiver)
    congressional_net_buys_30d: int = Field(
        default=0,
        description="Net count of congressional BUY minus SELL transactions in last 30 days.",
    )
    congressional_top_buyers: list[str] = Field(
        default_factory=list,
        description="Top 3 Congress members who bought (name).",
    )
    congressional_top_sellers: list[str] = Field(
        default_factory=list,
        description="Top 3 Congress members who sold (name).",
    )

    # Government contracts (DoD, GSA, etc.)
    govt_contracts_count_90d: int = Field(
        default=0,
        description="Number of federal contracts awarded to company in last 90 days.",
    )
    govt_contracts_total_usd: float = Field(
        default=0.0,
        description="Total USD value of contracts in last 90 days.",
    )

    # Lobbying spend
    lobbying_usd_last_quarter: float = Field(
        default=0.0,
        description="USD spent on federal lobbying in the most recent quarter.",
    )

    # Insider trading (SEC Form 4)
    insider_net_txns_90d: int = Field(
        default=0,
        description="Net count of insider BUY minus SELL Form 4 transactions in last 90 days.",
    )
    insider_top_buyers: list[str] = Field(
        default_factory=list,
        description="Names of top insider buyers (max 3).",
    )

    # Meta
    data_age_seconds: int = Field(
        default=86400,
        description="Age of the freshest Quiver observation in seconds.",
    )
    fetched_ok: bool = Field(
        default=False,
        description="True if Quiver was successfully queried. False means all fields are defaults.",
    )


class MacroContext(BaseModel):
    """Macro economic regime context."""

    regime: Regime = Regime.TRANSITIONING
    fed_funds_rate: float | None = None
    vix_level: float | None = None
    yield_curve_2y10y_bps: int | None = None
    sector_etf_5d_pct: float | None = None
    sector_etf_20d_pct: float | None = None
    data_age_seconds: int = 0


class FundamentalsContext(BaseModel):
    """Basic fundamental metrics from yfinance."""

    market_cap: float | None = None
    pe_ratio: float | None = None  # trailing P/E
    forward_pe: float | None = None
    eps_ttm: float | None = None
    revenue_ttm: float | None = None
    profit_margin: float | None = None
    debt_to_equity: float | None = None
    dividend_yield: float | None = None
    sector: str | None = None
    industry: str | None = None
    data_age_seconds: int = 0


class EventCalendar(BaseModel):
    """Upcoming events for a ticker."""

    next_earnings_days: int | None = None
    ex_dividend_within_30d: bool = False
    fed_meeting_within_30d: bool = False
    known_catalysts: list[str] = Field(default_factory=list)


class TickerBriefing(BaseModel):
    """Complete materialized snapshot for one ticker.

    This is the ONLY data structure agents receive.
    All fields are pre-computed. Agents do not call tools.
    """

    ticker: str
    date: str
    snapshot_id: str
    price: PriceContext
    options: OptionsContext
    news: NewsContext
    social: SocialContext
    institutional: InstitutionalContext = Field(default_factory=InstitutionalContext)
    macro: MacroContext
    events: EventCalendar
    volatility: VolatilityContext = Field(default_factory=VolatilityContext)
    fundamentals: FundamentalsContext | None = None
    data_gaps: list[str] = Field(default_factory=list)


# ============================================================
# Stage 1: Screening
# ============================================================


class ScreeningResult(BaseModel):
    """Tier classification for one ticker."""

    ticker: str
    tier: Tier
    trigger_reasons: list[str]
    factor_score: float = Field(ge=-1.0, le=1.0, description="Baseline factor composite")


# ============================================================
# Stage 2: Agent Outputs
# ============================================================


class Catalyst(BaseModel):
    event: str
    mechanism: str
    magnitude_estimate: str


class MustBeTrue(BaseModel):
    condition: str
    probability: float = Field(ge=0.0, le=1.0)
    evidence: str
    falsifiable_by: str


class ThesisOutput(BaseModel):
    """Output from the Thesis Agent (upside case)."""

    ticker: str
    direction: Literal["BUY"] = "BUY"
    valuation_gap_summary: str
    momentum_aligned: bool
    momentum_detail: str
    catalysts: list[Catalyst]
    contrarian_signals: list[str]
    must_be_true: list[MustBeTrue] = Field(min_length=3, max_length=5)
    weakest_link: str
    confidence_rationale: str
    confidence_score: int = Field(ge=0, le=100)
    used_mock: bool = False


class AntithesisOutput(BaseModel):
    """Output from the Antithesis Agent (downside case)."""

    ticker: str
    direction: Literal["SHORT"] = "SHORT"
    overvaluation_summary: str
    deterioration_present: bool
    deterioration_detail: str
    risk_catalysts: list[Catalyst]
    crowding_fragility: list[str]
    must_be_true: list[MustBeTrue] = Field(min_length=3, max_length=5)
    weakest_link: str
    confidence_rationale: str
    confidence_score: int = Field(ge=0, le=100)
    used_mock: bool = False


class BaseRateOutput(BaseModel):
    """Output from the Base Rate Agent (statistical anchor)."""

    ticker: str
    expected_move_pct: float
    upside_pct: float
    downside_pct: float
    regime: Regime
    historical_analog: str
    base_rate_probability_up: float = Field(ge=0.0, le=1.0)
    volatility_forecast_20d: float
    sector_momentum_rank: int | None = None
    used_mock: bool = False


# ============================================================
# Stage 3: Synthesis
# ============================================================


class Scenario(BaseModel):
    probability: float = Field(ge=0.0, le=1.0)
    target_price: float
    return_pct: float
    rationale: str


class MustBeTrueResolved(BaseModel):
    agent: Literal["thesis", "antithesis"]
    condition: str
    status: Literal["met", "not_met", "indeterminate"]
    challenged: bool
    challenge_data_supported: bool | None = None


class FactualError(BaseModel):
    agent: Literal["thesis", "antithesis"]
    claim: str
    actual: str


class SynthesisOutput(BaseModel):
    """Output from the Synthesis Agent (final signal)."""

    ticker: str
    date: str
    signal: Signal
    conviction: int = Field(ge=0, le=100)
    scenarios: list[Scenario] = Field(min_length=1)
    expected_value_pct: float
    disagreement_score: float = Field(ge=0.0, le=1.0)
    data_audit: list[FactualError] = Field(default_factory=list)
    must_be_true_resolved: list[MustBeTrueResolved] = Field(default_factory=list)
    decision_rationale: str
    key_evidence: list[str]
    hold_threshold_met: bool = False
    used_mock: bool = False


# ============================================================
# Stage 4: Risk
# ============================================================


class StressTestResult(BaseModel):
    scenario: str
    estimated_loss_usd: float
    estimated_loss_pct: float


class RiskOutput(BaseModel):
    """Output from the deterministic risk layer."""

    ticker: str
    signal: Signal
    risk_rating: Literal["LOW", "MEDIUM", "HIGH", "EXTREME"]
    base_shares: int
    volatility_adjusted_shares: int
    concentration_adjusted_shares: int
    event_adjusted_shares: int
    final_shares: int
    position_value_usd: float
    position_pct_of_portfolio: float = Field(ge=0.0, le=0.02)
    binding_constraint: str
    stop_loss_price: float
    stop_loss_type: Literal["volatility", "technical"]
    take_profit_price: float
    risk_reward_ratio: float
    max_loss_usd: float
    max_loss_pct_portfolio: float
    stress_tests: list[StressTestResult]
    risk_flags: list[str]
    execution_notes: str = ""


# ============================================================
# Stage 5: Final Decision (full pipeline output)
# ============================================================


class FinalDecision(BaseModel):
    """Complete output of one analysis pipeline run."""

    ticker: str
    date: str
    snapshot_id: str
    tier: Tier
    screening: ScreeningResult
    thesis: ThesisOutput | None = None
    antithesis: AntithesisOutput | None = None
    base_rate: BaseRateOutput | None = None
    synthesis: SynthesisOutput | None = None
    risk: RiskOutput | None = None
    factor_baseline_score: float
    signal: Signal
    conviction: int = Field(ge=0, le=100)
    final_shares: int = 0
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, int] = Field(default_factory=dict)
    any_agent_used_mock: bool = False
    data_watermark: str = ""
    pipeline_cost_usd: float = 0.0
    pipeline_latency_ms: int = 0
    # Propagated from TickerBriefing so the UI can render a data-attribution
    # panel (Price / News / Options / Macro / Social) without needing a second
    # round-trip. Each entry is a namespaced gap string such as
    # ``"news:finnhub_fallback:..."`` or ``"options:analytics_fallback"``.
    data_gaps: list[str] = Field(default_factory=list)
    # ------------------------------------------------------------------
    # Second-dimension signals surfaced on the batch-signals table.
    # Populated from the ticker's TickerBriefing at pipeline assembly so
    # the UI can render them without a second round-trip.
    # ------------------------------------------------------------------
    options_direction: Literal["BULL", "BEAR", "NEUTRAL"] | None = None
    options_impact: int | None = Field(default=None, ge=0, le=100)
    realized_vol_20d_pct: float | None = None
    atr_pct_of_price: float | None = None
    # Full volatility context propagated from TickerBriefing so the UI can
    # render HAR-RV Ridge forecast details without a second round-trip.
    volatility: VolatilityContext | None = Field(
        default=None,
        description="Full volatility context with HAR-RV Ridge forecasts (if model trained).",
    )
    # ------------------------------------------------------------------
    # Divergence Engine output (5-dimension signal fusion).
    # ------------------------------------------------------------------
    divergence_score: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="Composite divergence score in [-1, +1]. None when engine unavailable.",
    )
    divergence_summary: str | None = Field(
        default=None,
        description="Human-readable divergence summary for audit trail.",
    )


# ============================================================
# Stage 6: Memory
# ============================================================


class TradeRecord(BaseModel):
    """Stored after a position is opened."""

    ticker: str
    entry_date: str
    entry_price: float
    direction: Signal
    shares: int
    conviction_at_entry: int
    snapshot_id: str
    thesis_summary: str
    antithesis_summary: str


class TradeOutcome(BaseModel):
    """Stored after a position is closed."""

    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_usd: float
    was_correct: bool
    holding_days: int


class AgentReflection(BaseModel):
    """One agent's reflection on a completed trade."""

    agent: Literal["thesis", "antithesis", "base_rate", "synthesis"]
    trade_ticker: str
    trade_date: str
    prediction_correct: bool
    what_i_got_right: str
    what_i_missed: str
    lesson: str
    confidence_was_calibrated: bool
    tags: list[str]
    importance_score: float = Field(ge=0.0, le=1.0)


class SemanticLesson(BaseModel):
    """Distilled principle from multiple episodic memories."""

    lesson: str
    evidence_count: int
    first_observed: str
    last_observed: str
    tags: list[str]
    importance: float = Field(ge=0.0, le=1.0)
