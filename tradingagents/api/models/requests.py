"""Request models for TradingAgents API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request body for POST /api/analyze."""

    ticker: str
    trade_date: str
    selected_analysts: list[str] = Field(
        default=["market", "news", "fundamentals", "divergence"],
    )
    debate_rounds: int = 1


class BacktestRequest(BaseModel):
    """Request body for POST /api/backtest."""

    ticker: str
    start_date: str
    end_date: str
    initial_capital: float = 100_000.0


class DivergenceRequest(BaseModel):
    """Request body for divergence analysis."""

    ticker: str
