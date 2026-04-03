"""Unit tests for Institutional and Options divergence dimensions."""

from __future__ import annotations

import pytest

from tradingagents.divergence.dimensions.institutional import InstitutionalDimension
from tradingagents.divergence.dimensions.options import OptionsDimension


# =====================================================================
# Institutional Dimension
# =====================================================================


class TestAnalystConsensus:
    """Tests for analyst-rating consensus scoring."""

    def setup_method(self) -> None:
        self.dim = InstitutionalDimension()

    def test_all_strong_buy(self) -> None:
        data = {"strong_buy": 10, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0}
        result = self.dim.compute("AAPL", analyst_data=data)
        assert result["value"] == pytest.approx(1.0)

    def test_all_strong_sell(self) -> None:
        data = {"strong_buy": 0, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 10}
        result = self.dim.compute("AAPL", analyst_data=data)
        assert result["value"] == pytest.approx(-1.0)

    def test_all_buy(self) -> None:
        data = {"strong_buy": 0, "buy": 10, "hold": 0, "sell": 0, "strong_sell": 0}
        result = self.dim.compute("AAPL", analyst_data=data)
        assert result["value"] == pytest.approx(0.5)

    def test_mixed_balanced(self) -> None:
        data = {"strong_buy": 5, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 5}
        result = self.dim.compute("AAPL", analyst_data=data)
        assert result["value"] == pytest.approx(0.0)

    def test_mostly_hold(self) -> None:
        data = {"strong_buy": 0, "buy": 0, "hold": 20, "sell": 0, "strong_sell": 0}
        result = self.dim.compute("AAPL", analyst_data=data)
        assert result["value"] == pytest.approx(0.0)


class TestInsiderTransactions:
    """Tests for insider net-buying scoring."""

    def setup_method(self) -> None:
        self.dim = InstitutionalDimension()

    def test_net_buying(self) -> None:
        data = {"net_buying": 500_000, "total_volume": 1_000_000}
        result = self.dim.compute("AAPL", insider_data=data)
        assert result["value"] == pytest.approx(0.5)
        assert result["confidence"] == 0.4  # insider-only

    def test_net_selling(self) -> None:
        data = {"net_buying": -1_000_000, "total_volume": 1_000_000}
        result = self.dim.compute("AAPL", insider_data=data)
        assert result["value"] == pytest.approx(-1.0)


class TestInstitutionalCombined:
    """Tests for combined analyst + insider computation."""

    def setup_method(self) -> None:
        self.dim = InstitutionalDimension()

    def test_both_sources(self) -> None:
        analyst = {"strong_buy": 10, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0}
        insider = {"net_buying": 1_000_000, "total_volume": 1_000_000}
        result = self.dim.compute("AAPL", analyst_data=analyst, insider_data=insider)
        # analyst = 1.0, insider = 1.0 => combined = 1.0
        assert result["value"] == pytest.approx(1.0)
        assert result["confidence"] == 0.9
        assert "analyst_ratings" in result["sources"]
        assert "insider_transactions" in result["sources"]

    def test_conflicting_signals(self) -> None:
        analyst = {"strong_buy": 10, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0}
        insider = {"net_buying": -1_000_000, "total_volume": 1_000_000}
        result = self.dim.compute("AAPL", analyst_data=analyst, insider_data=insider)
        # analyst = 1.0 * 0.6 + insider = -1.0 * 0.4 => 0.2
        assert result["value"] == pytest.approx(0.2)

    def test_analyst_only_reduced_confidence(self) -> None:
        analyst = {"strong_buy": 5, "buy": 5, "hold": 0, "sell": 0, "strong_sell": 0}
        result = self.dim.compute("AAPL", analyst_data=analyst)
        assert result["confidence"] == 0.5

    def test_no_data(self) -> None:
        result = self.dim.compute("AAPL")
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0
        assert result["sources"] == []


class TestInstitutionalEdgeCases:
    """Edge-case tests for InstitutionalDimension."""

    def setup_method(self) -> None:
        self.dim = InstitutionalDimension()

    def test_zero_ratings(self) -> None:
        data = {"strong_buy": 0, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0}
        result = self.dim.compute("AAPL", analyst_data=data)
        # All zero => analyst score is None => falls to no-data path
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0

    def test_empty_analyst_dict(self) -> None:
        result = self.dim.compute("AAPL", analyst_data={})
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0

    def test_insider_zero_net(self) -> None:
        data = {"net_buying": 0, "total_volume": 100_000}
        result = self.dim.compute("AAPL", insider_data=data)
        assert result["value"] == pytest.approx(0.0)


# =====================================================================
# Options Dimension
# =====================================================================


class TestPutCallRatio:
    """Tests for put/call ratio scoring."""

    def setup_method(self) -> None:
        self.dim = OptionsDimension()

    def test_high_ratio_bearish(self) -> None:
        result = self.dim.compute("SPY", put_call_data={"ratio": 1.5})
        assert result["value"] == pytest.approx(-1.0)

    def test_low_ratio_bullish(self) -> None:
        result = self.dim.compute("SPY", put_call_data={"ratio": 0.5})
        assert result["value"] == pytest.approx(1.0)

    def test_mid_ratio(self) -> None:
        result = self.dim.compute("SPY", put_call_data={"ratio": 0.85})
        # 0.85 is midpoint of [0.7, 1.0] => score should be 0.0
        assert result["value"] == pytest.approx(0.0)

    def test_ratio_at_boundary_1(self) -> None:
        result = self.dim.compute("SPY", put_call_data={"ratio": 1.0})
        assert result["value"] == pytest.approx(-1.0)

    def test_ratio_at_boundary_07(self) -> None:
        result = self.dim.compute("SPY", put_call_data={"ratio": 0.7})
        assert result["value"] == pytest.approx(1.0)


class TestVixLevel:
    """Tests for VIX level scoring."""

    def setup_method(self) -> None:
        self.dim = OptionsDimension()

    def test_high_vix_fear(self) -> None:
        result = self.dim.compute("SPY", vix_data={"level": 40})
        assert result["value"] == pytest.approx(-1.0)

    def test_low_vix_complacency(self) -> None:
        result = self.dim.compute("SPY", vix_data={"level": 10})
        assert result["value"] == pytest.approx(1.0)

    def test_mid_vix(self) -> None:
        result = self.dim.compute("SPY", vix_data={"level": 22.5})
        # midpoint of [15, 30] => 0.0
        assert result["value"] == pytest.approx(0.0)


class TestOptionsCombined:
    """Tests for combined put/call + VIX computation."""

    def setup_method(self) -> None:
        self.dim = OptionsDimension()

    def test_both_bearish(self) -> None:
        result = self.dim.compute(
            "SPY",
            put_call_data={"ratio": 1.2},
            vix_data={"level": 35},
        )
        assert result["value"] == pytest.approx(-1.0)
        assert result["confidence"] == 0.9

    def test_both_bullish(self) -> None:
        result = self.dim.compute(
            "SPY",
            put_call_data={"ratio": 0.5},
            vix_data={"level": 10},
        )
        assert result["value"] == pytest.approx(1.0)

    def test_no_data(self) -> None:
        result = self.dim.compute("SPY")
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0
        assert result["sources"] == []

    def test_missing_ratio_key(self) -> None:
        result = self.dim.compute("SPY", put_call_data={})
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0
