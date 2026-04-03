"""Trade journal for recording, querying, and persisting trade history."""

import csv
import io
import json
import os
from datetime import datetime


class TradeJournal:
    """Persistent trade journal with filtering, summary, and export capabilities."""

    def __init__(self, journal_path: str = "./data/trade_journal.json"):
        self.journal_path = journal_path
        self.trades: list[dict] = []

    def record(self, trade: dict) -> None:
        """Append a trade to the journal."""
        self.trades.append(trade)

    def get_trades(
        self,
        ticker: str | None = None,
        start_date: str | None = None,
    ) -> list[dict]:
        """Get trades optionally filtered by ticker and/or start date."""
        result = self.trades
        if ticker is not None:
            result = [t for t in result if t.get("ticker") == ticker]
        if start_date is not None:
            result = [
                t for t in result
                if t.get("timestamp", "") >= start_date
            ]
        return result

    def summary(self) -> dict:
        """Calculate trade summary statistics."""
        total_trades = len(self.trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "by_ticker": {},
            }

        # Group trades by ticker and compute realized P&L per round-trip
        by_ticker: dict[str, dict] = {}
        # Track open cost basis per ticker for P&L calculation
        cost_basis: dict[str, list[float]] = {}  # FIFO queue of fill prices

        for trade in self.trades:
            ticker_name = trade.get("ticker", "UNKNOWN")
            action = trade.get("action", "")
            fill_price = trade.get("fill_price", 0.0)
            shares = trade.get("shares", 0)
            commission = trade.get("commission", 0.0)

            if ticker_name not in by_ticker:
                by_ticker[ticker_name] = {"trades": 0, "pnl": 0.0, "wins": 0}
            if ticker_name not in cost_basis:
                cost_basis[ticker_name] = []

            by_ticker[ticker_name]["trades"] += 1

            if action == "BUY":
                # Record cost basis entries
                for _ in range(shares):
                    cost_basis[ticker_name].append(fill_price)
                # Commission is a cost
                by_ticker[ticker_name]["pnl"] -= commission
            elif action == "SELL":
                # Match against FIFO cost basis
                for _ in range(shares):
                    if cost_basis[ticker_name]:
                        buy_price = cost_basis[ticker_name].pop(0)
                        by_ticker[ticker_name]["pnl"] += fill_price - buy_price
                # Commission is a cost
                by_ticker[ticker_name]["pnl"] -= commission

        total_pnl = sum(info["pnl"] for info in by_ticker.values())

        # Win rate: count tickers with positive P&L
        tickers_with_sells = [
            t for t in by_ticker
            if any(
                tr.get("action") == "SELL" and tr.get("ticker") == t
                for tr in self.trades
            )
        ]
        wins = sum(1 for t in tickers_with_sells if by_ticker[t]["pnl"] > 0)
        win_rate = wins / len(tickers_with_sells) if tickers_with_sells else 0.0

        # Round values for clean output
        by_ticker_summary = {}
        for t, info in by_ticker.items():
            by_ticker_summary[t] = {
                "trades": info["trades"],
                "pnl": round(info["pnl"], 2),
            }

        return {
            "total_trades": total_trades,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "by_ticker": by_ticker_summary,
        }

    def export_csv(self) -> str:
        """Export all trades as a CSV string."""
        if not self.trades:
            return ""
        output = io.StringIO()
        # Use keys from the first trade as fieldnames
        fieldnames = list(self.trades[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for trade in self.trades:
            writer.writerow(trade)
        return output.getvalue()

    def save(self) -> None:
        """Persist journal to JSON file."""
        directory = os.path.dirname(self.journal_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.journal_path, "w") as f:
            json.dump(self.trades, f, indent=2)

    def load(self) -> None:
        """Load journal from JSON file."""
        if os.path.exists(self.journal_path):
            with open(self.journal_path, "r") as f:
                self.trades = json.load(f)
