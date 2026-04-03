"""Divergence analysis routes."""

from __future__ import annotations

from fastapi import APIRouter

from ..models.responses import DivergenceResponse

router = APIRouter(prefix="/api", tags=["divergence"])


@router.get("/divergence/{ticker}", response_model=DivergenceResponse)
async def get_divergence(ticker: str) -> DivergenceResponse:
    """Compute divergence score for a ticker."""
    from tradingagents.divergence.aggregator import DivergenceAggregator

    aggregator = DivergenceAggregator()
    result = aggregator.compute(ticker)

    return DivergenceResponse(
        ticker=result["ticker"],
        regime=result["regime"],
        composite_score=result["composite_score"],
        dimensions=result["dimensions"],
        timestamp=result["timestamp"],
    )
