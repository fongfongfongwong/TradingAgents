"""Response models for TradingAgents API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


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
