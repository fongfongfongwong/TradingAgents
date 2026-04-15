"""Response models for TradingAgents API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalysisResponse(BaseModel):
    """Response for analysis endpoints."""

    analysis_id: str
    status: str
    ticker: str
    result: dict[str, Any] | None = None


class DivergenceResponse(BaseModel):
    """Response for GET /api/divergence/{ticker}."""

    ticker: str
    regime: str
    composite_score: float
    dimensions: dict[str, Any]
    timestamp: str


class BacktestResponse(BaseModel):
    """Response for POST /api/backtest."""

    ticker: str
    metrics: dict[str, Any]
    trades_count: int


class HealthResponse(BaseModel):
    """Response for GET /health."""

    status: str
    version: str
    tests_passed: int | None = None


class BatchSignalItem(BaseModel):
    """Single-ticker result for GET /api/v3/signals/batch.

    Produced by running the full v3 pipeline (``run_analysis``) for one
    ticker. On pipeline failure the ticker is returned with ``signal="HOLD"``,
    ``conviction=0``, and the error captured in ``data_gaps``.
    """

    ticker: str
    signal: Literal["BUY", "SHORT", "HOLD"]
    conviction: int  # 0-100
    tier: int  # 1, 2, 3
    expected_value_pct: float | None
    thesis_confidence: float | None  # 0-100
    antithesis_confidence: float | None  # 0-100
    disagreement_score: float | None  # 0-1
    final_shares: int
    pipeline_latency_ms: int
    data_gaps: list[str]
    cached: bool  # True if served from cache
    cost_usd: float = 0.0  # total LLM cost for this ticker's run
    models_used: list[str] = Field(default_factory=list)
    # ------------------------------------------------------------------
    # Steps 3+4: second-dimension signals surfaced on the signals table.
    # Populated from the ticker's TickerBriefing at pipeline assembly.
    # ``None`` on error items or when the underlying data is unavailable.
    # ------------------------------------------------------------------
    options_direction: Literal["BULL", "BEAR", "NEUTRAL"] | None = None
    options_impact: int | None = Field(default=None, ge=0, le=100)
    realized_vol_20d_pct: float | None = None
    atr_pct_of_price: float | None = None
    # ------------------------------------------------------------------
    # HAR-RV Ridge forecast fields surfaced from VolatilityContext so the
    # signals table can render forecast vs realized comparisons without a
    # second round-trip. ``None`` when the model is not trained or the
    # ticker has insufficient history.
    # ------------------------------------------------------------------
    predicted_rv_1d_pct: float | None = None
    predicted_rv_5d_pct: float | None = None
    rv_forecast_delta_pct: float | None = None
    rv_forecast_model_version: str | None = None
    # True if any v3 agent fell back to a deterministic mock during this run.
    used_mock: bool = False
    # Take-Profit / Stop-Loss from risk layer
    tp_price: float | None = None
    sl_price: float | None = None
    risk_reward: float | None = None
    # Real-time price fields populated post-pipeline from price snapshot cache.
    last_price: float | None = None
    change_pct: float | None = None


# ---------------------------------------------------------------------------
# G4: Runtime configuration model
# ---------------------------------------------------------------------------


class RuntimeConfig(BaseModel):
    """User-editable runtime configuration surfaced via /api/config/runtime.

    Persists to ``~/.tradingagents/runtime_config.json``. All fields have
    safe defaults so a missing file yields a fully valid config.
    """

    llm_provider: Literal["anthropic", "openai", "google", "xai"] = "anthropic"

    thesis_model: str = "claude-sonnet-4-5"
    antithesis_model: str = "claude-sonnet-4-5"
    base_rate_model: str = "claude-sonnet-4-5"
    synthesis_model: str = "claude-sonnet-4-5"
    synthesis_fallback_model: str = "claude-sonnet-4-5"

    data_vendor_price: Literal["yfinance", "polygon", "alpha_vantage"] = "yfinance"
    data_vendor_news: Literal["yfinance", "finnhub"] = "yfinance"
    data_vendor_options: Literal["yfinance", "cboe", "databento"] = "yfinance"
    data_vendor_macro: Literal["yfinance", "fred"] = "yfinance"
    data_vendor_social: Literal[
        "disabled", "fear_greed_apewisdom"
    ] = "fear_greed_apewisdom"

    output_language: Literal["en", "zh", "ja", "es"] = "en"

    budget_daily_usd: float = Field(default=15.0, ge=0, le=10_000)
    budget_per_ticker_usd: float = Field(default=0.60, ge=0, le=1_000)

    analyst_selection: list[str] = Field(
        default_factory=lambda: [
            "market",
            "news",
            "fundamentals",
            "macro",
            "options",
            "social",
        ]
    )


class ScoredHeadline(BaseModel):
    """Prioritized headline for the v3 news scorer endpoint."""

    title: str
    source: str | None = None
    url: str | None = None
    published_at: str | None = None  # ISO8601
    relevance: float = Field(ge=0, le=1)
    direction: Literal["LONG", "SHORT", "NEUTRAL"]
    confidence: float = Field(ge=0, le=1)
    impact_score: float = Field(ge=0, le=1)  # final sort key
    tags: list[str] = Field(default_factory=list)
    rationale: str
