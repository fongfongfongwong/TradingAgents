"""Tests for divergence schema models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.divergence.schemas import (
    DIMENSIONS,
    DimensionScore,
    DivergenceVector,
    RegimeState,
)


# ---------------------------------------------------------------------------
# DimensionScore
# ---------------------------------------------------------------------------

class TestDimensionScore:
    def test_construction_valid(self):
        ds = DimensionScore(
            dimension="institutional", value=0.5, confidence=0.8,
            sources=["cboe", "finnhub"], raw_data={"put_call_ratio": 0.9},
        )
        assert ds.dimension == "institutional"
        assert ds.value == 0.5
        assert ds.confidence == 0.8
        assert ds.sources == ["cboe", "finnhub"]

    def test_value_bounds_upper(self):
        with pytest.raises(ValidationError):
            DimensionScore(dimension="options", value=1.5, confidence=0.5)

    def test_value_bounds_lower(self):
        with pytest.raises(ValidationError):
            DimensionScore(dimension="options", value=-1.5, confidence=0.5)

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            DimensionScore(dimension="news", value=0.0, confidence=1.5)

    def test_invalid_dimension_name(self):
        with pytest.raises(ValidationError):
            DimensionScore(dimension="made_up", value=0.0, confidence=0.5)

    def test_defaults(self):
        ds = DimensionScore(dimension="retail", value=0.1, confidence=0.2)
        assert ds.sources == []
        assert ds.raw_data == {}


# ---------------------------------------------------------------------------
# RegimeState
# ---------------------------------------------------------------------------

class TestRegimeState:
    def test_values(self):
        assert RegimeState.RISK_ON == "RISK_ON"
        assert RegimeState.RISK_OFF == "RISK_OFF"
        assert RegimeState.TRANSITIONING == "TRANSITIONING"


# ---------------------------------------------------------------------------
# DivergenceVector
# ---------------------------------------------------------------------------

def _make_vector(**overrides) -> DivergenceVector:
    """Helper to build a minimal DivergenceVector."""
    dims = {}
    values = {"institutional": 0.8, "options": -0.3, "price_action": 0.1, "news": 0.0, "retail": -0.5}
    for d in DIMENSIONS:
        dims[d] = DimensionScore(
            dimension=d, value=values[d], confidence=0.9, sources=["src1"],
        )
    defaults = dict(
        ticker="AAPL",
        timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        regime=RegimeState.RISK_ON,
        dimensions=dims,
        composite_score=0.25,
        weights={d: 0.2 for d in DIMENSIONS},
    )
    defaults.update(overrides)
    return DivergenceVector(**defaults)


class TestDivergenceVector:
    def test_construction(self):
        v = _make_vector()
        assert v.ticker == "AAPL"
        assert len(v.dimensions) == 5

    def test_strongest_signal(self):
        v = _make_vector()
        s = v.strongest_signal()
        assert s.dimension == "institutional"
        assert s.value == 0.8

    def test_weakest_signal(self):
        v = _make_vector()
        w = v.weakest_signal()
        assert w.dimension == "news"
        assert w.value == 0.0

    def test_is_divergent_true(self):
        # spread = 0.8 - (-0.5) = 1.3 > 0.3
        v = _make_vector()
        assert v.is_divergent(threshold=0.3) is True

    def test_is_divergent_false(self):
        dims = {}
        for d in DIMENSIONS:
            dims[d] = DimensionScore(dimension=d, value=0.1, confidence=0.5, sources=["s"])
        v = _make_vector(dimensions=dims)
        assert v.is_divergent(threshold=0.3) is False

    def test_is_divergent_custom_threshold(self):
        v = _make_vector()
        # spread 1.3, threshold 2.0
        assert v.is_divergent(threshold=2.0) is False

    def test_to_agent_summary_contains_key_info(self):
        v = _make_vector()
        summary = v.to_agent_summary()
        assert "AAPL" in summary
        assert "RISK_ON" in summary
        assert "institutional" in summary
        assert "Strongest signal" in summary
        assert "Divergent" in summary

    def test_composite_score_validation(self):
        with pytest.raises(ValidationError):
            _make_vector(composite_score=5.0)
