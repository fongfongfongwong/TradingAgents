"""Tests for PriceActionDimension, NewsDimension, and RetailDimension."""

from __future__ import annotations

import pytest

from tradingagents.divergence.dimensions.price_action import PriceActionDimension
from tradingagents.divergence.dimensions.news import NewsDimension
from tradingagents.divergence.dimensions.retail import RetailDimension


# =====================================================================
# Helpers
# =====================================================================

def _assert_result_shape(result: dict) -> None:
    """Verify the standard result dict has the expected keys and ranges."""
    assert "value" in result
    assert "confidence" in result
    assert "sources" in result
    assert "raw_data" in result
    assert -1.0 <= result["value"] <= 1.0
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["sources"], list)
    assert isinstance(result["raw_data"], dict)


# =====================================================================
# PriceActionDimension
# =====================================================================

class TestPriceActionDimension:
    """Tests for PriceActionDimension."""

    def setup_method(self) -> None:
        self.dim = PriceActionDimension()

    def test_uptrend_normal_rsi(self) -> None:
        """Strong uptrend with neutral RSI -> bullish, signals agree."""
        # RSI 45 -> mean_reversion = (50-45)/50 = +0.1, same sign as momentum
        data = {"current_price": 150, "sma_50": 140, "sma_200": 120, "rsi_14": 45}
        result = self.dim.compute("AAPL", price_data=data)
        _assert_result_shape(result)
        assert result["value"] > 0.3, "Uptrend + neutral RSI should be bullish"
        assert result["raw_data"]["signals_agree"] is True

    def test_uptrend_overbought_rsi_divergence(self) -> None:
        """Uptrend but RSI overbought -> divergence, value near 0."""
        data = {"current_price": 150, "sma_50": 140, "sma_200": 120, "rsi_14": 80}
        result = self.dim.compute("AAPL", price_data=data)
        _assert_result_shape(result)
        # Momentum is +1, mean-reversion is negative => combined near 0
        assert abs(result["value"]) < 0.6, "Divergent signals should cancel"
        assert result["raw_data"]["signals_agree"] is False

    def test_downtrend_oversold_rsi_divergence(self) -> None:
        """Downtrend but RSI oversold -> divergence."""
        data = {"current_price": 80, "sma_50": 90, "sma_200": 110, "rsi_14": 20}
        result = self.dim.compute("AAPL", price_data=data)
        _assert_result_shape(result)
        # Momentum is -1, mean-reversion is bullish => near 0
        assert abs(result["value"]) < 0.6, "Divergent signals should cancel"
        assert result["raw_data"]["signals_agree"] is False

    def test_downtrend_normal_rsi(self) -> None:
        """Strong downtrend with neutral RSI -> bearish."""
        # RSI 55 -> mean_reversion = (50-55)/50 = -0.1, same sign as momentum
        data = {"current_price": 80, "sma_50": 90, "sma_200": 110, "rsi_14": 55}
        result = self.dim.compute("AAPL", price_data=data)
        _assert_result_shape(result)
        assert result["value"] < -0.3, "Downtrend + neutral RSI should be bearish"
        assert result["raw_data"]["signals_agree"] is True

    def test_missing_data_returns_zero(self) -> None:
        """No price data -> value=0, confidence=0."""
        result = self.dim.compute("AAPL", price_data=None)
        _assert_result_shape(result)
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0
        assert result["sources"] == []

    def test_partial_data_momentum_only(self) -> None:
        """Only SMA data, no RSI -> momentum only."""
        data = {"current_price": 150, "sma_50": 140, "sma_200": 120}
        result = self.dim.compute("AAPL", price_data=data)
        _assert_result_shape(result)
        assert result["value"] > 0, "Should still detect uptrend"
        assert "price_momentum" in result["sources"]
        assert "mean_reversion" not in result["sources"]

    def test_partial_data_rsi_only(self) -> None:
        """Only RSI, no price/SMA data -> mean-reversion only."""
        data = {"rsi_14": 25}
        result = self.dim.compute("AAPL", price_data=data)
        _assert_result_shape(result)
        assert result["value"] > 0, "Oversold RSI should be contrarian bullish"
        assert "mean_reversion" in result["sources"]
        assert "price_momentum" not in result["sources"]


# =====================================================================
# NewsDimension
# =====================================================================

class TestNewsDimension:
    """Tests for NewsDimension."""

    def setup_method(self) -> None:
        self.dim = NewsDimension()

    def test_high_bullish_sentiment(self) -> None:
        """Mostly bullish news -> positive score."""
        data = {
            "bullish_percent": 0.80,
            "bearish_percent": 0.10,
            "articles_in_last_week": 25,
        }
        result = self.dim.compute("TSLA", sentiment_data=data)
        _assert_result_shape(result)
        assert result["value"] > 0.5, "Strong bullish sentiment"
        assert result["confidence"] > 0.4

    def test_high_bearish_sentiment(self) -> None:
        """Mostly bearish news -> negative score."""
        data = {
            "bullish_percent": 0.10,
            "bearish_percent": 0.80,
            "articles_in_last_week": 30,
        }
        result = self.dim.compute("TSLA", sentiment_data=data)
        _assert_result_shape(result)
        assert result["value"] < -0.5, "Strong bearish sentiment"

    def test_neutral_sentiment(self) -> None:
        """Balanced sentiment -> near zero."""
        data = {
            "bullish_percent": 0.45,
            "bearish_percent": 0.45,
            "articles_in_last_week": 15,
        }
        result = self.dim.compute("TSLA", sentiment_data=data)
        _assert_result_shape(result)
        assert abs(result["value"]) < 0.2, "Balanced sentiment should be near zero"

    def test_with_company_news_score(self) -> None:
        """Both spread and company news score present."""
        data = {
            "bullish_percent": 0.60,
            "bearish_percent": 0.30,
            "company_news_score": 0.5,
            "articles_in_last_week": 20,
        }
        result = self.dim.compute("TSLA", sentiment_data=data)
        _assert_result_shape(result)
        assert result["value"] > 0
        assert "news_sentiment" in result["sources"]
        assert "company_news_score" in result["sources"]

    def test_low_article_count_reduces_confidence(self) -> None:
        """Few articles -> confidence is scaled down."""
        data_few = {
            "bullish_percent": 0.80,
            "bearish_percent": 0.10,
            "articles_in_last_week": 2,
        }
        data_many = {
            "bullish_percent": 0.80,
            "bearish_percent": 0.10,
            "articles_in_last_week": 25,
        }
        result_few = self.dim.compute("TSLA", sentiment_data=data_few)
        result_many = self.dim.compute("TSLA", sentiment_data=data_many)
        assert result_few["confidence"] < result_many["confidence"]

    def test_missing_data_returns_zero(self) -> None:
        """No sentiment data -> value=0, confidence=0."""
        result = self.dim.compute("TSLA", sentiment_data=None)
        _assert_result_shape(result)
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0
        assert result["sources"] == []


# =====================================================================
# RetailDimension
# =====================================================================

class TestRetailDimension:
    """Tests for RetailDimension."""

    def setup_method(self) -> None:
        self.dim = RetailDimension()

    def test_high_mentions_greed(self) -> None:
        """High social mentions + extreme greed -> mixed/bearish (contrarian)."""
        social = {"mentions": 400, "mentions_24h_ago": 200}
        fg = {"value": 85}  # extreme greed -> contrarian bearish
        result = self.dim.compute("GME", social_data=social, fear_greed=fg)
        _assert_result_shape(result)
        # Social is bullish (growing), fear_greed is contrarian bearish
        assert "social_mentions" in result["sources"]
        assert "fear_greed_index" in result["sources"]

    def test_low_mentions_fear(self) -> None:
        """Low social mentions + extreme fear -> contrarian bullish from F&G."""
        social = {"mentions": 5, "mentions_24h_ago": 10}
        fg = {"value": 15}  # extreme fear -> contrarian bullish
        result = self.dim.compute("GME", social_data=social, fear_greed=fg)
        _assert_result_shape(result)
        assert result["value"] > 0, "Extreme fear is contrarian bullish"

    def test_aaii_bullish_spread(self) -> None:
        """Positive AAII spread -> bullish signal."""
        fg = {"value": 50, "aaii_bull_bear_spread": 30}
        result = self.dim.compute("SPY", fear_greed=fg)
        _assert_result_shape(result)
        assert result["value"] > 0, "Bullish AAII spread should contribute positively"
        assert "aaii_survey" in result["sources"]

    def test_aaii_bearish_spread(self) -> None:
        """Negative AAII spread -> bearish signal."""
        fg = {"value": 50, "aaii_bull_bear_spread": -30}
        result = self.dim.compute("SPY", fear_greed=fg)
        _assert_result_shape(result)
        assert result["value"] < 0, "Bearish AAII spread should be negative"

    def test_all_signals_present(self) -> None:
        """All three retail sub-signals available."""
        social = {"mentions": 300, "mentions_24h_ago": 250}
        fg = {"value": 60, "aaii_bull_bear_spread": 10}
        result = self.dim.compute("AMC", social_data=social, fear_greed=fg)
        _assert_result_shape(result)
        assert len(result["sources"]) == 3
        # Confidence should be higher with more signals
        assert result["confidence"] >= 0.7

    def test_missing_all_data(self) -> None:
        """No data at all -> value=0, confidence=0."""
        result = self.dim.compute("GME")
        _assert_result_shape(result)
        assert result["value"] == 0.0
        assert result["confidence"] == 0.0
        assert result["sources"] == []

    def test_social_only(self) -> None:
        """Only social data, no fear & greed."""
        social = {"mentions": 200, "mentions_24h_ago": 100}
        result = self.dim.compute("GME", social_data=social)
        _assert_result_shape(result)
        assert result["value"] > 0, "Growing mentions should be bullish"
        assert "social_mentions" in result["sources"]
        assert len(result["sources"]) == 1

    def test_fear_greed_only(self) -> None:
        """Only Fear & Greed index, no social."""
        fg = {"value": 20}
        result = self.dim.compute("SPY", fear_greed=fg)
        _assert_result_shape(result)
        assert result["value"] > 0, "Low F&G (fear) should be contrarian bullish"

    def test_flat_mentions_trend(self) -> None:
        """Mentions present but flat trend -> weakly positive."""
        social = {"mentions": 300, "mentions_24h_ago": 300}
        result = self.dim.compute("GME", social_data=social)
        _assert_result_shape(result)
        # Flat trend with mentions -> weakly bullish
        assert result["value"] >= 0
