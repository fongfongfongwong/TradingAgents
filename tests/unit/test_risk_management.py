"""Tests for tradingagents.risk — position sizing, stops, constraints, validation gate."""

from __future__ import annotations

import math
import unittest

from tradingagents.risk.position_sizing import (
    VolatilityTargetSizer,
    FractionalKellySizer,
)
from tradingagents.risk.stop_rules import (
    TrailingStop,
    ATRStop,
    TimeStop,
    CompositeStop,
)
from tradingagents.risk.constraints import PortfolioConstraints
from tradingagents.risk.validation_gate import ValidationGate


# ---------------------------------------------------------------------------
# VolatilityTargetSizer
# ---------------------------------------------------------------------------
class TestVolatilityTargetSizer(unittest.TestCase):
    def _make_returns(self, daily_std: float, n: int = 30) -> list[float]:
        """Deterministic returns with known standard deviation."""
        # Alternate +std and -std so mean ~ 0 and stdev ~ daily_std
        return [daily_std if i % 2 == 0 else -daily_std for i in range(n)]

    def test_high_vol_smaller_position(self):
        sizer = VolatilityTargetSizer(target_vol=0.15)
        high_vol_returns = self._make_returns(0.03, 30)  # ~47% annualised
        result = sizer.compute(100_000, 50.0, high_vol_returns)
        self.assertGreater(result["realized_vol"], 0.15)
        self.assertLess(result["position_pct"], 1.0)
        self.assertGreater(result["shares"], 0)

    def test_low_vol_larger_position(self):
        sizer = VolatilityTargetSizer(target_vol=0.15)
        low_vol_returns = self._make_returns(0.002, 30)  # ~3% annualised
        result = sizer.compute(100_000, 50.0, low_vol_returns)
        self.assertLess(result["realized_vol"], 0.15)
        # position_pct would exceed 1.0 but gets capped
        self.assertLessEqual(result["position_pct"], 1.0)

    def test_position_pct_capped_at_one(self):
        sizer = VolatilityTargetSizer(target_vol=0.50)
        tiny_vol_returns = self._make_returns(0.001, 30)
        result = sizer.compute(100_000, 50.0, tiny_vol_returns)
        self.assertEqual(result["position_pct"], 1.0)

    def test_insufficient_returns(self):
        sizer = VolatilityTargetSizer()
        result = sizer.compute(100_000, 50.0, [0.01])
        self.assertEqual(result["shares"], 0)
        self.assertEqual(result["position_pct"], 0.0)

    def test_zero_price(self):
        sizer = VolatilityTargetSizer()
        returns = self._make_returns(0.01, 30)
        result = sizer.compute(100_000, 0.0, returns)
        self.assertEqual(result["shares"], 0)

    def test_lookback_respected(self):
        sizer = VolatilityTargetSizer(lookback_days=5)
        # First 25 returns are calm, last 5 are wild
        calm = [0.001, -0.001] * 12 + [0.001]
        wild = [0.05, -0.05, 0.05, -0.05, 0.05]
        returns = calm + wild
        result = sizer.compute(100_000, 50.0, returns)
        # Realised vol should reflect wild tail, not calm head
        self.assertGreater(result["realized_vol"], 0.30)


# ---------------------------------------------------------------------------
# FractionalKellySizer
# ---------------------------------------------------------------------------
class TestFractionalKellySizer(unittest.TestCase):
    def test_good_win_rate(self):
        sizer = FractionalKellySizer(fraction=0.25)
        result = sizer.compute(
            100_000, 50.0, win_rate=0.6, avg_win=2.0, avg_loss=1.0, num_trades=100
        )
        self.assertTrue(result["sufficient_history"])
        self.assertGreater(result["kelly_fraction"], 0)
        self.assertGreater(result["shares"], 0)

    def test_bad_win_rate_zero_position(self):
        sizer = FractionalKellySizer(fraction=0.25)
        result = sizer.compute(
            100_000, 50.0, win_rate=0.3, avg_win=1.0, avg_loss=2.0, num_trades=100
        )
        # Kelly fraction should be <= 0, clamped to 0
        self.assertEqual(result["kelly_fraction"], 0.0)
        self.assertEqual(result["shares"], 0)

    def test_insufficient_history(self):
        sizer = FractionalKellySizer(fraction=0.25, min_trades=50)
        result = sizer.compute(
            100_000, 50.0, win_rate=0.6, avg_win=2.0, avg_loss=1.0, num_trades=10
        )
        self.assertFalse(result["sufficient_history"])
        self.assertEqual(result["shares"], 0)

    def test_fraction_scaling(self):
        sizer_quarter = FractionalKellySizer(fraction=0.25)
        sizer_half = FractionalKellySizer(fraction=0.50)
        r1 = sizer_quarter.compute(100_000, 50.0, 0.6, 2.0, 1.0, 100)
        r2 = sizer_half.compute(100_000, 50.0, 0.6, 2.0, 1.0, 100)
        self.assertGreater(r2["adjusted_fraction"], r1["adjusted_fraction"])

    def test_zero_avg_loss(self):
        sizer = FractionalKellySizer()
        result = sizer.compute(100_000, 50.0, 0.6, 2.0, 0.0, 100)
        self.assertEqual(result["shares"], 0)


# ---------------------------------------------------------------------------
# Stop Rules
# ---------------------------------------------------------------------------
class TestTrailingStop(unittest.TestCase):
    def test_triggers_on_drop(self):
        stop = TrailingStop(pct=0.10)
        result = stop.should_exit(90.0, 100.0, 105.0, 5)
        # drop = (105-90)/105 = 14.3%
        self.assertTrue(result["exit"])

    def test_no_trigger_small_drop(self):
        stop = TrailingStop(pct=0.10)
        result = stop.should_exit(96.0, 100.0, 100.0, 5)
        # drop = 4%
        self.assertFalse(result["exit"])

    def test_exact_threshold(self):
        stop = TrailingStop(pct=0.10)
        # drop exactly 10% from peak 100 -> 90
        result = stop.should_exit(90.0, 95.0, 100.0, 5)
        self.assertTrue(result["exit"])


class TestATRStop(unittest.TestCase):
    def test_triggers(self):
        stop = ATRStop(multiplier=2.0)
        # entry=100, ATR=3 => threshold=94. Price=93 -> exit
        result = stop.should_exit(93.0, 100.0, 105.0, 5, {"atr": 3.0})
        self.assertTrue(result["exit"])

    def test_no_trigger(self):
        stop = ATRStop(multiplier=2.0)
        result = stop.should_exit(97.0, 100.0, 105.0, 5, {"atr": 3.0})
        self.assertFalse(result["exit"])

    def test_no_atr_available(self):
        stop = ATRStop()
        result = stop.should_exit(90.0, 100.0, 105.0, 5, {})
        self.assertFalse(result["exit"])


class TestTimeStop(unittest.TestCase):
    def test_triggers(self):
        stop = TimeStop(max_days=30)
        result = stop.should_exit(100.0, 100.0, 100.0, 30)
        self.assertTrue(result["exit"])

    def test_no_trigger(self):
        stop = TimeStop(max_days=30)
        result = stop.should_exit(100.0, 100.0, 100.0, 15)
        self.assertFalse(result["exit"])


class TestCompositeStop(unittest.TestCase):
    def test_any_triggers(self):
        composite = CompositeStop([
            TrailingStop(pct=0.10),
            TimeStop(max_days=30),
        ])
        # Time stop triggers (35 > 30), trailing does not (price at peak)
        result = composite.should_exit(100.0, 95.0, 100.0, 35)
        self.assertTrue(result["exit"])
        self.assertIn("time_stop", result["reason"])

    def test_none_triggers(self):
        composite = CompositeStop([
            TrailingStop(pct=0.10),
            TimeStop(max_days=30),
        ])
        result = composite.should_exit(99.0, 95.0, 100.0, 5)
        self.assertFalse(result["exit"])


# ---------------------------------------------------------------------------
# PortfolioConstraints
# ---------------------------------------------------------------------------
class TestPortfolioConstraints(unittest.TestCase):
    def test_within_limits(self):
        pc = PortfolioConstraints()
        trade = {"ticker": "AAPL", "shares": 10, "price": 50.0, "sector": "tech"}
        portfolio = {
            "total_value": 100_000,
            "sector_exposures": {"tech": 0.05},
            "current_drawdown": 0.05,
        }
        result = pc.check(trade, portfolio)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["violations"], [])

    def test_position_too_large(self):
        pc = PortfolioConstraints(max_position_pct=0.10)
        trade = {"ticker": "AAPL", "shares": 300, "price": 50.0, "sector": "tech"}
        portfolio = {
            "total_value": 100_000,
            "sector_exposures": {"tech": 0.0},
            "current_drawdown": 0.0,
        }
        result = pc.check(trade, portfolio)
        self.assertFalse(result["allowed"])
        self.assertTrue(any("position" in v for v in result["violations"]))
        self.assertIsNotNone(result["adjusted_size"])

    def test_sector_overweight(self):
        pc = PortfolioConstraints(max_sector_pct=0.30)
        trade = {"ticker": "AAPL", "shares": 10, "price": 50.0, "sector": "tech"}
        portfolio = {
            "total_value": 100_000,
            "sector_exposures": {"tech": 0.28},
            "current_drawdown": 0.0,
        }
        # existing 28% + new 0.5% = 28.5% < 30% -> ok
        result = pc.check(trade, portfolio)
        self.assertTrue(result["allowed"])

    def test_sector_exceeds(self):
        pc = PortfolioConstraints(max_sector_pct=0.30)
        trade = {"ticker": "AAPL", "shares": 100, "price": 50.0, "sector": "tech"}
        portfolio = {
            "total_value": 100_000,
            "sector_exposures": {"tech": 0.28},
            "current_drawdown": 0.0,
        }
        # existing 28% + new 5% = 33% > 30%
        result = pc.check(trade, portfolio)
        self.assertFalse(result["allowed"])
        self.assertTrue(any("sector" in v for v in result["violations"]))

    def test_drawdown_exceeded(self):
        pc = PortfolioConstraints(max_drawdown=0.15)
        trade = {"ticker": "AAPL", "shares": 5, "price": 50.0, "sector": "tech"}
        portfolio = {
            "total_value": 100_000,
            "sector_exposures": {},
            "current_drawdown": 0.18,
        }
        result = pc.check(trade, portfolio)
        self.assertFalse(result["allowed"])
        self.assertTrue(any("drawdown" in v for v in result["violations"]))


# ---------------------------------------------------------------------------
# ValidationGate
# ---------------------------------------------------------------------------
class TestValidationGate(unittest.TestCase):
    def _base_proposal(self) -> dict:
        return {
            "ticker": "AAPL",
            "price": 150.0,
            "shares": 50,
            "portfolio_value": 500_000,
            "avg_volume": 500_000,
            "current_drawdown": 0.05,
            "estimated_commission": 5.0,
        }

    def test_all_pass(self):
        gate = ValidationGate()
        result = gate.validate(self._base_proposal())
        self.assertTrue(result["approved"])
        self.assertEqual(len(result["checks_failed"]), 0)
        self.assertEqual(len(result["checks_passed"]), 5)

    def test_sanity_fail_empty_ticker(self):
        gate = ValidationGate()
        p = self._base_proposal()
        p["ticker"] = ""
        result = gate.validate(p)
        self.assertFalse(result["approved"])
        self.assertTrue(any("sanity" in c for c in result["checks_failed"]))

    def test_sanity_fail_zero_price(self):
        gate = ValidationGate()
        p = self._base_proposal()
        p["price"] = 0
        result = gate.validate(p)
        self.assertFalse(result["approved"])
        self.assertTrue(any("sanity" in c for c in result["checks_failed"]))

    def test_liquidity_fail(self):
        gate = ValidationGate(min_avg_volume=100_000)
        p = self._base_proposal()
        p["avg_volume"] = 50_000
        result = gate.validate(p)
        self.assertFalse(result["approved"])
        self.assertTrue(any("liquidity" in c for c in result["checks_failed"]))

    def test_concentration_fail(self):
        gate = ValidationGate(max_position_pct=0.10)
        p = self._base_proposal()
        p["shares"] = 500  # 500*150 = 75K on 500K = 15%
        result = gate.validate(p)
        self.assertFalse(result["approved"])
        self.assertTrue(any("concentration" in c for c in result["checks_failed"]))
        self.assertIn("suggested_shares", result["adjustments"])

    def test_drawdown_fail(self):
        gate = ValidationGate(max_drawdown=0.15)
        p = self._base_proposal()
        p["current_drawdown"] = 0.20
        result = gate.validate(p)
        self.assertFalse(result["approved"])
        self.assertTrue(any("drawdown" in c for c in result["checks_failed"]))

    def test_cost_fail(self):
        gate = ValidationGate(max_commission_pct=0.01)
        p = self._base_proposal()
        p["estimated_commission"] = 100.0  # 100 / 7500 = 1.33%
        result = gate.validate(p)
        self.assertFalse(result["approved"])
        self.assertTrue(any("cost" in c for c in result["checks_failed"]))


if __name__ == "__main__":
    unittest.main()
