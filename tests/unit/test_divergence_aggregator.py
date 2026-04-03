"""Tests for DivergenceAggregator."""

import pytest

from tradingagents.divergence.aggregator import DivergenceAggregator


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _full_raw_data(
    regime_vix=15.0, regime_breadth=0.7, regime_pc=0.5,
):
    """Build a full 5-dimension raw_data dict matching actual dimension APIs."""
    return {
        "institutional": {
            "analyst": {"strong_buy": 10, "buy": 5, "hold": 3, "sell": 1, "strong_sell": 0},
            "insider": {"net_buying": 0.6, "total_volume": 1.0},
        },
        "options": {
            "put_call": {"ratio": 0.7},
            "vix": {"level": 15.0},
        },
        # PriceActionDimension.compute(ticker, price_data=...)
        "price_action": {
            "current_price": 180.0,
            "sma_50": 170.0,
            "sma_200": 160.0,
            "rsi_14": 55.0,
        },
        # NewsDimension.compute(ticker, sentiment_data=...)
        "news": {
            "bullish_percent": 0.65,
            "bearish_percent": 0.20,
            "company_news_score": 0.4,
            "articles_in_last_week": 25,
        },
        # RetailDimension.compute(ticker, social_data=..., fear_greed=...)
        "retail": {
            "social": {"mentions": 300, "mentions_24h_ago": 200},
            "fear_greed": {"value": 40, "aaii_bull_bear_spread": 10},
        },
        "regime": {"vix": regime_vix, "breadth": regime_breadth, "put_call_ratio": regime_pc},
    }


def _risk_on_data():
    return _full_raw_data(regime_vix=15.0, regime_breadth=0.7, regime_pc=0.5)


def _risk_off_data():
    return _full_raw_data(regime_vix=35.0, regime_breadth=0.3, regime_pc=1.2)


def _transitioning_data():
    return _full_raw_data(regime_vix=25.0, regime_breadth=0.5, regime_pc=0.85)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComputeFullData:
    """Test compute with full 5-dimension data."""

    def test_returns_all_keys(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert "ticker" in result
        assert "timestamp" in result
        assert "regime" in result
        assert "dimensions" in result
        assert "composite_score" in result
        assert "weights" in result
        assert "confidence" in result
        assert "dimensions_available" in result
        assert "agent_summary" in result

    def test_ticker_preserved(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert result["ticker"] == "AAPL"

    def test_five_dimensions_available(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert result["dimensions_available"] == 5
        assert len(result["dimensions"]) == 5

    def test_composite_in_valid_range(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert -1.0 <= result["composite_score"] <= 1.0

    def test_confidence_positive_with_full_data(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert result["confidence"] > 0

class TestMissingDimensions:
    """Test compute with missing dimensions."""

    def test_partial_data_reduces_available_count(self):
        agg = DivergenceAggregator()
        data = {
            "institutional": {
                "analyst": {"strong_buy": 10, "buy": 5, "hold": 3, "sell": 1, "strong_sell": 0},
            },
            "options": {
                "put_call": {"ratio": 0.7},
            },
            "regime": {"vix": 15.0},
        }
        result = agg.compute("AAPL", raw_data=data)
        assert result["dimensions_available"] < 5
        assert result["dimensions_available"] >= 2

    def test_partial_data_reduces_confidence(self):
        agg = DivergenceAggregator()
        full = agg.compute("AAPL", raw_data=_risk_on_data())
        partial_data = {
            "institutional": {
                "analyst": {"strong_buy": 10, "buy": 5, "hold": 3, "sell": 1, "strong_sell": 0},
            },
            "regime": {"vix": 15.0},
        }
        partial = agg.compute("AAPL", raw_data=partial_data)
        assert partial["confidence"] < full["confidence"]

    def test_weight_normalization_with_missing_dims(self):
        """When dimensions are missing, remaining weights redistribute."""
        agg = DivergenceAggregator()
        # Only provide institutional data
        data = {
            "institutional": {
                "analyst": {"strong_buy": 10, "buy": 5, "hold": 3, "sell": 1, "strong_sell": 0},
                "insider": {"net_buying": 0.5, "total_volume": 1.0},
            },
            "regime": {"vix": 15.0},
        }
        result = agg.compute("AAPL", raw_data=data)
        # Composite should still be valid
        assert -1.0 <= result["composite_score"] <= 1.0
        # Only 1 dimension available
        assert result["dimensions_available"] == 1

class TestRegimeAdjustment:
    """Test regime-based composite adjustments."""

    def test_risk_on_no_change(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert result["regime"] == "RISK_ON"
        # Composite should be positive given mostly bullish inputs
        assert result["composite_score"] > 0

    def test_risk_off_flips_signal(self):
        """RISK_OFF should dampen/flip the composite via *-0.5 multiplier."""
        agg = DivergenceAggregator()
        on_result = agg.compute("AAPL", raw_data=_risk_on_data())
        off_result = agg.compute("AAPL", raw_data=_risk_off_data())
        # Same underlying signals but different regime
        assert on_result["composite_score"] > 0
        # RISK_OFF multiplies by -0.5, so positive becomes negative (dampened)
        assert off_result["composite_score"] < 0

    def test_risk_off_dampens_magnitude(self):
        """RISK_OFF composite magnitude should be smaller (multiplied by 0.5)."""
        agg = DivergenceAggregator()
        on_result = agg.compute("AAPL", raw_data=_risk_on_data())
        off_result = agg.compute("AAPL", raw_data=_risk_off_data())
        assert abs(off_result["composite_score"]) < abs(on_result["composite_score"])

    def test_transitioning_reduces_conviction(self):
        """TRANSITIONING regime multiplies by 0.7, reducing magnitude."""
        agg = DivergenceAggregator()
        on_result = agg.compute("AAPL", raw_data=_risk_on_data())
        trans_result = agg.compute("AAPL", raw_data=_transitioning_data())
        # Same direction but reduced magnitude
        if on_result["composite_score"] > 0:
            assert trans_result["composite_score"] > 0
        assert abs(trans_result["composite_score"]) < abs(on_result["composite_score"])

    def test_same_data_different_regime_different_composite(self):
        """Same signals under different regimes must produce different composites."""
        agg = DivergenceAggregator()
        on = agg.compute("AAPL", raw_data=_risk_on_data())
        off = agg.compute("AAPL", raw_data=_risk_off_data())
        trans = agg.compute("AAPL", raw_data=_transitioning_data())
        scores = {on["composite_score"], off["composite_score"], trans["composite_score"]}
        # At least 2 different scores (likely all 3)
        assert len(scores) >= 2

class TestBatchCompute:
    """Test compute_batch."""

    def test_batch_returns_list(self):
        agg = DivergenceAggregator()
        results = agg.compute_batch(["AAPL", "MSFT", "GOOG"])
        assert isinstance(results, list)
        assert len(results) == 3

    def test_batch_tickers_match(self):
        agg = DivergenceAggregator()
        tickers = ["AAPL", "MSFT"]
        results = agg.compute_batch(tickers)
        assert results[0]["ticker"] == "AAPL"
        assert results[1]["ticker"] == "MSFT"

    def test_batch_with_per_ticker_data(self):
        agg = DivergenceAggregator()
        batch_data = {
            "AAPL": _risk_on_data(),
            "MSFT": _risk_off_data(),
        }
        results = agg.compute_batch(["AAPL", "MSFT"], raw_data=batch_data)
        assert results[0]["regime"] == "RISK_ON"
        assert results[1]["regime"] == "RISK_OFF"

class TestAgentSummary:
    """Test agent_summary format."""

    def test_summary_contains_ticker(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert "AAPL" in result["agent_summary"]

    def test_summary_contains_regime(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert "RISK_ON" in result["agent_summary"]

    def test_summary_contains_direction(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        summary = result["agent_summary"]
        assert any(d in summary for d in ["BULLISH", "BEARISH", "NEUTRAL"])

    def test_summary_contains_dimensions_available(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        assert "5/5 dimensions available" in result["agent_summary"]

    def test_summary_contains_strongest_weakest(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL", raw_data=_risk_on_data())
        summary = result["agent_summary"]
        assert "Strongest:" in summary
        assert "Weakest:" in summary

class TestAllDimensionsMissing:
    """Test with no data at all."""

    def test_no_data_confidence_zero(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL")
        assert result["confidence"] == 0.0

    def test_no_data_composite_zero(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL")
        assert result["composite_score"] == 0.0

    def test_no_data_dimensions_available_zero(self):
        agg = DivergenceAggregator()
        result = agg.compute("AAPL")
        assert result["dimensions_available"] == 0


class TestCustomWeights:
    """Test custom weight configuration."""

    def test_custom_weights_normalized(self):
        agg = DivergenceAggregator(weights={
            "institutional": 1.0,
            "options": 1.0,
            "price_action": 1.0,
            "news": 1.0,
            "retail": 1.0,
        })
        assert abs(sum(agg.weights.values()) - 1.0) < 1e-9

    def test_zero_weights_raises(self):
        with pytest.raises(ValueError):
            DivergenceAggregator(weights={
                "institutional": 0,
                "options": 0,
                "price_action": 0,
                "news": 0,
                "retail": 0,
            })


class TestDefaultWeights:
    """Test default weight values."""

    def test_default_weights_sum_to_one(self):
        agg = DivergenceAggregator()
        assert abs(sum(agg.weights.values()) - 1.0) < 1e-9

    def test_institutional_highest_weight(self):
        agg = DivergenceAggregator()
        assert agg.weights["institutional"] > agg.weights["options"]
        assert agg.weights["institutional"] > agg.weights["price_action"]

