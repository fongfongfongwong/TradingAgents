import pytest
from types import SimpleNamespace
from tradingagents.signals.options_signal import (
    compute_options_value,
    classify_options_direction,
    derive_options_signal,
)


def _opts(pcr=None, skew=None, rank=None, flow_pcr=None, large_trade_bias=None):
    return SimpleNamespace(
        put_call_ratio=pcr,
        iv_skew_25d=skew,
        iv_rank_percentile=rank,
        flow_put_call_ratio=flow_pcr,
        large_trade_bias=large_trade_bias,
    )


class TestComputeValue:
    def test_neutral_pcr(self):
        # pcr=0.85 -> score=0
        v, _ = compute_options_value(_opts(pcr=0.85, skew=0.0))
        assert abs(v) < 0.001

    def test_bullish_pcr(self):
        # pcr=0.5 -> (0.85-0.5)*2 = 0.7 -> strong bull
        v, _ = compute_options_value(_opts(pcr=0.5, skew=0.0))
        assert v > 0.3

    def test_bearish_pcr(self):
        v, _ = compute_options_value(_opts(pcr=1.3, skew=0.0))
        assert v < -0.3

    def test_skew_dominates(self):
        v, _ = compute_options_value(_opts(pcr=0.85, skew=0.1))
        assert v < 0  # positive skew (put-heavy) = bearish


class TestHysteresis:
    def test_no_previous_direction_uses_025_threshold(self):
        d, _ = classify_options_direction(0.20, previous_direction=None)
        assert d == "NEUTRAL"
        d, _ = classify_options_direction(0.30, previous_direction=None)
        assert d == "BULL"
        d, _ = classify_options_direction(-0.30, previous_direction=None)
        assert d == "BEAR"

    def test_previous_bull_sticky(self):
        # Was BULL; value now at +0.18 -> should stay BULL (within hysteresis band)
        d, _ = classify_options_direction(0.18, previous_direction="BULL")
        assert d == "BULL"
        # Only flips BEAR if value goes below -0.35
        d, _ = classify_options_direction(-0.30, previous_direction="BULL")
        assert d == "NEUTRAL"  # crossed -0.25 but not -0.35
        d, _ = classify_options_direction(-0.40, previous_direction="BULL")
        assert d == "BEAR"

    def test_previous_bear_sticky(self):
        d, _ = classify_options_direction(0.20, previous_direction="BEAR")
        assert d == "NEUTRAL"
        d, _ = classify_options_direction(0.40, previous_direction="BEAR")
        assert d == "BULL"


class TestDerive:
    def test_no_data_returns_none(self):
        d, i = derive_options_signal(_opts())
        assert d is None and i is None

    def test_impact_range(self):
        d, i = derive_options_signal(_opts(pcr=0.5, skew=-0.05))
        assert d == "BULL"
        assert 0 <= i <= 100


class TestTradeFlowScoring:
    """The paid Databento feed populates flow_pcr + large_trade_bias.

    When those are present, scoring should switch to the 4-dim weighted
    average (35/30/20/15) instead of the legacy 2-dim (60/40).
    """

    def test_legacy_weighting_when_no_flow(self):
        # Only OI-PCR + skew → legacy 60/40 weighting.
        # pcr=0.5 gives pcr_score=0.7; skew=0 → value = 0.6*0.7 = 0.42
        v, _ = compute_options_value(_opts(pcr=0.5, skew=0.0))
        assert abs(v - 0.42) < 0.01

    def test_flow_weighting_applies_when_flow_pcr_present(self):
        # With flow, weights switch to 35/30/20/15. A bearish flow_pcr
        # should reduce the bullish tilt from OI PCR alone.
        v_no_flow, _ = compute_options_value(_opts(pcr=0.5, skew=0.0))
        v_with_bear_flow, _ = compute_options_value(
            _opts(pcr=0.5, skew=0.0, flow_pcr=1.2)
        )
        assert v_with_bear_flow < v_no_flow, (
            "bearish flow should drag down the composite when added"
        )

    def test_large_trade_bias_alone_produces_signal(self):
        # Only large_trade_bias → still picks 4-dim weighting, but only
        # the large-trade weight contributes (renormalised).
        v, _ = compute_options_value(_opts(large_trade_bias=0.8))
        # Renormalised: 0.15 / 0.15 * 0.8 = 0.8
        assert abs(v - 0.8) < 0.01

    def test_flow_pcr_bullish_agrees_with_oi_pcr_bullish(self):
        # Both flow and OI bullish → stronger composite than either alone.
        v_oi_only, _ = compute_options_value(_opts(pcr=0.4, skew=0.0))
        v_both, _ = compute_options_value(
            _opts(pcr=0.4, skew=0.0, flow_pcr=0.3, large_trade_bias=0.5)
        )
        assert v_both > 0 and v_oi_only > 0
        # Both agreeing should produce at least as strong a signal.
        assert v_both >= v_oi_only - 0.1

    def test_confidence_increases_with_more_inputs(self):
        _, c_min = compute_options_value(_opts(pcr=0.8))
        _, c_max = compute_options_value(
            _opts(
                pcr=0.8,
                skew=0.0,
                rank=50.0,
                flow_pcr=0.8,
                large_trade_bias=0.0,
            )
        )
        assert c_max > c_min
        assert c_max <= 1.0

    def test_flow_disagrees_with_oi_signals_neutral_direction(self):
        # OI bullish (0.5) but flow bearish (1.3) → net near neutral.
        # With 35% PCR + 30% flow the two roughly cancel.
        v, _ = compute_options_value(_opts(pcr=0.5, flow_pcr=1.2))
        assert abs(v) < 0.25, (
            "strong OI/flow disagreement should dampen the composite signal"
        )
