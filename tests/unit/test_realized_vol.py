"""Unit tests for :func:`tradingagents.data.materializer._compute_realized_vol_20d`.

Covers the annualized 20-day realized volatility helper used by the v3
signals table. The helper returns ``None`` when there are insufficient bars
(fewer than 21 closes -- need 21 to form 20 log-returns), ``0.0`` when the
window is flat, and a positive float otherwise.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tradingagents.data.materializer import _compute_realized_vol_20d


@pytest.mark.unit
def test_insufficient_data_returns_none() -> None:
    """Fewer than 21 closes -> not enough to form 20 log returns."""
    assert _compute_realized_vol_20d([]) is None
    assert _compute_realized_vol_20d([100.0]) is None
    assert _compute_realized_vol_20d([100.0] * 20) is None


@pytest.mark.unit
def test_flat_series_is_zero() -> None:
    """A flat 21-bar series has zero log-return variance -> 0.0."""
    closes = [100.0] * 21
    result = _compute_realized_vol_20d(closes)
    assert result == 0.0


@pytest.mark.unit
def test_known_series_matches_numpy_reference() -> None:
    """Compare against an independent numpy computation for a deterministic series."""
    rng = np.random.default_rng(seed=1234)
    # Generate 30 closes via a geometric random walk around 100.
    shocks = rng.normal(loc=0.0, scale=0.02, size=30)
    closes = [100.0]
    for s in shocks:
        closes.append(closes[-1] * math.exp(float(s)))

    result = _compute_realized_vol_20d(closes)
    assert result is not None

    # Reference: last 21 closes -> 20 log returns -> sample stdev -> annualize.
    arr = np.asarray(closes[-21:], dtype=float)
    log_returns = np.diff(np.log(arr))
    expected = float(np.std(log_returns, ddof=1)) * math.sqrt(252.0) * 100.0
    assert result == pytest.approx(expected, rel=1e-6, abs=1e-6)


@pytest.mark.unit
def test_non_positive_price_in_window_returns_none() -> None:
    """Guard against ``log`` of a non-positive value blowing up."""
    closes = [100.0] * 20 + [0.0]
    assert _compute_realized_vol_20d(closes) is None


@pytest.mark.unit
def test_only_last_21_bars_used() -> None:
    """Earlier history outside the 21-bar window must not affect the result."""
    tail = [100.0 * (1.01 ** i) for i in range(21)]
    long_series = [1.0, 2.0, 3.0, 4.0] + tail
    assert _compute_realized_vol_20d(long_series) == pytest.approx(
        _compute_realized_vol_20d(tail)
    )
