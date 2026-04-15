"""Tests for tradingagents.signals.factor_baseline.

Covers: Bullish->BUY, Bearish->SHORT, Neutral->HOLD, all scores in [-1,1].
"""

from __future__ import annotations

import pytest

from tradingagents.schemas.v3 import (
    EventCalendar,
    MacroContext,
    NewsContext,
    OptionsContext,
    PriceContext,
    Signal,
    SocialContext,
    TickerBriefing,
)
from tradingagents.signals.factor_baseline import (
    _clamp,
    _score_momentum,
    _score_quality,
    _score_value,
    compute_factor_score,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_DEFAULTS = dict(
    date="2026-04-05",
    snapshot_id="snap_test",
    options=OptionsContext(),
    news=NewsContext(),
    social=SocialContext(),
    macro=MacroContext(),
    events=EventCalendar(),
)


def _make_briefing(
    ticker: str = "TEST",
    price: float = 150.0,
    change_1d_pct: float = 0.5,
    change_5d_pct: float = 1.0,
    change_20d_pct: float = 0.0,
    sma_20: float = 148.0,
    sma_50: float = 145.0,
    sma_200: float = 140.0,
    rsi_14: float = 50.0,
    macd_above_signal: bool = True,
    macd_crossover_days: int = 3,
    bollinger_position: str = "middle_third",
    volume_vs_avg_20d: float = 1.0,
    atr_14: float = 2.5,
    data_age_seconds: int = 60,
) -> TickerBriefing:
    """Build a TickerBriefing with sensible defaults; override as needed."""
    return TickerBriefing(
        ticker=ticker,
        price=PriceContext(
            price=price,
            change_1d_pct=change_1d_pct,
            change_5d_pct=change_5d_pct,
            change_20d_pct=change_20d_pct,
            sma_20=sma_20,
            sma_50=sma_50,
            sma_200=sma_200,
            rsi_14=rsi_14,
            macd_above_signal=macd_above_signal,
            macd_crossover_days=macd_crossover_days,
            bollinger_position=bollinger_position,
            volume_vs_avg_20d=volume_vs_avg_20d,
            atr_14=atr_14,
            data_age_seconds=data_age_seconds,
        ),
        **_DEFAULTS,
    )


def _bullish_briefing() -> TickerBriefing:
    """All indicators strongly bullish."""
    return _make_briefing(
        price=200.0,
        sma_200=150.0,
        sma_50=180.0,
        rsi_14=70.0,
        macd_above_signal=True,
        change_20d_pct=10.0,
        volume_vs_avg_20d=1.5,
        bollinger_position="upper_third",
    )


def _bearish_briefing() -> TickerBriefing:
    """All indicators strongly bearish."""
    return _make_briefing(
        price=100.0,
        sma_200=150.0,
        sma_50=130.0,
        rsi_14=30.0,
        macd_above_signal=False,
        change_20d_pct=-10.0,
        volume_vs_avg_20d=0.5,
        bollinger_position="lower_third",
    )


def _neutral_briefing() -> TickerBriefing:
    """Mixed indicators that should produce HOLD.

    Momentum: price 150 > sma200 140 -> +0.3, rsi 50 neutral -> 0,
              macd False -> -0.2, 20d 0 -> 0.  Total = 0.1
    Quality:  vol 1.0 neutral -> 0, bollinger middle -> 0.  Total = 0.0
    Value:    price 150 < sma50 160 -> -0.5
    Composite = 0.1*0.5 + 0.0*0.3 + (-0.5)*0.2 = 0.05 - 0.1 = -0.05 -> HOLD
    """
    return _make_briefing(
        price=150.0,
        sma_200=140.0,
        sma_50=160.0,
        rsi_14=50.0,
        macd_above_signal=False,
        change_20d_pct=0.0,
        volume_vs_avg_20d=1.0,
        bollinger_position="middle_third",
    )


# ------------------------------------------------------------------
# _clamp
# ------------------------------------------------------------------


class TestClamp:
    def test_within_range(self) -> None:
        assert _clamp(0.5) == 0.5

    def test_below_min(self) -> None:
        assert _clamp(-2.0) == -1.0

    def test_above_max(self) -> None:
        assert _clamp(2.0) == 1.0

    def test_at_boundaries(self) -> None:
        assert _clamp(-1.0) == -1.0
        assert _clamp(1.0) == 1.0

    def test_custom_range(self) -> None:
        assert _clamp(5.0, 0.0, 3.0) == 3.0
        assert _clamp(-1.0, 0.0, 3.0) == 0.0


# ------------------------------------------------------------------
# _score_momentum
# ------------------------------------------------------------------


class TestScoreMomentum:
    def test_all_bullish(self) -> None:
        score = _score_momentum(_bullish_briefing())
        # +0.3 (sma200) +0.2 (rsi>60) +0.2 (macd) +0.3 (20d>5) = 1.0
        assert score == pytest.approx(1.0)

    def test_all_bearish(self) -> None:
        score = _score_momentum(_bearish_briefing())
        # -0.3 (sma200) -0.2 (rsi<40) -0.2 (macd) -0.3 (20d<-5) = -1.0
        assert score == pytest.approx(-1.0)

    def test_rsi_neutral_zone(self) -> None:
        b = _make_briefing(rsi_14=50.0)
        score = _score_momentum(b)
        # price>sma200 +0.3, rsi neutral 0, macd True +0.2, 20d 0 -> 0.5
        assert score == pytest.approx(0.5)

    def test_rsi_at_boundary_60(self) -> None:
        """RSI == 60 is NOT > 60, so neutral."""
        b = _make_briefing(rsi_14=60.0)
        score = _score_momentum(b)
        # +0.3 + 0 + 0.2 + 0 = 0.5
        assert score == pytest.approx(0.5)

    def test_rsi_at_boundary_40(self) -> None:
        """RSI == 40 is NOT < 40, so neutral."""
        b = _make_briefing(rsi_14=40.0)
        score = _score_momentum(b)
        # +0.3 + 0 + 0.2 + 0 = 0.5
        assert score == pytest.approx(0.5)

    def test_score_in_range(self) -> None:
        score = _score_momentum(_make_briefing())
        assert -1.0 <= score <= 1.0


# ------------------------------------------------------------------
# _score_quality
# ------------------------------------------------------------------


class TestScoreQuality:
    def test_high_volume_upper_bollinger(self) -> None:
        b = _make_briefing(volume_vs_avg_20d=1.5, bollinger_position="upper_third")
        assert _score_quality(b) == pytest.approx(0.75)

    def test_low_volume_lower_bollinger(self) -> None:
        b = _make_briefing(volume_vs_avg_20d=0.5, bollinger_position="lower_third")
        assert _score_quality(b) == pytest.approx(-0.75)

    def test_neutral_quality(self) -> None:
        b = _make_briefing(volume_vs_avg_20d=1.0, bollinger_position="middle_third")
        assert _score_quality(b) == pytest.approx(0.0)

    def test_volume_at_threshold_1_2(self) -> None:
        """volume == 1.2 is NOT > 1.2, so neutral."""
        b = _make_briefing(volume_vs_avg_20d=1.2, bollinger_position="middle_third")
        assert _score_quality(b) == pytest.approx(0.0)

    def test_volume_at_threshold_0_8(self) -> None:
        """volume == 0.8 is NOT < 0.8, so neutral."""
        b = _make_briefing(volume_vs_avg_20d=0.8, bollinger_position="middle_third")
        assert _score_quality(b) == pytest.approx(0.0)

    def test_score_in_range(self) -> None:
        score = _score_quality(_make_briefing())
        assert -1.0 <= score <= 1.0


# ------------------------------------------------------------------
# _score_value
# ------------------------------------------------------------------


class TestScoreValue:
    def test_price_above_sma50(self) -> None:
        b = _make_briefing(price=200.0, sma_50=180.0)
        assert _score_value(b) == pytest.approx(0.5)

    def test_price_below_sma50(self) -> None:
        b = _make_briefing(price=100.0, sma_50=130.0)
        assert _score_value(b) == pytest.approx(-0.5)

    def test_price_equal_sma50(self) -> None:
        """price == sma_50 is NOT > sma_50, so returns -0.5."""
        b = _make_briefing(price=150.0, sma_50=150.0)
        assert _score_value(b) == pytest.approx(-0.5)


# ------------------------------------------------------------------
# compute_factor_score -- integration
# ------------------------------------------------------------------


class TestComputeFactorScore:
    def test_bullish_produces_buy(self) -> None:
        result = compute_factor_score(_bullish_briefing())
        assert result["signal"] == Signal.BUY
        assert result["composite_score"] > 0.2

    def test_bearish_produces_short(self) -> None:
        result = compute_factor_score(_bearish_briefing())
        assert result["signal"] == Signal.SHORT
        assert result["composite_score"] < -0.2

    def test_neutral_produces_hold(self) -> None:
        result = compute_factor_score(_neutral_briefing())
        assert result["signal"] == Signal.HOLD
        assert -0.2 <= result["composite_score"] <= 0.2

    def test_all_scores_in_range(self) -> None:
        for factory in (_bullish_briefing, _bearish_briefing, _neutral_briefing):
            result = compute_factor_score(factory())
            assert -1.0 <= result["momentum_score"] <= 1.0
            assert -1.0 <= result["quality_score"] <= 1.0
            assert -1.0 <= result["value_score"] <= 1.0
            assert -1.0 <= result["composite_score"] <= 1.0

    def test_result_keys(self) -> None:
        result = compute_factor_score(_bullish_briefing())
        expected_keys = {
            "ticker",
            "momentum_score",
            "quality_score",
            "value_score",
            "composite_score",
            "signal",
            "components",
        }
        assert set(result.keys()) == expected_keys

    def test_ticker_passed_through(self) -> None:
        result = compute_factor_score(_make_briefing(ticker="AAPL"))
        assert result["ticker"] == "AAPL"

    def test_composite_formula(self) -> None:
        """Verify composite = mom*0.5 + qual*0.3 + val*0.2 (clamped)."""
        result = compute_factor_score(_bullish_briefing())
        expected = (
            result["momentum_score"] * 0.5
            + result["quality_score"] * 0.3
            + result["value_score"] * 0.2
        )
        expected = max(-1.0, min(1.0, expected))
        assert result["composite_score"] == pytest.approx(expected)

    def test_signal_boundary_hold(self) -> None:
        """Composite near but not exceeding 0.2 should be HOLD."""
        # mom=0.5, qual=0, val=-0.5 -> 0.5*0.5 + 0*0.3 + (-0.5)*0.2 = 0.15
        b = _make_briefing(
            price=200.0,
            sma_200=100.0,
            rsi_14=50.0,
            macd_above_signal=True,
            change_20d_pct=0.0,
            volume_vs_avg_20d=1.0,
            bollinger_position="middle_third",
            sma_50=250.0,
        )
        result = compute_factor_score(b)
        assert result["signal"] == Signal.HOLD

    def test_signal_is_enum(self) -> None:
        result = compute_factor_score(_bullish_briefing())
        assert isinstance(result["signal"], Signal)

    def test_components_weight_keys(self) -> None:
        result = compute_factor_score(_make_briefing())
        components = result["components"]
        assert components["momentum_weight"] == pytest.approx(0.5)
        assert components["quality_weight"] == pytest.approx(0.3)
        assert components["value_weight"] == pytest.approx(0.2)


# ------------------------------------------------------------------
# Extreme / parametrized score range tests
# ------------------------------------------------------------------


class TestExtremeScoreRanges:
    """Verify scores stay in [-1, 1] even with extreme inputs."""

    @pytest.fixture(
        params=[
            dict(
                price=200.0,
                change_20d_pct=50.0,
                sma_200=50.0,
                rsi_14=99.0,
                macd_above_signal=True,
                volume_vs_avg_20d=5.0,
                bollinger_position="upper_third",
            ),
            dict(
                price=10.0,
                change_20d_pct=-50.0,
                sma_200=200.0,
                rsi_14=1.0,
                macd_above_signal=False,
                volume_vs_avg_20d=0.01,
                bollinger_position="lower_third",
            ),
        ],
    )
    def result(self, request: pytest.FixtureRequest) -> dict:
        briefing = _make_briefing(**request.param)
        return compute_factor_score(briefing)

    def test_composite_in_range(self, result: dict) -> None:
        assert -1.0 <= result["composite_score"] <= 1.0

    def test_momentum_in_range(self, result: dict) -> None:
        assert -1.0 <= result["momentum_score"] <= 1.0

    def test_quality_in_range(self, result: dict) -> None:
        assert -1.0 <= result["quality_score"] <= 1.0

    def test_value_in_range(self, result: dict) -> None:
        assert -1.0 <= result["value_score"] <= 1.0
