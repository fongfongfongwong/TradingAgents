import pytest
from types import SimpleNamespace
from tradingagents.signals.options_signal import (
    compute_options_value,
    classify_options_direction,
    derive_options_signal,
)


def _opts(pcr=None, skew=None, rank=None):
    return SimpleNamespace(
        put_call_ratio=pcr, iv_skew_25d=skew, iv_rank_percentile=rank
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
