"""Tests for the lightweight backtesting engine.

At least 20 tests covering engine, metrics, signal_cache, and report.
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import unittest

from tradingagents.backtest.engine import BacktestEngine
from tradingagents.backtest.metrics import BacktestMetrics
from tradingagents.backtest.signal_cache import SignalCache
from tradingagents.backtest.report import BacktestReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prices(
    ticker: str,
    bars: list[tuple],  # (date, open, high, low, close, volume)
) -> dict[str, list[dict]]:
    """Build prices dict for a single ticker."""
    return {
        ticker: [
            {
                "date": b[0],
                "open": b[1],
                "high": b[2],
                "low": b[3],
                "close": b[4],
                "volume": b[5],
            }
            for b in bars
        ]
    }


def _simple_prices() -> dict[str, list[dict]]:
    """5-day price series for AAPL."""
    return _make_prices(
        "AAPL",
        [
            ("2024-01-01", 100, 105, 99, 102, 1_000_000),
            ("2024-01-02", 102, 106, 101, 104, 1_000_000),
            ("2024-01-03", 104, 108, 103, 107, 1_000_000),
            ("2024-01-04", 107, 110, 106, 109, 1_000_000),
            ("2024-01-05", 109, 112, 108, 111, 1_000_000),
        ],
    )


# ===========================================================================
# Engine Tests
# ===========================================================================


class TestEngineBasic(unittest.TestCase):
    def setUp(self):
        self.engine = BacktestEngine(initial_capital=100_000, commission_pct=0.001)

    def test_buy_signal_opens_position_at_next_day_open(self):
        """BUY signal on day-0 should execute at day-1 open."""
        prices = _simple_prices()
        signals = [
            {
                "date": "2024-01-01",
                "ticker": "AAPL",
                "action": "BUY",
                "confidence": 0.9,
                "position_pct": 0.5,
            }
        ]
        result = self.engine.run(signals, prices)
        buy_trades = [t for t in result["trades"] if t["action"] == "BUY"]
        self.assertEqual(len(buy_trades), 1)
        # Executed at 2024-01-02 open = 102
        self.assertEqual(buy_trades[0]["date"], "2024-01-02")
        self.assertEqual(buy_trades[0]["price"], 102)

    def test_sell_signal_closes_position(self):
        """SELL after BUY should close the position."""
        prices = _simple_prices()
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "BUY", "confidence": 0.9, "position_pct": 0.5},
            {"date": "2024-01-03", "ticker": "AAPL", "action": "SELL", "confidence": 0.9, "position_pct": 0.0},
        ]
        result = self.engine.run(signals, prices)
        sell_trades = [t for t in result["trades"] if t["action"] == "SELL"]
        self.assertEqual(len(sell_trades), 1)
        # Executed at 2024-01-04 open = 107
        self.assertEqual(sell_trades[0]["date"], "2024-01-04")
        self.assertEqual(sell_trades[0]["price"], 107)

    def test_commission_deducted_on_buy(self):
        """Commission should reduce cash on BUY."""
        engine = BacktestEngine(initial_capital=100_000, commission_pct=0.01)  # 1%
        prices = _simple_prices()
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "BUY", "confidence": 1.0, "position_pct": 0.5},
        ]
        result = engine.run(signals, prices)
        buy = result["trades"][0]
        # commission = allocation * 0.01
        self.assertGreater(buy["commission"], 0)
        self.assertAlmostEqual(buy["commission"], buy["shares"] * buy["price"] * 0.01, places=2)

    def test_commission_deducted_on_sell(self):
        """Commission should reduce proceeds on SELL."""
        engine = BacktestEngine(initial_capital=100_000, commission_pct=0.01)
        prices = _simple_prices()
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "BUY", "confidence": 1.0, "position_pct": 0.5},
            {"date": "2024-01-02", "ticker": "AAPL", "action": "SELL", "confidence": 1.0, "position_pct": 0.0},
        ]
        result = engine.run(signals, prices)
        sell = [t for t in result["trades"] if t["action"] == "SELL"][0]
        self.assertGreater(sell["commission"], 0)

    def test_no_look_ahead_bias(self):
        """Signal on day d must NOT use day d prices for execution."""
        prices = _simple_prices()
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "BUY", "confidence": 0.9, "position_pct": 0.5},
        ]
        result = self.engine.run(signals, prices)
        buy = result["trades"][0]
        # Day 0 open=100, close=102.  Execution must be at day 1 open=102 not day 0 prices.
        self.assertNotEqual(buy["price"], 100)
        self.assertEqual(buy["price"], 102)

    def test_hold_signal_does_nothing(self):
        """HOLD should produce no trades."""
        prices = _simple_prices()
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "HOLD", "confidence": 0.5, "position_pct": 0.0},
        ]
        result = self.engine.run(signals, prices)
        self.assertEqual(len(result["trades"]), 0)

    def test_equity_curve_length_matches_dates(self):
        """Equity curve should have one value per trading day."""
        prices = _simple_prices()
        signals = []
        result = self.engine.run(signals, prices)
        self.assertEqual(len(result["equity_curve"]), 5)
        self.assertEqual(len(result["dates"]), 5)

    def test_no_signals_preserves_capital(self):
        """With no signals, final value should equal initial capital."""
        prices = _simple_prices()
        result = self.engine.run([], prices)
        self.assertAlmostEqual(result["final_value"], 100_000)

    def test_sell_without_position_ignored(self):
        """SELL when no position is held should be a no-op."""
        prices = _simple_prices()
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "SELL", "confidence": 1.0, "position_pct": 0.0},
        ]
        result = self.engine.run(signals, prices)
        self.assertEqual(len(result["trades"]), 0)

    def test_multiple_tickers(self):
        """Engine should handle signals across multiple tickers."""
        prices = _simple_prices()
        prices["MSFT"] = [
            {"date": "2024-01-01", "open": 200, "high": 210, "low": 198, "close": 205, "volume": 500000},
            {"date": "2024-01-02", "open": 205, "high": 215, "low": 203, "close": 210, "volume": 500000},
            {"date": "2024-01-03", "open": 210, "high": 220, "low": 208, "close": 215, "volume": 500000},
            {"date": "2024-01-04", "open": 215, "high": 225, "low": 213, "close": 220, "volume": 500000},
            {"date": "2024-01-05", "open": 220, "high": 230, "low": 218, "close": 225, "volume": 500000},
        ]
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "BUY", "confidence": 0.8, "position_pct": 0.25},
            {"date": "2024-01-01", "ticker": "MSFT", "action": "BUY", "confidence": 0.8, "position_pct": 0.25},
        ]
        result = self.engine.run(signals, prices)
        buy_trades = [t for t in result["trades"] if t["action"] == "BUY"]
        tickers = {t["ticker"] for t in buy_trades}
        self.assertEqual(tickers, {"AAPL", "MSFT"})

    def test_pnl_positive_on_winning_trade(self):
        """A buy-low sell-high round trip should show positive PnL."""
        prices = _simple_prices()
        signals = [
            {"date": "2024-01-01", "ticker": "AAPL", "action": "BUY", "confidence": 1.0, "position_pct": 0.5},
            {"date": "2024-01-03", "ticker": "AAPL", "action": "SELL", "confidence": 1.0, "position_pct": 0.0},
        ]
        result = self.engine.run(signals, prices)
        sell = [t for t in result["trades"] if t["action"] == "SELL"][0]
        self.assertGreater(sell["pnl"], 0)


# ===========================================================================
# Metrics Tests
# ===========================================================================


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.metrics = BacktestMetrics()

    def test_sharpe_known_curve(self):
        """Sharpe ratio for a steadily increasing curve should be positive."""
        # 252 days of +0.1% daily
        equity = [100_000]
        for _ in range(252):
            equity.append(equity[-1] * 1.001)
        result = self.metrics.compute(equity, [])
        self.assertGreater(result["sharpe_ratio"], 0)

    def test_win_rate_known_trades(self):
        """2 wins out of 3 trades -> 66.67% win rate."""
        trades = [
            {"action": "SELL", "pnl": 100},
            {"action": "SELL", "pnl": 200},
            {"action": "SELL", "pnl": -50},
        ]
        result = self.metrics.compute([100, 100], trades)
        self.assertAlmostEqual(result["win_rate"], 2 / 3, places=4)

    def test_profit_factor_known_trades(self):
        """gross_profit=300, gross_loss=50 -> profit_factor=6."""
        trades = [
            {"action": "SELL", "pnl": 100},
            {"action": "SELL", "pnl": 200},
            {"action": "SELL", "pnl": -50},
        ]
        result = self.metrics.compute([100, 100], trades)
        self.assertAlmostEqual(result["profit_factor"], 6.0, places=4)

    def test_max_drawdown_known_series(self):
        """Equity: 100, 110, 90, 95 -> drawdown from 110 to 90 = 18.18%."""
        equity = [100, 110, 90, 95]
        result = self.metrics.compute(equity, [])
        expected_dd = (110 - 90) / 110
        self.assertAlmostEqual(result["max_drawdown"], expected_dd, places=4)

    def test_max_drawdown_duration(self):
        """Drawdown from index 1 (peak=110) to recovery never -> duration = 2."""
        equity = [100, 110, 90, 95]
        result = self.metrics.compute(equity, [])
        # Peak at i=1, never recovers by i=3 -> duration = 3-1 = 2
        self.assertEqual(result["max_drawdown_duration"], 2)

    def test_sortino_uses_only_downside(self):
        """Sortino should differ from Sharpe when returns are skewed."""
        # All positive returns -> no downside -> sortino should be high
        equity = [100_000]
        for _ in range(100):
            equity.append(equity[-1] * 1.002)
        result = self.metrics.compute(equity, [])
        # With no negative returns, downside deviation is very small (only rf drag)
        # so sortino should be >= sharpe
        self.assertGreaterEqual(result["sortino_ratio"], result["sharpe_ratio"])

    def test_total_return_calculation(self):
        """100k -> 120k = 20% return."""
        equity = [100_000, 110_000, 120_000]
        result = self.metrics.compute(equity, [])
        self.assertAlmostEqual(result["total_return"], 0.2, places=4)

    def test_empty_equity_curve(self):
        """Single-element curve should return empty metrics."""
        result = self.metrics.compute([100], [])
        self.assertEqual(result["total_return"], 0.0)

    def test_expectancy(self):
        """Expectancy = avg_win * win_rate - avg_loss * (1-win_rate)."""
        trades = [
            {"action": "SELL", "pnl": 300},
            {"action": "SELL", "pnl": -100},
        ]
        result = self.metrics.compute([100, 100], trades)
        # win_rate=0.5, avg_win=300, avg_loss=100
        expected = 300 * 0.5 - 100 * 0.5
        self.assertAlmostEqual(result["expectancy"], expected, places=2)


# ===========================================================================
# Signal Cache Tests
# ===========================================================================


class TestSignalCache(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cache = SignalCache(cache_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_and_load(self):
        sig = {"action": "BUY", "confidence": 0.9}
        self.cache.save("AAPL", "2024-01-01", sig)
        loaded = self.cache.load("AAPL", "2024-01-01")
        self.assertEqual(loaded, sig)

    def test_has_returns_true_when_cached(self):
        self.cache.save("AAPL", "2024-01-01", {"action": "BUY"})
        self.assertTrue(self.cache.has("AAPL", "2024-01-01"))

    def test_has_returns_false_when_missing(self):
        self.assertFalse(self.cache.has("AAPL", "2024-01-01"))

    def test_load_returns_none_when_missing(self):
        self.assertIsNone(self.cache.load("AAPL", "2024-01-01"))

    def test_clear_removes_all(self):
        self.cache.save("AAPL", "2024-01-01", {"action": "BUY"})
        self.cache.save("MSFT", "2024-01-02", {"action": "SELL"})
        self.cache.clear()
        self.assertFalse(self.cache.has("AAPL", "2024-01-01"))
        self.assertFalse(self.cache.has("MSFT", "2024-01-02"))


# ===========================================================================
# Report Tests
# ===========================================================================


class TestReport(unittest.TestCase):
    def test_generates_valid_markdown(self):
        metrics = {
            "total_return": 0.15,
            "annual_return": 0.30,
            "sharpe_ratio": 1.5,
            "sortino_ratio": 2.0,
            "max_drawdown": 0.10,
            "max_drawdown_duration": 5,
            "win_rate": 0.6,
            "profit_factor": 2.5,
            "total_trades": 10,
            "avg_trade_return": 150.0,
            "expectancy": 100.0,
        }
        trades = [
            {"date": "2024-01-02", "ticker": "AAPL", "action": "BUY", "price": 102.0, "shares": 100, "commission": 10.2, "pnl": 0},
        ]
        equity = [100_000, 105_000, 115_000]
        report = BacktestReport()
        md = report.generate(metrics, equity, trades)
        self.assertIn("# Backtest Report", md)
        self.assertIn("## Performance Summary", md)
        self.assertIn("## Trade Log", md)
        self.assertIn("## Key Statistics", md)
        self.assertIn("15.00%", md)  # total return
        self.assertIn("AAPL", md)

    def test_report_with_no_trades(self):
        metrics = {
            "total_return": 0.0, "annual_return": 0.0, "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0, "max_drawdown": 0.0, "max_drawdown_duration": 0,
            "win_rate": 0.0, "profit_factor": 0.0, "total_trades": 0,
            "avg_trade_return": 0.0, "expectancy": 0.0,
        }
        report = BacktestReport()
        md = report.generate(metrics, [100_000], [])
        self.assertIn("# Backtest Report", md)


if __name__ == "__main__":
    unittest.main()
