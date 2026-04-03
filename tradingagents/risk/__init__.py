"""Risk management framework for TradingAgents.

Provides position sizing, stop-loss rules, portfolio constraints,
and a validation gate that can block bad trades.
"""

from tradingagents.risk.position_sizing import (
    VolatilityTargetSizer,
    FractionalKellySizer,
)
from tradingagents.risk.stop_rules import (
    StopRule,
    TrailingStop,
    ATRStop,
    TimeStop,
    CompositeStop,
)
from tradingagents.risk.constraints import PortfolioConstraints
from tradingagents.risk.validation_gate import ValidationGate

__all__ = [
    "VolatilityTargetSizer",
    "FractionalKellySizer",
    "StopRule",
    "TrailingStop",
    "ATRStop",
    "TimeStop",
    "CompositeStop",
    "PortfolioConstraints",
    "ValidationGate",
]
