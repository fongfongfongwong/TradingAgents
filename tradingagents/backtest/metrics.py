"""Performance metrics for backtest results.

Uses only Python stdlib + math.
"""

from __future__ import annotations

import math
from typing import Any


class BacktestMetrics:
    """Computes standard trading performance metrics."""

    def compute(
        self,
        equity_curve: list[float],
        trades: list[dict],
        risk_free_rate: float = 0.05,
    ) -> dict:
        """Return a dict of performance metrics.

        Parameters
        ----------
        equity_curve:
            Daily portfolio values (length >= 2 for meaningful stats).
        trades:
            List of trade dicts from ``BacktestEngine.run``.
        risk_free_rate:
            Annualised risk-free rate for Sharpe / Sortino.
        """
        if len(equity_curve) < 2:
            return self._empty_metrics()

        daily_returns = self._daily_returns(equity_curve)
        n_days = len(daily_returns)

        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        annual_return = self._annualise_return(total_return, n_days)
        annual_vol = self._annual_volatility(daily_returns)
        downside_vol = self._downside_deviation(daily_returns, risk_free_rate)

        sharpe = (
            (annual_return - risk_free_rate) / annual_vol
            if annual_vol > 0
            else 0.0
        )
        if downside_vol > 0:
            sortino = (annual_return - risk_free_rate) / downside_vol
        elif annual_return > risk_free_rate:
            sortino = float("inf")
        else:
            sortino = 0.0

        max_dd, max_dd_duration = self._max_drawdown(equity_curve)

        # Trade-level metrics
        sell_trades = [t for t in trades if t["action"] == "SELL"]
        total_trades = len(sell_trades)
        wins = [t for t in sell_trades if t["pnl"] > 0]
        losses = [t for t in sell_trades if t["pnl"] <= 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0

        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else float("inf")
        )

        avg_trade_return = (
            sum(t["pnl"] for t in sell_trades) / total_trades
            if total_trades > 0
            else 0.0
        )

        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        expectancy = avg_win * win_rate - avg_loss * (1 - win_rate)

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_dd,
            "max_drawdown_duration": max_dd_duration,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_trades": total_trades,
            "avg_trade_return": avg_trade_return,
            "expectancy": expectancy,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _daily_returns(equity: list[float]) -> list[float]:
        return [
            (equity[i] - equity[i - 1]) / equity[i - 1]
            for i in range(1, len(equity))
            if equity[i - 1] != 0
        ]

    @staticmethod
    def _annualise_return(total_return: float, n_days: int) -> float:
        if n_days <= 0:
            return 0.0
        years = n_days / 252.0
        if years <= 0:
            return 0.0
        return (1 + total_return) ** (1 / years) - 1

    @staticmethod
    def _annual_volatility(daily_returns: list[float]) -> float:
        if len(daily_returns) < 2:
            return 0.0
        mean = sum(daily_returns) / len(daily_returns)
        var = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        return math.sqrt(var) * math.sqrt(252)

    @staticmethod
    def _downside_deviation(
        daily_returns: list[float], risk_free_rate: float
    ) -> float:
        daily_rf = risk_free_rate / 252.0
        downside = [min(r - daily_rf, 0) for r in daily_returns]
        if len(downside) < 2:
            return 0.0
        # Use N (not N-1) for downside deviation per convention
        var = sum(d ** 2 for d in downside) / len(downside)
        return math.sqrt(var) * math.sqrt(252)

    @staticmethod
    def _max_drawdown(equity: list[float]) -> tuple[float, int]:
        """Return (max_drawdown_fraction, duration_in_days)."""
        if not equity:
            return 0.0, 0
        peak = equity[0]
        max_dd = 0.0
        # Track drawdown duration
        dd_start = 0
        max_dd_dur = 0
        in_drawdown = False

        for i, val in enumerate(equity):
            if val >= peak:
                if in_drawdown:
                    dur = i - dd_start
                    if dur > max_dd_dur:
                        max_dd_dur = dur
                    in_drawdown = False
                peak = val
            else:
                if not in_drawdown:
                    dd_start = i - 1
                    in_drawdown = True
                dd = (peak - val) / peak
                if dd > max_dd:
                    max_dd = dd

        # If still in drawdown at end
        if in_drawdown:
            dur = len(equity) - 1 - dd_start
            if dur > max_dd_dur:
                max_dd_dur = dur

        return max_dd, max_dd_dur

    @staticmethod
    def _empty_metrics() -> dict:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_duration": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_trades": 0,
            "avg_trade_return": 0.0,
            "expectancy": 0.0,
        }
