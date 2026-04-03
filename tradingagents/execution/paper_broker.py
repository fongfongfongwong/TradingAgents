"""Paper trading broker that simulates order execution with slippage and commission."""

import uuid
from datetime import datetime, timezone


class PaperBroker:
    """Simulated broker for paper trading with realistic slippage and commission."""

    def __init__(
        self,
        initial_capital: float = 100000,
        slippage_pct: float = 0.001,
        commission_pct: float = 0.001,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct
        # positions: {ticker: {"shares": int, "avg_cost": float}}
        self.positions: dict[str, dict] = {}
        # current market prices for P&L
        self.current_prices: dict[str, float] = {}
        # all executed trades
        self.trade_history: list[dict] = []

    def submit_order(self, ticker: str, action: str, shares: int, price: float) -> dict:
        """Submit a BUY or SELL order with simulated fill."""
        action = action.upper()
        if action not in ("BUY", "SELL"):
            raise ValueError(f"Invalid action: {action}. Must be 'BUY' or 'SELL'.")
        if shares <= 0:
            raise ValueError("Shares must be positive.")
        if price <= 0:
            raise ValueError("Price must be positive.")

        # Calculate fill price with slippage
        if action == "BUY":
            fill_price = price * (1 + self.slippage_pct)
        else:
            fill_price = price * (1 - self.slippage_pct)

        total_cost = fill_price * shares
        commission = total_cost * self.commission_pct

        if action == "BUY":
            required = total_cost + commission
            if required > self.cash:
                raise ValueError(
                    f"Insufficient cash. Required: {required:.2f}, Available: {self.cash:.2f}"
                )
            self.cash -= required
            # Update position
            if ticker in self.positions:
                pos = self.positions[ticker]
                old_total = pos["avg_cost"] * pos["shares"]
                new_total = old_total + total_cost
                pos["shares"] += shares
                pos["avg_cost"] = new_total / pos["shares"]
            else:
                self.positions[ticker] = {
                    "shares": shares,
                    "avg_cost": fill_price,
                }
            # Update current price
            self.current_prices[ticker] = price

        elif action == "SELL":
            if ticker not in self.positions or self.positions[ticker]["shares"] < shares:
                owned = self.positions.get(ticker, {}).get("shares", 0)
                raise ValueError(
                    f"Cannot sell {shares} shares of {ticker}. Only own {owned}."
                )
            self.cash += total_cost - commission
            pos = self.positions[ticker]
            pos["shares"] -= shares
            if pos["shares"] == 0:
                del self.positions[ticker]
            # Update current price
            self.current_prices[ticker] = price

        order_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(timezone.utc).isoformat()

        trade = {
            "order_id": order_id,
            "status": "filled",
            "ticker": ticker,
            "action": action,
            "fill_price": round(fill_price, 6),
            "shares": shares,
            "commission": round(commission, 6),
            "timestamp": timestamp,
        }
        self.trade_history.append(trade)
        return trade

    def get_position(self, ticker: str) -> dict:
        """Get current position for a ticker."""
        if ticker not in self.positions:
            return {
                "ticker": ticker,
                "shares": 0,
                "avg_cost": 0.0,
                "current_value": 0.0,
                "unrealized_pnl": 0.0,
            }
        pos = self.positions[ticker]
        current_price = self.current_prices.get(ticker, pos["avg_cost"])
        current_value = pos["shares"] * current_price
        cost_basis = pos["shares"] * pos["avg_cost"]
        return {
            "ticker": ticker,
            "shares": pos["shares"],
            "avg_cost": round(pos["avg_cost"], 6),
            "current_value": round(current_value, 2),
            "unrealized_pnl": round(current_value - cost_basis, 2),
        }

    def get_portfolio(self) -> dict:
        """Get full portfolio summary."""
        positions = {}
        total_position_value = 0.0
        total_unrealized_pnl = 0.0
        for ticker in self.positions:
            pos = self.get_position(ticker)
            positions[ticker] = pos
            total_position_value += pos["current_value"]
            total_unrealized_pnl += pos["unrealized_pnl"]
        return {
            "cash": round(self.cash, 2),
            "positions": positions,
            "total_value": round(self.cash + total_position_value, 2),
            "unrealized_pnl": round(total_unrealized_pnl, 2),
        }

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update current market prices for P&L calculation."""
        self.current_prices.update(prices)

    def close_position(self, ticker: str, price: float) -> dict:
        """Close an entire position at the given price."""
        if ticker not in self.positions:
            raise ValueError(f"No position in {ticker} to close.")
        shares = self.positions[ticker]["shares"]
        return self.submit_order(ticker, "SELL", shares, price)

    def get_trade_history(self) -> list[dict]:
        """Return all executed trades."""
        return list(self.trade_history)
