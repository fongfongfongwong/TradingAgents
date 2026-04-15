"""Tier 0 inference-path tests for the HAR-RV Ridge forecast wiring.

Covers the defensive logic added by build agent T0-4:

1. Legacy models (10 baseline features, no ``target_transform``) must still
   load, predict, and produce sensible values even when the ambient
   ``har_rv_factors`` module has been upgraded to emit Tier 0 columns.
2. When the loaded model's ``feature_names`` include Tier 0 columns, those
   columns should flow through to ``predict()``.
3. ``target_transform == "log"`` must invert via ``np.exp`` exactly once.
4. Unknown options-context fields must gracefully become NaN rather than
   crashing ``_align_features_to_model``.
"""

from __future__ import annotations

import math
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tradingagents.api.routes.rv_forecast import (
    _align_features_to_model,
    _compute_features_for_ticker,
    _invert_target_transform,
    _predict_with_model,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_LEGACY_COLS: tuple[str, ...] = (
    "rv_daily",
    "rv_5d_mean",
    "rv_22d_mean",
    "bpv_daily",
    "rv_momentum",
    "vol_surprise",
    "rv_5d_std",
    "rv_22d_std",
    "rv_ar1_pred",
    "rv_ar1_resid",
)

_TIER0_COLS: tuple[str, ...] = (
    "rv_parkinson",
    "rv_rs",
    "rv_yz",
    "rv_overnight",
    "rv_oc",
    "r_neg_d",
    "r_neg_5d",
    "r_neg_22d",
)


class _FakeRidge:
    """Minimal stand-in for ``sklearn.linear_model.RidgeCV``."""

    def __init__(self, coef_per_col: float = 0.01) -> None:
        self._coef = coef_per_col

    def predict(self, X: np.ndarray) -> np.ndarray:
        # Simple linear sum so we can reason about the output scale.
        return X.sum(axis=1) * self._coef + 0.0001


class _FakeModel:
    """Stand-in for ``tradingagents.models.har_rv_ridge.TrainedModel``.

    Holds only the attributes the inference path touches.
    """

    def __init__(
        self,
        feature_names: tuple[str, ...],
        *,
        target_transform: str | None = None,
        feature_set_version: str | None = None,
        horizon: int = 1,
        raw_prediction: float = 0.015,
    ) -> None:
        self.feature_names = feature_names
        self.target_transform = target_transform
        self.feature_set_version = feature_set_version
        self.horizon = horizon
        self.trained_at = "2026-04-01T00:00:00Z"
        self.train_rows = 1000
        self.alpha = 10.0
        # Not used when we stub predict, but kept for shape parity.
        self.ridge = _FakeRidge()
        self._raw_prediction = raw_prediction


def _legacy_model() -> _FakeModel:
    return _FakeModel(feature_names=_LEGACY_COLS)


def _tier0_model() -> _FakeModel:
    return _FakeModel(
        feature_names=_LEGACY_COLS + _TIER0_COLS,
        feature_set_version="tier0",
    )


def _options_model() -> _FakeModel:
    return _FakeModel(
        feature_names=_LEGACY_COLS + ("iv_skew_25d", "iv_rank_percentile"),
        feature_set_version="tier0",
    )


def _make_feature_row(
    columns: tuple[str, ...], value: float = 0.02
) -> pd.DataFrame:
    """Build a 1-row MultiIndex panel mimicking the output of compute_har_factors."""
    data = {c: [value] for c in columns}
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-04-04"), "AAPL")], names=["date", "ticker"]
    )
    return pd.DataFrame(data, index=idx)


class _StubOptionsContext:
    """Lightweight duck-type for OptionsContext.

    Only the attributes the alignment helper reads are defined; missing
    attributes are exercised via ``getattr(..., None)``.
    """

    def __init__(
        self,
        iv_skew_25d: float | None = None,
        iv_rank_percentile: float | None = None,
        put_call_ratio: float | None = None,
    ) -> None:
        self.iv_skew_25d = iv_skew_25d
        self.iv_rank_percentile = iv_rank_percentile
        self.put_call_ratio = put_call_ratio
        # Deliberately do NOT define iv_level_30d so the getattr fallback is
        # exercised.


# ---------------------------------------------------------------------------
# Test 1: legacy model against Tier 0-enriched features
# ---------------------------------------------------------------------------


def test_align_features_drops_tier0_columns_for_legacy_model() -> None:
    """Legacy model only knows 10 columns; Tier 0 extras must be dropped."""
    features = _make_feature_row(_LEGACY_COLS + _TIER0_COLS)
    model = _legacy_model()

    aligned = _align_features_to_model(features, model)

    assert tuple(aligned.columns) == _LEGACY_COLS
    # Every Tier 0 column is gone.
    for col in _TIER0_COLS:
        assert col not in aligned.columns


def test_compute_features_for_ticker_falls_back_to_legacy_when_tier0_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate an early-round factor module that emits only legacy columns.

    The loaded model knows only legacy columns too, so the full pipeline
    must still return a single aligned row.
    """

    class _FakeYFTicker:
        def history(self, period: str, auto_adjust: bool) -> pd.DataFrame:
            rng = pd.date_range(end="2026-04-04", periods=120, freq="B")
            return pd.DataFrame(
                {
                    "Open": np.linspace(100.0, 110.0, len(rng)),
                    "High": np.linspace(101.0, 111.0, len(rng)),
                    "Low": np.linspace(99.0, 109.0, len(rng)),
                    "Close": np.linspace(100.5, 110.5, len(rng)),
                    "Volume": np.full(len(rng), 1_000_000),
                },
                index=rng,
            )

    fake_yf = types.SimpleNamespace(Ticker=lambda sym: _FakeYFTicker())
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake_yf)

    def _fake_compute_har_factors(ohlc: pd.DataFrame) -> pd.DataFrame:
        # Emit ONLY legacy columns -- simulates early-round factor module.
        return pd.DataFrame(
            {c: np.full(len(ohlc), 0.02) for c in _LEGACY_COLS},
            index=ohlc.index,
        )

    import tradingagents.factors.har_rv_factors as factors_mod  # type: ignore

    monkeypatch.setattr(
        factors_mod, "compute_har_factors", _fake_compute_har_factors
    )
    # Also override FEATURE_NAMES to the legacy-only tuple so the NaN gate
    # matches the stubbed factor output.
    monkeypatch.setattr(factors_mod, "FEATURE_NAMES", _LEGACY_COLS)

    model = _legacy_model()
    result = _compute_features_for_ticker("AAPL", model=model)

    assert result is not None
    assert tuple(result.columns) == _LEGACY_COLS
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Test 2: model that knows Tier 0 columns gets them populated
# ---------------------------------------------------------------------------


def test_align_features_passes_tier0_columns_to_tier0_model() -> None:
    features = _make_feature_row(_LEGACY_COLS + _TIER0_COLS, value=0.03)
    model = _tier0_model()

    aligned = _align_features_to_model(features, model)

    assert set(aligned.columns) == set(_LEGACY_COLS + _TIER0_COLS)
    for col in _TIER0_COLS:
        # Values were copied across, not silently NaN'd.
        assert not math.isnan(float(aligned[col].iloc[0]))
        assert float(aligned[col].iloc[0]) == pytest.approx(0.03)


def test_align_features_fills_missing_columns_with_nan() -> None:
    """Model expects Tier 0 but factor frame lacks them -- must become NaN."""
    features = _make_feature_row(_LEGACY_COLS)  # no tier 0 cols
    model = _tier0_model()

    aligned = _align_features_to_model(features, model)

    assert set(aligned.columns) == set(_LEGACY_COLS + _TIER0_COLS)
    for col in _TIER0_COLS:
        assert math.isnan(float(aligned[col].iloc[0]))


# ---------------------------------------------------------------------------
# Test 3: log-target inversion applied exactly once
# ---------------------------------------------------------------------------


def test_invert_target_transform_log_applies_exp_once() -> None:
    raw = math.log(0.025)  # pretend training space was log
    model = _FakeModel(
        feature_names=_LEGACY_COLS, target_transform="log"
    )

    inverted = _invert_target_transform(raw, model)

    assert inverted == pytest.approx(0.025, rel=1e-9)


def test_invert_target_transform_raw_is_identity() -> None:
    model_none = _FakeModel(feature_names=_LEGACY_COLS, target_transform=None)
    model_raw = _FakeModel(feature_names=_LEGACY_COLS, target_transform="raw")

    assert _invert_target_transform(0.02, model_none) == 0.02
    assert _invert_target_transform(0.02, model_raw) == 0.02


def test_invert_target_transform_unknown_falls_back_to_raw() -> None:
    model = _FakeModel(
        feature_names=_LEGACY_COLS, target_transform="boxcox-unknown"
    )
    assert _invert_target_transform(0.02, model) == 0.02


def test_predict_with_model_applies_log_inversion_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_predict_with_model should call predict then invert exactly once."""
    call_counter = {"invert": 0, "predict": 0}

    def _fake_predict(model: Any, features: pd.DataFrame) -> pd.Series:
        call_counter["predict"] += 1
        return pd.Series([math.log(0.05)])

    import tradingagents.models.har_rv_ridge as ridge_mod

    monkeypatch.setattr(ridge_mod, "predict", _fake_predict)

    model = _FakeModel(feature_names=_LEGACY_COLS, target_transform="log")
    features = _make_feature_row(_LEGACY_COLS)

    result = _predict_with_model(model, features)

    assert result is not None
    assert result == pytest.approx(0.05, rel=1e-9)
    assert call_counter["predict"] == 1


# ---------------------------------------------------------------------------
# Test 4: unknown / missing options-context fields become NaN
# ---------------------------------------------------------------------------


def test_align_features_with_missing_options_fields_produces_nan() -> None:
    """Model expects iv_level_30d but OptionsContext stub does not define it."""
    features = _make_feature_row(_LEGACY_COLS)
    model = _FakeModel(
        feature_names=_LEGACY_COLS + ("iv_skew_25d", "iv_level_30d"),
        feature_set_version="tier0",
    )
    options_ctx = _StubOptionsContext(
        iv_skew_25d=0.12,  # present
        iv_rank_percentile=55.0,  # not in model.feature_names, must be ignored
    )

    aligned = _align_features_to_model(features, model, options_ctx=options_ctx)

    assert "iv_skew_25d" in aligned.columns
    assert float(aligned["iv_skew_25d"].iloc[0]) == pytest.approx(0.12)
    assert "iv_level_30d" in aligned.columns
    assert math.isnan(float(aligned["iv_level_30d"].iloc[0]))
    # iv_rank_percentile is not part of the model's feature set and must be absent.
    assert "iv_rank_percentile" not in aligned.columns


def test_align_features_with_none_options_context_does_not_crash() -> None:
    features = _make_feature_row(_LEGACY_COLS)
    model = _options_model()

    aligned = _align_features_to_model(features, model, options_ctx=None)

    # iv_skew_25d / iv_rank_percentile are expected by the model but no
    # options_ctx was supplied, so they must be present as NaN.
    assert "iv_skew_25d" in aligned.columns
    assert math.isnan(float(aligned["iv_skew_25d"].iloc[0]))
    assert "iv_rank_percentile" in aligned.columns
    assert math.isnan(float(aligned["iv_rank_percentile"].iloc[0]))


# ---------------------------------------------------------------------------
# Parity check: materializer helpers expose the same semantics
# ---------------------------------------------------------------------------


def test_materializer_align_and_invert_parity() -> None:
    """The materializer ships its own copies of these helpers; sanity check
    that they agree on a simple case so the two inference entry points stay
    in lock-step."""
    from tradingagents.data.materializer import (
        _align_features_to_model as mat_align,
        _invert_target_transform as mat_invert,
    )

    features = _make_feature_row(_LEGACY_COLS + _TIER0_COLS)
    model = _legacy_model()

    aligned_api = _align_features_to_model(features, model)
    aligned_mat = mat_align(features, model)

    assert tuple(aligned_api.columns) == tuple(aligned_mat.columns)
    assert aligned_api.equals(aligned_mat)

    log_model = _FakeModel(feature_names=_LEGACY_COLS, target_transform="log")
    assert mat_invert(math.log(0.03), log_model) == pytest.approx(0.03)
    assert _invert_target_transform(math.log(0.03), log_model) == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# Schema smoke test for the new VolatilityContext field
# ---------------------------------------------------------------------------


def test_volatility_context_accepts_feature_set_version_field() -> None:
    from tradingagents.schemas.v3 import VolatilityContext

    ctx = VolatilityContext(rv_forecast_feature_set_version="tier0")
    assert ctx.rv_forecast_feature_set_version == "tier0"

    default = VolatilityContext()
    assert default.rv_forecast_feature_set_version is None
