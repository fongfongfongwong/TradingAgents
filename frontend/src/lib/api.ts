const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/* ------------------------------------------------------------------ */
/*  Shared types                                                       */
/* ------------------------------------------------------------------ */

export interface AnalysisRequest {
  ticker: string;
  analyst_model?: string;
  trader_model?: string;
  num_steps?: number;
}

export interface AnalysisStatus {
  id: string;
  ticker: string;
  status: "pending" | "running" | "completed" | "failed";
  created_at: string;
  completed_at: string | null;
  result: AnalysisResult | null;
  error: string | null;
}

export interface AnalysisResult {
  decision: string;
  confidence: number;
  reasoning: string;
  agent_reports: AgentReport[];
  divergence_data: DivergenceData | null;
}

export interface AgentReport {
  agent_name: string;
  role: string;
  signal: string;
  confidence: number;
  summary: string;
}

export interface DivergenceData {
  ticker: string;
  dimensions: DivergenceDimension[];
  overall_score: number;
}

export interface DivergenceDimension {
  name: string;
  bull_score: number;
  bear_score: number;
  divergence: number;
}

export interface BacktestRequest {
  ticker: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
}

export interface BacktestResult {
  id: string;
  ticker: string;
  start_date: string;
  end_date: string;
  total_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  trades: BacktestTrade[];
}

export interface BacktestTrade {
  date: string;
  action: "buy" | "sell";
  price: number;
  shares: number;
  pnl: number;
}

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

export interface SystemStats {
  analyses_today: number;
  analyses_total: number;
  active_agents: number;
  avg_confidence: number;
  uptime_hours: number;
}

/* ------------------------------------------------------------------ */
/*  HTTP helpers                                                       */
/* ------------------------------------------------------------------ */

class ApiError extends Error {
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

/** Dashboard stats */
export function getStats(): Promise<SystemStats> {
  return request<SystemStats>("/api/stats");
}

/** List recent analyses */
export function listAnalyses(limit = 20): Promise<AnalysisStatus[]> {
  return request<AnalysisStatus[]>(`/api/analyses?limit=${limit}`);
}

/** Start a new analysis */
export function startAnalysis(body: AnalysisRequest): Promise<{ id: string }> {
  return request<{ id: string }>("/api/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Get analysis by id */
export function getAnalysis(id: string): Promise<AnalysisStatus> {
  return request<AnalysisStatus>(`/api/analyze/${id}`);
}

/** Divergence data for a ticker */
export function getDivergence(ticker: string): Promise<DivergenceData> {
  return request<DivergenceData>(`/api/divergence/${ticker}`);
}

/** Run backtest */
export function runBacktest(body: BacktestRequest): Promise<BacktestResult> {
  return request<BacktestResult>("/api/backtest", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Portfolio */
export function getPortfolio(): Promise<PortfolioSummary> {
  return request<PortfolioSummary>("/api/portfolio");
}

/** SSE stream URL for a running analysis */
export function streamUrl(analysisId: string): string {
  return `${BASE_URL}/api/analyze/${analysisId}/stream`;
}
