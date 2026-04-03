"""Tests for the RegimeDetector."""

from __future__ import annotations

import pytest

from tradingagents.divergence.regime import RegimeDetector
from tradingagents.divergence.schemas import RegimeState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector() -> RegimeDetector:
    """Default detector with standard thresholds."""
    return RegimeDetector()


@pytest.fixture
def custom_detector() -> RegimeDetector:
    """Detector with custom thresholds."""
    return RegimeDetector(
        vix_thresholds=(15.0, 25.0),
        breadth_threshold=0.6,
        pc_thresholds=(0.6, 0.9),
    )


# ---------------------------------------------------------------------------
# VIX classification
# ---------------------------------------------------------------------------

class TestVixClassification:
    def test_low_vix_risk_on(self, detector: RegimeDetector) -> None:
        assert detector._classify_vix(12.0) == RegimeState.RISK_ON

    def test_high_vix_risk_off(self, detector: RegimeDetector) -> None:
        assert detector._classify_vix(35.0) == RegimeState.RISK_OFF

    def test_mid_vix_transitioning(self, detector: RegimeDetector) -> None:
        assert detector._classify_vix(25.0) == RegimeState.TRANSITIONING

    def test_vix_at_low_boundary(self, detector: RegimeDetector) -> None:
        # VIX == 20 is NOT < 20, so it should be TRANSITIONING
        assert detector._classify_vix(20.0) == RegimeState.TRANSITIONING

    def test_vix_at_high_boundary(self, detector: RegimeDetector) -> None:
        # VIX == 30 is NOT > 30, so it should be TRANSITIONING
        assert detector._classify_vix(30.0) == RegimeState.TRANSITIONING


# ---------------------------------------------------------------------------
# Breadth classification
# ---------------------------------------------------------------------------

class TestBreadthClassification:
    def test_high_breadth_risk_on(self, detector: RegimeDetector) -> None:
        assert detector._classify_breadth(0.7) == RegimeState.RISK_ON

    def test_low_breadth_risk_off(self, detector: RegimeDetector) -> None:
        assert detector._classify_breadth(0.3) == RegimeState.RISK_OFF

    def test_mid_breadth_transitioning(self, detector: RegimeDetector) -> None:
        assert detector._classify_breadth(0.5) == RegimeState.TRANSITIONING

    def test_breadth_at_threshold(self, detector: RegimeDetector) -> None:
        # breadth == 0.5 is NOT > 0.5, so TRANSITIONING (or RISK_OFF check)
        # 0.5 is not < 0.5 either -> TRANSITIONING
        assert detector._classify_breadth(0.5) == RegimeState.TRANSITIONING


# ---------------------------------------------------------------------------
# Put/call ratio classification
# ---------------------------------------------------------------------------

class TestPutCallClassification:
    def test_low_pc_risk_on(self, detector: RegimeDetector) -> None:
        assert detector._classify_put_call(0.5) == RegimeState.RISK_ON

    def test_high_pc_risk_off(self, detector: RegimeDetector) -> None:
        assert detector._classify_put_call(1.2) == RegimeState.RISK_OFF

    def test_mid_pc_transitioning(self, detector: RegimeDetector) -> None:
        assert detector._classify_put_call(0.85) == RegimeState.TRANSITIONING


# ---------------------------------------------------------------------------
# Majority voting
# ---------------------------------------------------------------------------

class TestMajorityVote:
    def test_two_of_three_agree_risk_on(self, detector: RegimeDetector) -> None:
        signals = [RegimeState.RISK_ON, RegimeState.RISK_ON, RegimeState.RISK_OFF]
        assert detector._majority_vote(signals) == RegimeState.RISK_ON

    def test_two_of_three_agree_risk_off(self, detector: RegimeDetector) -> None:
        signals = [RegimeState.RISK_OFF, RegimeState.RISK_ON, RegimeState.RISK_OFF]
        assert detector._majority_vote(signals) == RegimeState.RISK_OFF

    def test_all_agree(self, detector: RegimeDetector) -> None:
        signals = [RegimeState.RISK_ON, RegimeState.RISK_ON, RegimeState.RISK_ON]
        assert detector._majority_vote(signals) == RegimeState.RISK_ON

    def test_all_disagree_transitioning(self, detector: RegimeDetector) -> None:
        signals = [RegimeState.RISK_ON, RegimeState.RISK_OFF, RegimeState.TRANSITIONING]
        assert detector._majority_vote(signals) == RegimeState.TRANSITIONING

    def test_single_signal(self, detector: RegimeDetector) -> None:
        assert detector._majority_vote([RegimeState.RISK_OFF]) == RegimeState.RISK_OFF

    def test_two_way_tie_transitioning(self, detector: RegimeDetector) -> None:
        signals = [RegimeState.RISK_ON, RegimeState.RISK_OFF]
        assert detector._majority_vote(signals) == RegimeState.TRANSITIONING


# ---------------------------------------------------------------------------
# detect() integration
# ---------------------------------------------------------------------------

class TestDetect:
    def test_all_signals_agree(self, detector: RegimeDetector) -> None:
        result = detector.detect(vix=12.0, breadth=0.8, put_call_ratio=0.5)
        assert result == RegimeState.RISK_ON

    def test_only_vix(self, detector: RegimeDetector) -> None:
        assert detector.detect(vix=35.0) == RegimeState.RISK_OFF

    def test_only_breadth(self, detector: RegimeDetector) -> None:
        assert detector.detect(breadth=0.8) == RegimeState.RISK_ON

    def test_only_put_call(self, detector: RegimeDetector) -> None:
        assert detector.detect(put_call_ratio=1.5) == RegimeState.RISK_OFF

    def test_no_data_returns_transitioning(self, detector: RegimeDetector) -> None:
        assert detector.detect() == RegimeState.TRANSITIONING

    def test_two_signals_disagree(self, detector: RegimeDetector) -> None:
        # VIX=12 -> RISK_ON, PC=1.2 -> RISK_OFF => tie => TRANSITIONING
        assert detector.detect(vix=12.0, put_call_ratio=1.2) == RegimeState.TRANSITIONING

    def test_two_signals_agree(self, detector: RegimeDetector) -> None:
        # VIX=12 -> RISK_ON, breadth=0.8 -> RISK_ON
        assert detector.detect(vix=12.0, breadth=0.8) == RegimeState.RISK_ON


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_custom_vix_thresholds(self, custom_detector: RegimeDetector) -> None:
        # With vix_thresholds=(15, 25): VIX=18 should be TRANSITIONING (not RISK_ON)
        assert custom_detector._classify_vix(18.0) == RegimeState.TRANSITIONING
        # VIX=14 -> RISK_ON with custom thresholds
        assert custom_detector._classify_vix(14.0) == RegimeState.RISK_ON
        # VIX=26 -> RISK_OFF with custom thresholds
        assert custom_detector._classify_vix(26.0) == RegimeState.RISK_OFF

    def test_custom_breadth_threshold(self, custom_detector: RegimeDetector) -> None:
        # breadth_threshold=0.6: breadth=0.55 -> TRANSITIONING (not RISK_ON)
        assert custom_detector._classify_breadth(0.55) == RegimeState.TRANSITIONING
        # breadth=0.65 -> RISK_ON
        assert custom_detector._classify_breadth(0.65) == RegimeState.RISK_ON

    def test_custom_pc_thresholds(self, custom_detector: RegimeDetector) -> None:
        # pc_thresholds=(0.6, 0.9): ratio=0.55 -> RISK_ON
        assert custom_detector._classify_put_call(0.55) == RegimeState.RISK_ON
        # ratio=0.95 -> RISK_OFF
        assert custom_detector._classify_put_call(0.95) == RegimeState.RISK_OFF
        # ratio=0.75 -> TRANSITIONING
        assert custom_detector._classify_put_call(0.75) == RegimeState.TRANSITIONING
