"""Tests for DivergenceEngine."""

from __future__ import annotations

import pytest

from tradingagents.divergence.engine import DEFAULT_WEIGHTS, DivergenceEngine
from tradingagents.divergence.schemas import (
    DIMENSIONS,
    RegimeState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_signals() -> dict[str, dict]:
    """Return a full set of raw signals for all 5 dimensions."""
    return {
        "institutional": {"value": 0.6, "sources": ["cboe", "finnhub", "sec"]},
        "options": {"value": -0.4, "sources": ["cboe", "tos"]},
        "price_action": {"value": 0.2, "sources": ["finnhub", "yfinance", "ta"]},
        "news": {"value": 0.1, "sources": ["finnhub", "benzinga"]},
        "retail": {"value": -0.8, "sources": ["apewisdom", "aaii"]},
    }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestEngineInit:
    def test_default_weights(self):
        engine = DivergenceEngine()
        assert engine.weights == pytest.approx(DEFAULT_WEIGHTS)

    def test_custom_weights_normalized(self):
        engine = DivergenceEngine(weights={"institutional": 2, "options": 2})
        assert engine.weights["institutional"] == pytest.approx(0.5)
        assert engine.weights["options"] == pytest.approx(0.5)

    def test_zero_weights_raises(self):
        with pytest.raises(ValueError):
            DivergenceEngine(weights={"institutional": 0, "options": 0})


# ---------------------------------------------------------------------------
# compute
# ---------------------------------------------------------------------------

class TestCompute:
    def test_full_data(self):
        engine = DivergenceEngine()
        vec = engine.compute("AAPL", _full_signals())
        assert vec.ticker == "AAPL"
        assert len(vec.dimensions) == 5
        for d in DIMENSIONS:
            assert d in vec.dimensions
        assert -1.0 <= vec.composite_score <= 1.0

    def test_missing_dimensions_graceful(self):
        engine = DivergenceEngine()
        # Only provide two dimensions.
        partial = {
            "institutional": {"value": 0.5, "sources": ["cboe"]},
            "options": {"value": -0.3, "sources": ["cboe"]},
        }
        vec = engine.compute("TSLA", partial)
        assert len(vec.dimensions) == 5
        # Missing dims should have zero value and zero confidence.
        assert vec.dimensions["retail"].value == 0.0
        assert vec.dimensions["retail"].confidence == 0.0

    def test_regime_defaults_to_risk_on(self):
        engine = DivergenceEngine()
        vec = engine.compute("AAPL", _full_signals())
        assert vec.regime == RegimeState.RISK_ON

    def test_regime_override(self):
        engine = DivergenceEngine()
        vec = engine.compute("AAPL", _full_signals(), regime=RegimeState.RISK_OFF)
        assert vec.regime == RegimeState.RISK_OFF

    def test_regime_adjustment_flips_sign(self):
        engine = DivergenceEngine()
        vec_on = engine.compute("AAPL", _full_signals(), regime=RegimeState.RISK_ON)
        vec_off = engine.compute("AAPL", _full_signals(), regime=RegimeState.RISK_OFF)
        # Composite should be opposite sign (unless zero).
        if vec_on.composite_score != 0.0:
            assert (vec_on.composite_score > 0) != (vec_off.composite_score > 0), (
                f"RISK_OFF should flip sign: on={vec_on.composite_score}, off={vec_off.composite_score}"
            )

    def test_weights_stored_on_vector(self):
        engine = DivergenceEngine()
        vec = engine.compute("AAPL", _full_signals())
        assert vec.weights == pytest.approx(engine.weights)

    def test_empty_signals_all_zero(self):
        engine = DivergenceEngine()
        vec = engine.compute("XYZ", {})
        assert vec.composite_score == 0.0
        for d in vec.dimensions.values():
            assert d.value == 0.0
            assert d.confidence == 0.0


# ---------------------------------------------------------------------------
# _normalize_score
# ---------------------------------------------------------------------------

class TestNormalizeScore:
    def test_within_bounds(self):
        assert DivergenceEngine._normalize_score(0.5, "options") == 0.5

    def test_clamp_upper(self):
        assert DivergenceEngine._normalize_score(5.0, "news") == 1.0

    def test_clamp_lower(self):
        assert DivergenceEngine._normalize_score(-3.0, "retail") == -1.0

    def test_zero(self):
        assert DivergenceEngine._normalize_score(0.0, "institutional") == 0.0


# ---------------------------------------------------------------------------
# _compute_confidence
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_full_coverage(self):
        assert DivergenceEngine._compute_confidence(3, 3) == pytest.approx(1.0)

    def test_partial_coverage(self):
        assert DivergenceEngine._compute_confidence(1, 3) == pytest.approx(1 / 3)

    def test_over_coverage_capped(self):
        assert DivergenceEngine._compute_confidence(5, 3) == pytest.approx(1.0)

    def test_zero_expected(self):
        assert DivergenceEngine._compute_confidence(2, 0) == 0.0

    def test_none_available(self):
        assert DivergenceEngine._compute_confidence(0, 3) == 0.0
