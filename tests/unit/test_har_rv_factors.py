"""Unit tests for tradingagents.factors.har_rv_factors."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.factors.har_rv_factors import (
    FEATURE_NAMES,
    compute_ar1_expanding,
    compute_bpv_daily,
    compute_garman_klass_rv,
    compute_har_factors,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_ohlc() -> pd.DataFrame:
    """250 business days of synthetic OHLC data with deterministic seeds."""
    dates = pd.date_range("2024-01-01", periods=250, freq="B")
    rng = np.random.default_rng(42)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, 250)))
    high = close * (1.0 + np.abs(rng.normal(0, 0.01, 250)))
    low = close * (1.0 - np.abs(rng.normal(0, 0.01, 250)))
    open_ = close * (1.0 + rng.normal(0, 0.005, 250))
    # Ensure OHLC monotonicity: high >= max(open, close), low <= min(open, close).
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=dates,
    )


# ---------------------------------------------------------------------------
# Garman-Klass estimator
# ---------------------------------------------------------------------------


def _gk_reference(o: float, h: float, l: float, c: float) -> float:  # noqa: E741
    log_hl = math.log(h / l)
    log_co = math.log(c / o)
    gk = 0.5 * log_hl**2 - (2.0 * math.log(2.0) - 1.0) * log_co**2
    return math.sqrt(max(gk, 0.0))


def test_garman_klass_matches_hand_computed() -> None:
    ohlc = pd.DataFrame(
        {
            "open": [100.0, 50.0, 200.0],
            "high": [102.5, 50.8, 205.0],
            "low": [99.0, 49.5, 198.0],
            "close": [101.0, 50.2, 203.0],
        },
        index=pd.date_range("2024-01-01", periods=3, freq="B"),
    )
    expected = [
        _gk_reference(100.0, 102.5, 99.0, 101.0),
        _gk_reference(50.0, 50.8, 49.5, 50.2),
        _gk_reference(200.0, 205.0, 198.0, 203.0),
    ]
    got = compute_garman_klass_rv(ohlc).to_numpy()
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-15)


def test_garman_klass_non_negative_clamp() -> None:
    # Force GK < 0: H == L (log_hl = 0) but C != O (log_co != 0).
    ohlc = pd.DataFrame(
        {
            "open": [100.0],
            "high": [100.5],
            "low": [100.5],  # H == L so log_hl == 0
            "close": [101.0],  # close != open so log_co != 0 → GK strictly negative
        },
        index=pd.date_range("2024-01-01", periods=1, freq="B"),
    )
    rv = compute_garman_klass_rv(ohlc)
    assert rv.iloc[0] == 0.0
    assert np.isfinite(rv.iloc[0])


def test_garman_klass_case_insensitive_columns() -> None:
    ohlc = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
        },
        index=pd.date_range("2024-01-01", periods=1, freq="B"),
    )
    rv = compute_garman_klass_rv(ohlc)
    assert np.isfinite(rv.iloc[0])
    assert rv.iloc[0] > 0.0


# ---------------------------------------------------------------------------
# Bipower variation approximation
# ---------------------------------------------------------------------------


def test_bpv_formula_hand_computed() -> None:
    close = pd.Series(
        [100.0, 101.0, 99.0, 100.5],
        index=pd.date_range("2024-01-01", periods=4, freq="B"),
    )
    bpv = compute_bpv_daily(close)

    # First two values must be NaN.
    assert math.isnan(bpv.iloc[0])
    assert math.isnan(bpv.iloc[1])

    r1 = math.log(101.0 / 100.0)
    r2 = math.log(99.0 / 101.0)
    r3 = math.log(100.5 / 99.0)

    expected_2 = (math.pi / 2.0) * abs(r1) * abs(r2)
    expected_3 = (math.pi / 2.0) * abs(r2) * abs(r3)

    assert bpv.iloc[2] == pytest.approx(expected_2, rel=1e-12, abs=1e-15)
    assert bpv.iloc[3] == pytest.approx(expected_3, rel=1e-12, abs=1e-15)


# ---------------------------------------------------------------------------
# AR(1) expanding-window
# ---------------------------------------------------------------------------


def test_ar1_expanding_converges_to_true_coefficients() -> None:
    # Generate an AR(1) with enough x-variance for OLS identification:
    #   RV_t = 0.1 + 0.5 * RV_{t-1} + eps_t,  eps ~ N(0, sigma^2)
    # With seeded noise the estimators are deterministic and should converge
    # to the true (a=0.1, b=0.5) as the expanding window grows.
    n = 400
    rng = np.random.default_rng(7)
    rv = np.zeros(n, dtype=float)
    rv[0] = 0.2
    for t in range(1, n):
        rv[t] = 0.1 + 0.5 * rv[t - 1] + rng.normal(0.0, 0.02)

    series = pd.Series(rv, index=pd.date_range("2024-01-01", periods=n, freq="B"))
    pred, resid = compute_ar1_expanding(series, warmup=60)

    # Recover (a_hat, b_hat) implied by the final prediction.
    # pred[-1] = a_hat + b_hat * rv[-2]; pred[-2] = a_hat + b_hat * rv[-3].
    # Solving two equations recovers a and b from the last two predictions.
    p_last = pred.iloc[-1]
    p_prev = pred.iloc[-2]
    x_last = rv[-2]
    x_prev = rv[-3]
    b_hat = (p_last - p_prev) / (x_last - x_prev)
    a_hat = p_last - b_hat * x_last
    assert abs(a_hat - 0.1) < 0.02
    assert abs(b_hat - 0.5) < 0.05

    # Residuals must average close to zero in the tail (mean-zero noise).
    tail_resid = resid.iloc[-200:].dropna().to_numpy()
    assert abs(tail_resid.mean()) < 0.01


def test_ar1_warmup_boundary() -> None:
    n = 120
    rng = np.random.default_rng(0)
    rv = pd.Series(
        np.abs(rng.normal(0.02, 0.005, n)),
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )
    pred, _ = compute_ar1_expanding(rv, warmup=60)

    # Index 0 has a NaN lag, so valid (x, y) pairs start at index 1. The first
    # index t for which n_prev[t] >= 60 is t = 61 (pairs at indices 1..60).
    assert pred.iloc[:61].isna().all()
    assert not math.isnan(pred.iloc[61])


def test_ar1_residuals_are_elementwise_difference() -> None:
    n = 200
    rng = np.random.default_rng(1)
    rv = pd.Series(
        np.abs(rng.normal(0.02, 0.005, n)),
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )
    pred, resid = compute_ar1_expanding(rv, warmup=60)

    both = np.isfinite(pred) & np.isfinite(resid)
    np.testing.assert_allclose(
        resid[both].to_numpy(),
        (rv[both] - pred[both]).to_numpy(),
        rtol=0,
        atol=1e-15,
    )


# ---------------------------------------------------------------------------
# Look-ahead bias / determinism
# ---------------------------------------------------------------------------


def test_no_lookahead_prefix_identity(synthetic_ohlc: pd.DataFrame) -> None:
    first_100 = compute_har_factors(synthetic_ohlc.iloc[:100])
    first_150 = compute_har_factors(synthetic_ohlc.iloc[:150])

    # First 100 rows of both must be bit-identical (treat NaNs as equal).
    aligned = first_150.iloc[:100]
    assert first_100.shape == aligned.shape
    for col in FEATURE_NAMES:
        a = first_100[col].to_numpy()
        b = aligned[col].to_numpy()
        mask = ~(np.isnan(a) & np.isnan(b))
        np.testing.assert_allclose(a[mask], b[mask], rtol=0, atol=1e-12)


# ---------------------------------------------------------------------------
# Full pipeline shape & rolling-window behavior
# ---------------------------------------------------------------------------


def test_compute_har_factors_shape(synthetic_ohlc: pd.DataFrame) -> None:
    features = compute_har_factors(synthetic_ohlc)
    # Shape adapts to the current FEATURE_NAMES length (Tier -1 = 10, Tier 0
    # adds additional range-based / leverage columns).
    assert features.shape == (250, len(FEATURE_NAMES))
    assert tuple(features.columns) == FEATURE_NAMES
    assert features.index.equals(synthetic_ohlc.index)


def test_rolling_5d_mean_nan_handling(synthetic_ohlc: pd.DataFrame) -> None:
    features = compute_har_factors(synthetic_ohlc)
    rv = features["rv_daily"]
    rv_5d_mean = features["rv_5d_mean"]

    # First 4 values must be NaN (need 5 obs).
    assert rv_5d_mean.iloc[:4].isna().all()
    # Row 5 (index 4) must equal the mean of rows 1-5 (indices 0..4).
    expected = rv.iloc[:5].mean()
    assert rv_5d_mean.iloc[4] == pytest.approx(expected, rel=1e-12, abs=1e-15)


def test_momentum_divide_by_zero_is_nan() -> None:
    # Construct a series where the 22-day mean is exactly 0 at some point:
    # feed 22 rows of zero-range bars (H == L == O == C) so rv_daily is all 0.
    n = 30
    ohlc = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
        },
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )
    features = compute_har_factors(ohlc)
    # From row 21 onward, rv_22d_mean is 0 -> rv_momentum must be NaN, not inf.
    mom_tail = features["rv_momentum"].iloc[21:].to_numpy()
    surprise_tail = features["vol_surprise"].iloc[21:].to_numpy()
    assert np.isnan(mom_tail).all()
    assert np.isnan(surprise_tail).all()
    # Also ensure no positive/negative infinities leaked.
    assert not np.isinf(mom_tail).any()
    assert not np.isinf(surprise_tail).any()


def test_missing_column_raises() -> None:
    with pytest.raises(ValueError, match="missing required column"):
        compute_garman_klass_rv(
            pd.DataFrame(
                {"open": [1.0], "high": [2.0], "low": [0.5]},
                index=pd.date_range("2024-01-01", periods=1, freq="B"),
            )
        )
