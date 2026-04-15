"""Tier 0 unit tests for tradingagents.factors.har_rv_factors.

Covers the Parkinson, Rogers-Satchell, Yang-Zhang, overnight, open-to-close,
and Corsi-Reno LHAR leverage features. Also contains a regression check that
the Tier -1 (legacy) feature values are unchanged by the Tier 0 extension.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.factors.har_rv_factors import (
    FEATURE_NAMES,
    LEGACY_FEATURE_NAMES,
    TIER0_FEATURE_NAMES,
    _PARKINSON_COEF,
    _yang_zhang_k,
    compute_har_factors,
    compute_leverage_features,
    compute_open_to_close_variance,
    compute_overnight_variance,
    compute_parkinson_rv,
    compute_rogers_satchell_rv,
    compute_yang_zhang_rv,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_ohlc() -> pd.DataFrame:
    """100 business days of deterministic synthetic OHLC data."""
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    rng = np.random.default_rng(7)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, 100)))
    high = close * (1.0 + np.abs(rng.normal(0, 0.01, 100)))
    low = close * (1.0 - np.abs(rng.normal(0, 0.01, 100)))
    open_ = close * (1.0 + rng.normal(0, 0.005, 100))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=dates,
    )


@pytest.fixture
def constant_ohlc() -> pd.DataFrame:
    """100 rows where O == H == L == C -- every variance estimator must be 0."""
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    price = np.full(100, 50.0)
    return pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price},
        index=dates,
    )


# ---------------------------------------------------------------------------
# FEATURE_NAMES contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_feature_names_extends_legacy_in_order() -> None:
    """Legacy features remain at the head in their original order."""
    assert FEATURE_NAMES[: len(LEGACY_FEATURE_NAMES)] == LEGACY_FEATURE_NAMES
    assert FEATURE_NAMES[len(LEGACY_FEATURE_NAMES) :] == TIER0_FEATURE_NAMES
    assert len(FEATURE_NAMES) == len(LEGACY_FEATURE_NAMES) + len(TIER0_FEATURE_NAMES)
    # Legacy count is locked at 10 to catch accidental reordering.
    assert len(LEGACY_FEATURE_NAMES) == 10
    assert len(TIER0_FEATURE_NAMES) == 8


# ---------------------------------------------------------------------------
# Constant OHLC -> every estimator is zero
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parkinson_zero_on_constant(constant_ohlc: pd.DataFrame) -> None:
    rv = compute_parkinson_rv(constant_ohlc)
    assert (rv == 0.0).all()
    assert rv.name == "rv_parkinson"


@pytest.mark.unit
def test_rogers_satchell_zero_on_constant(constant_ohlc: pd.DataFrame) -> None:
    rv = compute_rogers_satchell_rv(constant_ohlc)
    assert (rv == 0.0).all()
    assert rv.name == "rv_rs"


@pytest.mark.unit
def test_overnight_zero_on_constant(constant_ohlc: pd.DataFrame) -> None:
    rv = compute_overnight_variance(constant_ohlc)
    # First row is NaN (no previous close); rest must be zero.
    assert math.isnan(rv.iloc[0])
    assert (rv.iloc[1:] == 0.0).all()


@pytest.mark.unit
def test_open_to_close_zero_on_constant(constant_ohlc: pd.DataFrame) -> None:
    rv = compute_open_to_close_variance(constant_ohlc)
    assert (rv == 0.0).all()


@pytest.mark.unit
def test_yang_zhang_zero_on_constant(constant_ohlc: pd.DataFrame) -> None:
    rv = compute_yang_zhang_rv(constant_ohlc, window=22)
    # First 22 rows need history -> NaN; remainder should be exactly 0.
    assert rv.iloc[:22].isna().all()
    assert (rv.iloc[22:] == 0.0).all()


# ---------------------------------------------------------------------------
# Hand-verified formula checks on a tiny frame
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parkinson_formula_hand_verified() -> None:
    ohlc = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
        }
    )
    rv = compute_parkinson_rv(ohlc)
    expected_0 = (math.log(102.0 / 99.0) ** 2) / (4.0 * math.log(2.0))
    expected_1 = (math.log(103.0 / 100.0) ** 2) / (4.0 * math.log(2.0))
    assert rv.iloc[0] == pytest.approx(expected_0, rel=1e-12)
    assert rv.iloc[1] == pytest.approx(expected_1, rel=1e-12)
    # Sanity: coefficient constant matches the formula.
    assert _PARKINSON_COEF == pytest.approx(1.0 / (4.0 * math.log(2.0)), rel=1e-15)


@pytest.mark.unit
def test_rogers_satchell_formula_hand_verified() -> None:
    o, h, l, c = 100.0, 105.0, 98.0, 102.0
    ohlc = pd.DataFrame({"open": [o], "high": [h], "low": [l], "close": [c]})
    rv = compute_rogers_satchell_rv(ohlc)
    expected = math.log(h / c) * math.log(h / o) + math.log(l / c) * math.log(l / o)
    assert rv.iloc[0] == pytest.approx(expected, rel=1e-12)


@pytest.mark.unit
def test_overnight_and_oc_formula_hand_verified() -> None:
    ohlc = pd.DataFrame(
        {
            "open": [100.0, 103.0],
            "high": [105.0, 106.0],
            "low": [99.0, 101.0],
            "close": [102.0, 104.0],
        }
    )
    overnight = compute_overnight_variance(ohlc)
    oc = compute_open_to_close_variance(ohlc)
    # Row 0: overnight is NaN (no previous close).
    assert math.isnan(overnight.iloc[0])
    assert overnight.iloc[1] == pytest.approx(math.log(103.0 / 102.0) ** 2, rel=1e-12)
    assert oc.iloc[0] == pytest.approx(math.log(102.0 / 100.0) ** 2, rel=1e-12)
    assert oc.iloc[1] == pytest.approx(math.log(104.0 / 103.0) ** 2, rel=1e-12)


# ---------------------------------------------------------------------------
# Yang-Zhang k parameter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_yang_zhang_k_matches_formula() -> None:
    for n in (5, 10, 22, 66):
        expected = 0.34 / (1.34 + (n + 1.0) / (n - 1.0))
        assert _yang_zhang_k(n) == pytest.approx(expected, rel=1e-15)
    # n=22 numerical reference.
    assert _yang_zhang_k(22) == pytest.approx(0.34 / (1.34 + 23.0 / 21.0), rel=1e-15)


@pytest.mark.unit
def test_yang_zhang_k_rejects_small_n() -> None:
    with pytest.raises(ValueError):
        _yang_zhang_k(1)


# ---------------------------------------------------------------------------
# Leverage (Corsi-Reno LHAR) features
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_r_neg_d_always_non_positive(synthetic_ohlc: pd.DataFrame) -> None:
    r_neg, r_neg_5, r_neg_22 = compute_leverage_features(synthetic_ohlc["close"])
    finite = r_neg.dropna()
    assert (finite <= 0.0).all()
    # Rolling means of a non-positive series remain non-positive.
    assert (r_neg_5.dropna() <= 0.0).all()
    assert (r_neg_22.dropna() <= 0.0).all()


@pytest.mark.unit
def test_r_neg_d_clamps_positive_returns_to_zero() -> None:
    # Monotonically increasing close => every log return > 0 => r_neg_d == 0.
    close = pd.Series([100.0, 101.0, 102.5, 104.0, 105.2])
    r_neg, _, _ = compute_leverage_features(close)
    # First value is NaN (no previous close).
    assert math.isnan(r_neg.iloc[0])
    assert (r_neg.iloc[1:] == 0.0).all()


@pytest.mark.unit
def test_r_neg_d_preserves_negative_returns() -> None:
    close = pd.Series([100.0, 99.0, 98.0])  # both returns negative
    r_neg, _, _ = compute_leverage_features(close)
    assert r_neg.iloc[1] == pytest.approx(math.log(99.0 / 100.0), rel=1e-12)
    assert r_neg.iloc[2] == pytest.approx(math.log(98.0 / 99.0), rel=1e-12)


# ---------------------------------------------------------------------------
# Regression: Tier 0 does not change Tier -1 values
# ---------------------------------------------------------------------------


def _compute_legacy_only(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Reimplement the Tier -1 factor block inline so the test is independent
    of any future refactor of compute_har_factors."""
    from tradingagents.factors.har_rv_factors import (
        compute_ar1_expanding,
        compute_bpv_daily,
        compute_garman_klass_rv,
    )

    close = ohlc["close"].astype(float)
    rv_daily = compute_garman_klass_rv(ohlc)
    bpv_daily = compute_bpv_daily(close)
    rv_5d_mean = rv_daily.rolling(window=5, min_periods=5).mean()
    rv_22d_mean = rv_daily.rolling(window=22, min_periods=22).mean()
    rv_5d_std = rv_daily.rolling(window=5, min_periods=5).std(ddof=0)
    rv_22d_std = rv_daily.rolling(window=22, min_periods=22).std(ddof=0)
    safe_22 = rv_22d_mean.where(rv_22d_mean > 0.0)
    rv_momentum = rv_5d_mean / safe_22
    vol_surprise = rv_daily / safe_22
    ar1_pred, ar1_resid = compute_ar1_expanding(rv_daily, warmup=60)
    return pd.DataFrame(
        {
            "rv_daily": rv_daily,
            "rv_5d_mean": rv_5d_mean,
            "rv_22d_mean": rv_22d_mean,
            "bpv_daily": bpv_daily,
            "rv_momentum": rv_momentum,
            "vol_surprise": vol_surprise,
            "rv_5d_std": rv_5d_std,
            "rv_22d_std": rv_22d_std,
            "rv_ar1_pred": ar1_pred,
            "rv_ar1_resid": ar1_resid,
        },
        index=ohlc.index,
    )


@pytest.mark.unit
def test_tier0_does_not_change_legacy_values(synthetic_ohlc: pd.DataFrame) -> None:
    all_features = compute_har_factors(synthetic_ohlc)
    # Output must contain every name in FEATURE_NAMES in order.
    assert list(all_features.columns) == list(FEATURE_NAMES)

    legacy_actual = all_features[list(LEGACY_FEATURE_NAMES)]
    legacy_expected = _compute_legacy_only(synthetic_ohlc)[list(LEGACY_FEATURE_NAMES)]
    pd.testing.assert_frame_equal(legacy_actual, legacy_expected, check_exact=True)


# ---------------------------------------------------------------------------
# NaN propagation on missing data
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_nan_propagation_on_missing_high(synthetic_ohlc: pd.DataFrame) -> None:
    dirty = synthetic_ohlc.copy()
    dirty.iloc[10, dirty.columns.get_loc("high")] = np.nan

    rv_park = compute_parkinson_rv(dirty)
    rv_rs = compute_rogers_satchell_rv(dirty)
    assert math.isnan(rv_park.iloc[10])
    assert math.isnan(rv_rs.iloc[10])

    # Surrounding rows must remain finite.
    assert np.isfinite(rv_park.iloc[9])
    assert np.isfinite(rv_park.iloc[11])


@pytest.mark.unit
def test_nan_propagation_on_non_positive_price() -> None:
    # Zero / negative prices must not crash -- they propagate NaN.
    ohlc = pd.DataFrame(
        {
            "open": [100.0, 0.0, 101.0],
            "high": [101.0, 1.0, 102.0],
            "low": [99.0, 0.0, 100.0],
            "close": [100.5, 0.5, 101.5],
        }
    )
    rv_park = compute_parkinson_rv(ohlc)
    rv_rs = compute_rogers_satchell_rv(ohlc)
    oc = compute_open_to_close_variance(ohlc)
    overnight = compute_overnight_variance(ohlc)

    assert math.isnan(rv_park.iloc[1])  # log(1/0) undefined
    assert math.isnan(rv_rs.iloc[1])
    assert math.isnan(oc.iloc[1])
    # Overnight on row 2 uses previous close 0.5 -- finite; but row 1 uses prev 100 -> log(0/100) NaN.
    assert math.isnan(overnight.iloc[1])
    # Row 2 finite.
    assert np.isfinite(rv_park.iloc[2])


@pytest.mark.unit
def test_compute_har_factors_shape_and_nan_leading_rows(
    synthetic_ohlc: pd.DataFrame,
) -> None:
    features = compute_har_factors(synthetic_ohlc)
    assert features.shape == (len(synthetic_ohlc), len(FEATURE_NAMES))
    # Yang-Zhang needs >= 22 prior bars; rolling r_neg_22d likewise.
    assert features["rv_yz"].iloc[:22].isna().all()
    assert features["r_neg_22d"].iloc[:22].isna().all()
    # After sufficient history, Tier 0 features should be finite on most rows.
    tail = features.iloc[30:]
    assert tail["rv_parkinson"].notna().all()
    assert tail["rv_rs"].notna().all()
    assert tail["rv_oc"].notna().all()
