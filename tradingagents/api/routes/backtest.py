"""Backtest routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.requests import BacktestRequest
from ..models.responses import BacktestResponse

router = APIRouter(prefix="/api", tags=["backtest"])


@router.post("/backtest", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest) -> BacktestResponse:
    """Run a backtest for the given ticker and date range.

    In production this fetches real signals + prices.  The stub returns
    empty metrics when no signal/price data is supplied.
    """
    from tradingagents.backtest.engine import BacktestEngine
    from tradingagents.backtest.metrics import BacktestMetrics

    engine = BacktestEngine(initial_capital=req.initial_capital)

    # Stub: run with no signals / prices to produce baseline metrics
    result = engine.run(signals=[], prices={})
    metrics = BacktestMetrics().compute(
        equity_curve=result["equity_curve"],
        trades=result["trades"],
    )

    return BacktestResponse(
        ticker=req.ticker,
        metrics=metrics,
        trades_count=len(result["trades"]),
    )
