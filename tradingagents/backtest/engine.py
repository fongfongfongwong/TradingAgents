"""Lightweight backtest execution engine.

Simulates trading with next-day-open execution to avoid look-ahead bias.
Uses only Python stdlib.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Position:
    ticker: str
    shares: float
    entry_price: float
    entry_date: str


class BacktestEngine:
    """Event-driven backtester that processes signals against historical prices.

    Execution model:
        - A signal on date *d* is executed at the **open** of date *d+1*.
        - BUY allocates ``position_pct`` of current portfolio value.
        - SELL liquidates the full position in the given ticker.
        - HOLD is a no-op.
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        commission_pct: float = 0.001,
    ) -> None:
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        signals: list[dict],
        prices: dict[str, list[dict]],
    ) -> dict:
        """Run a full backtest.

        Parameters
        ----------
        signals:
            List of signal dicts, each with keys:
            ``date``, ``ticker``, ``action``, ``confidence``, ``position_pct``.
        prices:
            Mapping of ticker -> list of OHLCV bar dicts sorted by date.
            Each bar: ``date``, ``open``, ``high``, ``low``, ``close``, ``volume``.

        Returns
        -------
        dict with keys: ``equity_curve``, ``trades``, ``positions``, ``final_value``,
        ``initial_capital``, ``dates``.
        """
        # Build fast date -> bar lookup per ticker
        price_index: dict[str, dict[str, dict]] = {}
        date_lists: dict[str, list[str]] = {}
        for ticker, bars in prices.items():
            idx: dict[str, dict] = {}
            dates: list[str] = []
            for bar in bars:
                idx[bar["date"]] = bar
                dates.append(bar["date"])
            price_index[ticker] = idx
            date_lists[ticker] = dates

        # Build signal lookup: (date, ticker) -> signal
        signal_map: dict[tuple[str, str], dict] = {}
        for sig in signals:
            key = (sig["date"], sig["ticker"])
            signal_map[key] = sig

        # Collect all unique dates across all tickers, sorted
        all_dates = sorted({d for dates in date_lists.values() for d in dates})

        # State
        cash: float = self.initial_capital
        positions: dict[str, _Position] = {}  # ticker -> Position
        trades: list[dict] = []
        equity_curve: list[float] = []
        equity_dates: list[str] = []

        # Pending orders to execute at next open
        pending_orders: list[dict] = []

        for i, date in enumerate(all_dates):
            # ----- Execute pending orders at today's open -----
            new_pending: list[dict] = []
            for order in pending_orders:
                ticker = order["ticker"]
                bar = price_index.get(ticker, {}).get(date)
                if bar is None:
                    # No price data for this date; carry order forward
                    new_pending.append(order)
                    continue
                exec_price = bar["open"]

                if order["action"] == "BUY":
                    # Determine allocation based on portfolio value at execution
                    portfolio_value = cash + self._positions_value(
                        positions, price_index, date, use_open=True
                    )
                    alloc = portfolio_value * order["position_pct"]
                    shares = alloc / exec_price
                    commission = alloc * self.commission_pct
                    cost = alloc + commission
                    if cost > cash or shares <= 0:
                        continue  # skip if insufficient funds
                    cash -= cost
                    if ticker in positions:
                        # Average into existing position
                        pos = positions[ticker]
                        total_shares = pos.shares + shares
                        pos.entry_price = (
                            (pos.entry_price * pos.shares + exec_price * shares)
                            / total_shares
                        )
                        pos.shares = total_shares
                    else:
                        positions[ticker] = _Position(
                            ticker=ticker,
                            shares=shares,
                            entry_price=exec_price,
                            entry_date=date,
                        )
                    trades.append(
                        {
                            "date": date,
                            "ticker": ticker,
                            "action": "BUY",
                            "price": exec_price,
                            "shares": shares,
                            "commission": commission,
                            "pnl": 0.0,
                            "signal_date": order["signal_date"],
                        }
                    )

                elif order["action"] == "SELL":
                    if ticker not in positions:
                        continue
                    pos = positions.pop(ticker)
                    proceeds = pos.shares * exec_price
                    commission = proceeds * self.commission_pct
                    cash += proceeds - commission
                    pnl = (exec_price - pos.entry_price) * pos.shares - commission
                    trades.append(
                        {
                            "date": date,
                            "ticker": ticker,
                            "action": "SELL",
                            "price": exec_price,
                            "shares": pos.shares,
                            "commission": commission,
                            "pnl": pnl,
                            "signal_date": order["signal_date"],
                        }
                    )
            pending_orders = new_pending

            # ----- Record equity (using close prices) -----
            port_value = cash + self._positions_value(
                positions, price_index, date, use_open=False
            )
            equity_curve.append(port_value)
            equity_dates.append(date)

            # ----- Queue new orders from today's signals -----
            for ticker in prices:
                sig = signal_map.get((date, ticker))
                if sig is None:
                    continue
                action = sig["action"].upper()
                if action == "HOLD":
                    continue
                pending_orders.append(
                    {
                        "ticker": ticker,
                        "action": action,
                        "position_pct": sig.get("position_pct", 0.0),
                        "confidence": sig.get("confidence", 1.0),
                        "signal_date": date,
                    }
                )

        # Final positions snapshot
        final_positions = {
            t: {
                "shares": p.shares,
                "entry_price": p.entry_price,
                "entry_date": p.entry_date,
            }
            for t, p in positions.items()
        }

        return {
            "equity_curve": equity_curve,
            "dates": equity_dates,
            "trades": trades,
            "positions": final_positions,
            "final_value": equity_curve[-1] if equity_curve else self.initial_capital,
            "initial_capital": self.initial_capital,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _positions_value(
        positions: dict[str, _Position],
        price_index: dict[str, dict[str, dict]],
        date: str,
        *,
        use_open: bool = False,
    ) -> float:
        """Mark-to-market value of all open positions."""
        total = 0.0
        price_field = "open" if use_open else "close"
        for ticker, pos in positions.items():
            bar = price_index.get(ticker, {}).get(date)
            if bar is not None:
                total += pos.shares * bar[price_field]
            else:
                # Fall back to entry price if no bar available
                total += pos.shares * pos.entry_price
        return total
