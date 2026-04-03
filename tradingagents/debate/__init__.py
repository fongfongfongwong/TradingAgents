"""Structured Debate + Bayesian Aggregation system for TradingAgents."""

from tradingagents.debate.structured_round import (
    StructuredArgument,
    parse_structured_argument,
)
from tradingagents.debate.bayesian_aggregator import (
    BrierScore,
    BayesianAggregator,
)

__all__ = [
    "StructuredArgument",
    "parse_structured_argument",
    "BrierScore",
    "BayesianAggregator",
]
