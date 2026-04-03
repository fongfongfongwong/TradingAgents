"""Position sizing algorithms: volatility targeting and fractional Kelly."""

from __future__ import annotations

import math
from statistics import stdev


class VolatilityTargetSizer:
    """Size positions so the portfolio targets a specific annualised volatility."""

    def __init__(self, target_vol: float = 0.15, lookback_days: int = 20) -> None:
        self.target_vol = target_vol
        self.lookback_days = lookback_days

    def compute(
        self,
        portfolio_value: float,
        price: float,
        daily_returns: list[float],
    ) -> dict:
        """Return position size driven by realised vs target volatility.

        Returns
        -------
        dict with keys: shares, position_pct, realized_vol, target_vol
        """
        if len(daily_returns) < 2:
            return {
                "shares": 0,
                "position_pct": 0.0,
                "realized_vol": 0.0,
                "target_vol": self.target_vol,
            }

        # Use only the most recent *lookback_days* returns
        recent = daily_returns[-self.lookback_days :]
        realized_vol = stdev(recent) * math.sqrt(252)

        if realized_vol == 0:
            position_pct = 1.0
        else:
            position_pct = self.target_vol / realized_vol

        # Cap at 100 %
        position_pct = min(position_pct, 1.0)

        dollar_alloc = portfolio_value * position_pct
        shares = int(dollar_alloc // price) if price > 0 else 0

        return {
            "shares": shares,
            "position_pct": round(position_pct, 6),
            "realized_vol": round(realized_vol, 6),
            "target_vol": self.target_vol,
        }


class FractionalKellySizer:
    """Size positions using a fractional Kelly criterion."""

    def __init__(self, fraction: float = 0.25, min_trades: int = 50) -> None:
        self.fraction = fraction
        self.min_trades = min_trades

    def compute(
        self,
        portfolio_value: float,
        price: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        num_trades: int | None = None,
    ) -> dict:
        """Return position size based on Kelly criterion.

        Parameters
        ----------
        win_rate : float  – probability of a winning trade (0-1)
        avg_win  : float  – average gain on winning trades (positive)
        avg_loss : float  – average loss on losing trades (positive magnitude)
        num_trades : int | None – trade count for sufficiency check

        Returns
        -------
        dict with keys: shares, kelly_fraction, adjusted_fraction, sufficient_history
        """
        sufficient = True
        if num_trades is not None and num_trades < self.min_trades:
            sufficient = False

        if not sufficient or avg_loss <= 0 or avg_win <= 0:
            return {
                "shares": 0,
                "kelly_fraction": 0.0,
                "adjusted_fraction": 0.0,
                "sufficient_history": sufficient,
            }

        # Kelly formula: f* = p - q / (W/L)
        win_loss_ratio = avg_win / avg_loss
        kelly_f = win_rate - (1 - win_rate) / win_loss_ratio

        # Clamp to [0, 1] before applying fraction
        kelly_f = max(kelly_f, 0.0)
        adjusted = kelly_f * self.fraction
        adjusted = min(adjusted, 1.0)

        dollar_alloc = portfolio_value * adjusted
        shares = int(dollar_alloc // price) if price > 0 else 0

        return {
            "shares": shares,
            "kelly_fraction": round(kelly_f, 6),
            "adjusted_fraction": round(adjusted, 6),
            "sufficient_history": sufficient,
        }
