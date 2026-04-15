const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/* ------------------------------------------------------------------ */
/*  Types aligned with backend Pydantic models                         */
/* ------------------------------------------------------------------ */

// -- Analysis --

export interface AnalyzeRequest {
  ticker: string;
  trade_date: string;
  selected_analysts?: string[];
  debate_rounds?: number;
}

/** Matches backend AnalysisResponse exactly. */
export interface AnalysisResponse {
  analysis_id: string;
  status: "pending" | "running" | "complete" | "failed";
  ticker: string;
  result: AnalysisResult | null;
}

export interface AnalysisResult {
  ticker: string;
  trade_date: string;
  decision: string;
  confidence: number;
  analysts: string[];
}

/** Shape returned by GET /api/analyses (list endpoint). */
export interface AnalysisListItem {
  id: string;
  ticker: string;
  status: "pending" | "running" | "complete" | "failed";
  result: AnalysisResult | null;
  created_at: string;
}

// -- Divergence --

export interface DivergenceDimensionValue {
  value: number;
  confidence: number;
  sources: string[];
  raw_data: Record<string, unknown>;
}

/** Matches backend DivergenceResponse exactly. */
export interface DivergenceData {
  ticker: string;
  regime: string;
  composite_score: number;
  dimensions: Record<string, DivergenceDimensionValue>;
  timestamp: string;
}

// -- Backtest --

export interface BacktestRequest {
  ticker: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
}

/** Matches backend BacktestResponse exactly. */
export interface BacktestResult {
  ticker: string;
  metrics: Record<string, number>;
  trades_count: number;
}

// -- Portfolio --

export interface Position {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
}

export interface PortfolioSummary {
  total_value: number;
  cash: number;
  total_pnl: number;
  total_pnl_pct: number;
  positions: Position[];
}

// -- Stats --

export interface SystemStats {
  analyses_today: number;
  analyses_total: number;
  active_agents: number;
  avg_confidence: number;
}

// -- Config --

export interface AppConfig {
  [key: string]: unknown;
}

// -- Price --

export interface PriceBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// -- News --

export interface NewsItem {
  title: string;
  source: string;
  url: string;
  published_at: string;
  sentiment: number | null;
  relevance: number | null;
  summary: string | null;
}

// -- Options --

export interface OptionsChainRow {
  strike: number;
  call_bid: number | null;
  call_ask: number | null;
  call_volume: number;
  call_oi: number;
  put_bid: number | null;
  put_ask: number | null;
  put_volume: number;
  put_oi: number;
}

export interface OptionsData {
  ticker: string;
  expiration: string;
  chain: OptionsChainRow[];
  put_call_ratio: number;
  iv_rank: number | null;
}

// -- Holdings --

export interface HoldingEntry {
  holder: string;
  shares: number;
  change: number;
  change_pct: number;
  filing_date: string;
}

export interface InsiderTx {
  insider: string;
  relation: string;
  action: "buy" | "sell";
  shares: number;
  price: number;
  date: string;
}

export interface HoldingsData {
  ticker: string;
  institutional: HoldingEntry[];
  insider_transactions: InsiderTx[];
}

// -- Volatility / K-line (mirrors VolatilityContext in schemas/v3.py) --

export type VolRegime = "LOW" | "NORMAL" | "HIGH" | "EXTREME" | "UNKNOWN";

export interface KlineBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface V3VolatilityContext {
  realized_vol_5d_pct: number | null;
  realized_vol_20d_pct: number | null;
  realized_vol_60d_pct: number | null;
  atr_14_pct_of_price: number | null;
  bollinger_band_width_pct: number | null;
  iv_rank_percentile: number | null;
  vol_regime: VolRegime;
  vol_percentile_1y: number | null;
  kline_last_20: KlineBar[];
  data_age_seconds: number;
  // HAR-RV Ridge forecast fields (optional / backward-compatible).
  predicted_rv_1d_pct?: number | null;
  predicted_rv_5d_pct?: number | null;
  rv_forecast_model_version?: string | null;
  rv_forecast_delta_pct?: number | null;
}

export interface RVForecastResponse {
  ticker: string;
  horizon_days: number;
  predicted_rv_pct: number;
  current_realized_vol_20d_pct: number | null;
  delta_pct: number | null;
  model_version: string;
  computed_at: string;
}

/* ------------------------------------------------------------------ */
/*  HTTP helpers                                                       */
/* ------------------------------------------------------------------ */

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }

  return res.json() as Promise<T>;
}

/* ------------------------------------------------------------------ */
/*  API methods                                                        */
/* ------------------------------------------------------------------ */

// Dashboard
export const getStats = () => request<SystemStats>("/api/stats");

// Analysis
export const listAnalyses = (limit = 20) =>
  request<AnalysisListItem[]>(`/api/analyses?limit=${limit}`);

export const startAnalysis = (body: AnalyzeRequest) =>
  request<AnalysisResponse>("/api/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getAnalysis = (id: string) =>
  request<AnalysisResponse>(`/api/analyze/${id}`);

export const streamUrl = (analysisId: string) =>
  `${BASE_URL}/api/analyze/${analysisId}/stream`;

// ---- V3 Debate Pipeline ----

export interface V3AnalyzeRequest {
  ticker: string;
  date?: string;
}

export interface V3CatalystItem {
  event: string;
  mechanism: string;
  magnitude_estimate: string;
}

export interface V3MustBeTrue {
  condition: string;
  probability: number;
  evidence: string;
  falsifiable_by: string;
}

export interface V3InstitutionalContext {
  congressional_net_buys_30d: number;
  congressional_top_buyers: string[];
  congressional_top_sellers: string[];
  govt_contracts_count_90d: number;
  govt_contracts_total_usd: number;
  lobbying_usd_last_quarter: number;
  insider_net_txns_90d: number;
  insider_top_buyers: string[];
  data_age_seconds: number;
  fetched_ok: boolean;
}

export interface V3ThesisResult {
  ticker: string;
  direction: string;
  confidence_score: number;
  valuation_gap_summary: string;
  momentum_aligned: boolean;
  momentum_detail: string;
  catalysts: V3CatalystItem[];
  must_be_true: V3MustBeTrue[];
  weakest_link: string;
  confidence_rationale: string;
  contrarian_signals: string[];
}

export interface V3AntithesisResult {
  ticker: string;
  direction: string;
  confidence_score: number;
  overvaluation_summary: string;
  deterioration_present: boolean;
  deterioration_detail: string;
  risk_catalysts: V3CatalystItem[];
  must_be_true: V3MustBeTrue[];
  weakest_link: string;
  confidence_rationale: string;
  crowding_fragility: string[];
}

export interface V3BaseRateResult {
  ticker: string;
  expected_move_pct: number;
  upside_pct: number;
  downside_pct: number;
  regime: string;
  historical_analog: string;
  base_rate_probability_up: number;
  volatility_forecast_20d: number;
}

export interface V3ScenarioItem {
  probability: number;
  target_price: number;
  return_pct: number;
  rationale: string;
}

export interface V3SynthesisResult {
  ticker: string;
  signal: string;
  conviction: number;
  scenarios: V3ScenarioItem[];
  expected_value_pct: number;
  disagreement_score: number;
  decision_rationale: string;
  key_evidence: string[];
}

export interface V3RiskResult {
  ticker: string;
  signal: string;
  risk_rating: string;
  final_shares: number;
  position_pct_of_portfolio: number;
  stop_loss_price: number;
  take_profit_price: number;
  risk_reward_ratio: number;
  max_loss_usd: number;
  risk_flags: string[];
  stress_tests: { scenario: string; estimated_loss_usd: number; estimated_loss_pct: number }[];
}

export interface V3FinalDecision {
  ticker: string;
  date: string;
  snapshot_id: string;
  tier: number;
  signal: string;
  conviction: number;
  final_shares: number;
  factor_baseline_score: number;
  pipeline_latency_ms: number;
  thesis: V3ThesisResult | null;
  antithesis: V3AntithesisResult | null;
  base_rate: V3BaseRateResult | null;
  synthesis: V3SynthesisResult | null;
  risk: V3RiskResult | null;
  /** Namespaced data-gap strings (e.g. "news:finnhub_fallback", "options:analytics_fallback"). */
  data_gaps?: string[] | null;
  /** Optional volatility briefing (includes HAR-RV Ridge forecast fields when available). */
  volatility?: V3VolatilityContext | null;
}

export interface V3AnalysisStatus {
  analysis_id: string;
  status: "pending" | "running" | "complete" | "failed";
  ticker: string;
  result: V3FinalDecision | null;
  error?: string;
}

// ---- V3 Batch Signals (G1) ----

export interface BatchSignalItem {
  ticker: string;
  signal: "BUY" | "SHORT" | "HOLD";
  conviction: number;
  tier: number;
  expected_value_pct: number | null;
  thesis_confidence: number | null;
  antithesis_confidence: number | null;
  disagreement_score: number | null;
  final_shares: number;
  pipeline_latency_ms: number;
  data_gaps: string[];
  cached: boolean;
  cost_usd?: number;
  models_used?: string[];
  // Steps 3+4: second-dimension briefing-derived signals. All optional so
  // stale cache entries that predate the schema change still parse.
  options_direction?: "BULL" | "BEAR" | "NEUTRAL" | null;
  options_impact?: number | null;
  realized_vol_20d_pct?: number | null;
  atr_pct_of_price?: number | null;
  // HAR-RV Ridge forecast fields (R1 baseline — optional / backward-compatible).
  predicted_rv_1d_pct?: number | null;
  predicted_rv_5d_pct?: number | null;
  rv_forecast_delta_pct?: number | null;
  rv_forecast_model_version?: string | null;
  // True if any v3 agent fell back to a deterministic mock during this run.
  used_mock?: boolean;
  // Take-Profit / Stop-Loss from risk layer.
  tp_price?: number | null;
  sl_price?: number | null;
  risk_reward?: number | null;
  // Real-time price fields from Databento / yfinance fallback.
  last_price?: number | null;
  change_pct?: number | null;
}

// ---- Screener (optional — Run All uses this opportunistically) ----

export interface ScreenerTicker {
  ticker: string;
  is_etf: boolean;
  composite_score: number;
  realized_vol_20d: number | null;
  llm_reason: string | null;
}

export interface ScreenerResult {
  computed_at: string;
  equities: ScreenerTicker[];
  etfs: ScreenerTicker[];
}

// ---- G4: Runtime configuration ----

export type LlmProvider = "anthropic" | "openai" | "google" | "xai";
export type PriceVendor = "yfinance" | "polygon" | "alpha_vantage";
export type NewsVendor = "yfinance" | "finnhub";
export type OptionsVendor = "yfinance" | "cboe";
export type MacroVendor = "yfinance" | "fred";
export type SocialVendor = "disabled" | "fear_greed_apewisdom";
export type OutputLanguage = "en" | "zh" | "ja" | "es";

export interface RuntimeConfig {
  llm_provider: LlmProvider;
  thesis_model: string;
  antithesis_model: string;
  base_rate_model: string;
  synthesis_model: string;
  synthesis_fallback_model: string;
  data_vendor_price: PriceVendor;
  data_vendor_news: NewsVendor;
  data_vendor_options: OptionsVendor;
  data_vendor_macro: MacroVendor;
  data_vendor_social: SocialVendor;
  output_language: OutputLanguage;
  budget_daily_usd: number;
  budget_per_ticker_usd: number;
  analyst_selection: string[];
}

export const getRuntimeConfig = (): Promise<RuntimeConfig> =>
  request<RuntimeConfig>("/api/config/runtime");

export const updateRuntimeConfig = (body: RuntimeConfig): Promise<RuntimeConfig> =>
  request<RuntimeConfig>("/api/config/runtime", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// ---- P0-4: Cost observability ----

export interface CostsToday {
  date: string;
  total_usd: number;
  budget_daily_usd: number;
  budget_per_ticker_usd: number;
  pct_of_daily_budget: number;
  by_agent: Record<string, number>;
  by_ticker: Record<string, number>;
  by_model: Record<string, number>;
  call_count: number;
  budget_breached: boolean;
}

export interface CostsRangeDay {
  date: string;
  total_usd: number;
  call_count: number;
}

export const getCostsToday = (): Promise<CostsToday> =>
  request<CostsToday>("/api/config/costs/today");

export const getCostsRange = (days = 7): Promise<CostsRangeDay[]> =>
  request<CostsRangeDay[]>(`/api/config/costs/range?days=${days}`);

export interface BatchSignalsOptions {
  bypassCache?: boolean;
}

export const getBatchSignals = (
  tickers: string[],
  opts?: BatchSignalsOptions,
): Promise<BatchSignalItem[]> =>
  request<BatchSignalItem[]>(
    `/api/v3/signals/batch?tickers=${tickers.join(",")}${
      opts?.bypassCache ? "&force=1" : ""
    }`,
  );

// ---- Async batch + SSE progress (Run All button) ----

export interface BatchProgress {
  total: number;
  completed: number;
  failed: number;
  running: number;
  status: "running" | "complete" | "failed";
  last_ticker?: string | null;
  last_signal?: string | null;
  total_cost_usd?: number;
  started_at?: string;
  finished_at?: string | null;
}

export interface BatchStartResponse {
  batch_id: string;
  total: number;
}

export const startBatch = (
  tickers: string[],
  force = false,
): Promise<BatchStartResponse> =>
  request<BatchStartResponse>("/api/v3/signals/batch/start", {
    method: "POST",
    body: JSON.stringify({ tickers, force }),
  });

export const getBatchStatus = (
  batchId: string,
): Promise<BatchProgress & { batch_id: string; results: BatchSignalItem[] }> =>
  request<
    BatchProgress & { batch_id: string; results: BatchSignalItem[] }
  >(`/api/v3/signals/batch/${batchId}/status`);

export const batchStreamUrl = (batchId: string): string =>
  `${BASE_URL}/api/v3/signals/batch/${batchId}/stream`;

// Screener endpoints are provided by a sibling module; ``getLatestScreener``
// may 404 when the screener has never been run — callers should handle that.
export const getLatestScreener = (): Promise<ScreenerResult> =>
  request<ScreenerResult>("/api/v3/screener/latest");

export const runScreener = (): Promise<ScreenerResult> =>
  request<ScreenerResult>("/api/v3/screener/run", {
    method: "POST",
    body: "{}",
  });

export const startAnalysisV3 = (body: V3AnalyzeRequest) =>
  request<V3AnalysisStatus>("/api/v3/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getAnalysisV3 = (id: string) =>
  request<V3AnalysisStatus>(`/api/v3/analyze/${id}`);

export const streamUrlV3 = (analysisId: string) =>
  `${BASE_URL}/api/v3/analyze/${analysisId}/stream`;

// Divergence
export const getDivergence = (ticker: string) =>
  request<DivergenceData>(`/api/divergence/${ticker}`);

// HAR-RV Ridge forecast
export const getRVForecast = (
  ticker: string,
  horizon: 1 | 5 = 1,
): Promise<RVForecastResponse> =>
  request<RVForecastResponse>(
    `/api/v3/rv/forecast/${ticker}?horizon=${horizon}`,
  );

// Backtest
export const runBacktest = (body: BacktestRequest) =>
  request<BacktestResult>("/api/backtest", {
    method: "POST",
    body: JSON.stringify(body),
  });

// Portfolio
export const getPortfolio = () => request<PortfolioSummary>("/api/portfolio");

// Config
export const getConfig = () => request<AppConfig>("/api/config");
export const updateConfig = (body: AppConfig) =>
  request<AppConfig>("/api/config", {
    method: "PUT",
    body: JSON.stringify(body),
  });

// Price data (new)
export const getPriceData = (ticker: string, range = "6m") =>
  request<PriceBar[]>(`/api/price/${ticker}?range=${range}`);

// News (new)
export const getNews = (ticker: string) =>
  request<NewsItem[]>(`/api/news/${ticker}`);

// Scored News (v3)
export interface ScoredHeadline {
  title: string;
  source: string | null;
  url: string | null;
  published_at: string | null;
  relevance: number;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  confidence: number;
  impact_score: number;
  tags: string[];
  rationale: string;
}

export const getScoredNews = (ticker: string, limit = 20) =>
  request<ScoredHeadline[]>(`/api/v3/news/${ticker}/scored?limit=${limit}`);

// Options (new)
export const getOptions = (ticker: string) =>
  request<OptionsData>(`/api/options/${ticker}`);

// Real-time price snapshots (Databento / yfinance fallback)
export interface PriceSnapshot {
  last: number;
  change_pct: number;
  source: string;
  ts?: string; // ISO timestamp of the price data point
}

export const getPriceSnapshots = (tickers: string[]) =>
  request<Record<string, PriceSnapshot>>(
    `/api/v3/prices/snapshot?tickers=${tickers.join(",")}`,
  );

// Holdings (new)
export const getHoldings = (ticker: string) =>
  request<HoldingsData>(`/api/holdings/${ticker}`);

// Social sentiment (new)
export interface SocialSentiment {
  ticker: string;
  reddit?: {
    mentions_24h: number;
    mentions_7d: number;
    rank: number;
    sentiment_score: number;
    top_subreddits: string[];
  };
  fear_greed?: {
    value: number;
    label: string;
    previous_close: number;
    one_week_ago: number;
  };
  aaii?: {
    bullish_pct: number;
    bearish_pct: number;
    neutral_pct: number;
    survey_date: string;
  };
  congressional?: {
    politician: string;
    party: string;
    action: string;
    ticker: string;
    amount: string;
    date: string;
  }[];
  overall_sentiment: number;
  data_source: string;
}

export const getSocialSentiment = (ticker: string) =>
  request<SocialSentiment>(`/api/social/${ticker}`);

export const getCongressionalTrades = (ticker: string) =>
  request<{ ticker: string; trades: SocialSentiment["congressional"]; data_source: string }>(
    `/api/congressional/${ticker}`,
  );

// Macro (new)
export interface MacroOverview {
  us: Record<string, number | null>;
  global: Record<string, number | null>;
  geopolitical: Record<string, number | string | null>;
  cli: Record<string, number | null>;
  timestamp: string;
  data_source: string;
}

export interface EconomicEvent {
  event: string;
  country: string;
  date: string;
  impact: string;
  actual: string | null;
  estimate: string | null;
  previous: string | null;
}

export const getMacroOverview = () => request<MacroOverview>("/api/macro");
export const getEconomicCalendar = () =>
  request<EconomicEvent[]>("/api/macro/calendar");

// -- Data Source Monitoring --

export interface SourceProbeResult {
  connector_name: string;
  reachable: boolean;
  latency_ms: number;
  freshness_seconds: number | null;
  completeness_pct: number;
  error_rate_1h: number;
  rate_limit_pct: number;
  health_score: number;
  status: "ok" | "warn" | "err" | "unknown";
  categories: string[];
  tier: number;
  last_probed_at: string;
  detail: string;
  sample_ticker: string;
}

export const getSourcesStatus = (force = false) =>
  request<SourceProbeResult[]>(`/api/v3/sources/status${force ? "?force=true" : ""}`);

export const probeSource = (name: string) =>
  request<SourceProbeResult>(`/api/v3/sources/${name}/probe`);

export const getSourceHistory = (name: string, limit = 20) =>
  request<SourceProbeResult[]>(`/api/v3/sources/${name}/history?limit=${limit}`);

export interface SourceCoverageConnector {
  name: string;
  tier: number;
  status: "ok" | "warn" | "err" | "unknown";
  categories: string[];
  health_score: number;
}

export interface SourceCoverage {
  categories: string[];
  connectors: SourceCoverageConnector[];
}

export const getSourceCoverage = () =>
  request<SourceCoverage>("/api/v3/sources/coverage");
