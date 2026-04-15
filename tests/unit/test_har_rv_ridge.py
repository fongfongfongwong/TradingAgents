"""Unit tests for the HAR-RV Ridge baseline pipeline.

Covers:
    * preprocess_features (winsorization, z-score, date filtering)
    * split_by_date
    * train_ridge_model on synthetic data (coefficient recovery)
    * save_model / load_model round-trip
    * predict uses the same preprocessing as training (no leakage)
    * Trained model metadata populated correctly
    * RidgeCV selects alpha from within the provided grid
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.models.data_assembly import split_by_date
from tradingagents.models.har_rv_ridge import (
    _ALPHA_GRID,
    TrainedModel,
    load_model,
    predict,
    save_model,
    train_ridge_model,
)
from tradingagents.models.preprocessing import preprocess_features

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FEATURE_COLS: list[str] = [
    "f0", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
]
TRUE_COEFS = np.array([0.5, -0.3, 0.2, 0.1, -0.15, 0.4, -0.05, 0.25, -0.2, 0.35])


def _make_synthetic_panel(
    n_dates: int = 100,
    n_tickers: int = 20,
    noise_sigma: float = 0.05,
    seed: int = 42,
    horizon: int = 1,
) -> pd.DataFrame:
    """Build a (date, ticker) panel with linear-Gaussian features + target."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    index = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])

    n = len(index)
    X = rng.normal(0.0, 1.0, size=(n, len(FEATURE_COLS)))
    y = X @ TRUE_COEFS + rng.normal(0.0, noise_sigma, size=n)

    data = {col: X[:, i] for i, col in enumerate(FEATURE_COLS)}
    data[f"rv_next_{horizon}d"] = y
    return pd.DataFrame(data, index=index)


# ---------------------------------------------------------------------------
# preprocess_features
# ---------------------------------------------------------------------------


def test_preprocess_features_winsorizes_and_zscores_per_date() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    tickers = ["A", "B", "C", "D", "E"]
    index = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])

    # Day 1: one outlier at the end (1000) -> should be clipped.
    # Day 2: symmetric normal values.
    f_values = [1.0, 2.0, 3.0, 4.0, 1000.0, -2.0, -1.0, 0.0, 1.0, 2.0]
    panel = pd.DataFrame({"x": f_values, "other": f_values}, index=index)

    out = preprocess_features(panel, feature_cols=["x"], min_tickers=5)

    # Z-score mean ~ 0, std ~ 1 per date (outlier gets winsorized, not discarded)
    for date in dates:
        slice_ = out.xs(date, level="date")["x"]
        assert slice_.mean() == pytest.approx(0.0, abs=1e-9)
        assert slice_.std(ddof=0) == pytest.approx(1.0, abs=1e-9)

    # The outlier's post-winsorization value should be the max of its date slice.
    day1 = out.xs(dates[0], level="date")["x"]
    assert day1.loc["E"] == day1.max()
    # And it should no longer be >> the others: the 1000 gets clipped hard.
    assert abs(day1.loc["E"]) < 5.0

    # Non-listed columns are left untouched.
    assert (out["other"] == panel.loc[out.index, "other"]).all()


def test_preprocess_features_drops_dates_below_min_tickers() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    # Day 0: only 2 tickers (below min). Day 1: 5 tickers. Day 2: 3 tickers (below).
    rows: list[tuple] = []
    for d, n in zip(dates, [2, 5, 3]):
        for i in range(n):
            rows.append((d, f"T{i}"))
    index = pd.MultiIndex.from_tuples(rows, names=["date", "ticker"])
    panel = pd.DataFrame({"x": np.arange(len(index), dtype=float)}, index=index)

    out = preprocess_features(panel, feature_cols=["x"], min_tickers=5)
    kept = out.index.get_level_values("date").unique()
    assert list(kept) == [dates[1]]
    # Fewer total rows
    assert len(out) == 5


def test_preprocess_features_fills_nan_and_inf_with_zero() -> None:
    dates = pd.to_datetime(["2024-01-02"])
    tickers = ["A", "B", "C", "D", "E"]
    index = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
    # All values identical -> std=0 -> z should become 0, not NaN.
    panel = pd.DataFrame({"x": [1.0, 1.0, 1.0, 1.0, 1.0]}, index=index)
    out = preprocess_features(panel, feature_cols=["x"], min_tickers=5)
    assert (out["x"] == 0.0).all()

    # Now inject an inf -- it should be replaced with 0 post-preprocessing.
    panel2 = pd.DataFrame(
        {"x": [1.0, 2.0, 3.0, 4.0, np.inf]}, index=index
    )
    out2 = preprocess_features(panel2, feature_cols=["x"], min_tickers=5)
    assert np.isfinite(out2["x"]).all()


# ---------------------------------------------------------------------------
# split_by_date
# ---------------------------------------------------------------------------


def test_split_by_date_partitions_synthetic_panel() -> None:
    dates = pd.date_range("2023-10-01", "2024-09-30", freq="D")
    tickers = ["A", "B"]
    index = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
    panel = pd.DataFrame({"x": 1.0}, index=index)

    train, valid, test = split_by_date(
        panel, train_end="2023-12-31", valid_end="2024-06-30"
    )

    tr_dates = train.index.get_level_values("date")
    va_dates = valid.index.get_level_values("date")
    te_dates = test.index.get_level_values("date")

    assert tr_dates.max() == pd.Timestamp("2023-12-31")
    assert va_dates.min() == pd.Timestamp("2024-01-01")
    assert va_dates.max() == pd.Timestamp("2024-06-30")
    assert te_dates.min() == pd.Timestamp("2024-07-01")

    # No overlap; union == original
    total = len(train) + len(valid) + len(test)
    assert total == len(panel)


# ---------------------------------------------------------------------------
# train_ridge_model / predict / save-load
# ---------------------------------------------------------------------------


def test_train_ridge_model_recovers_coefficients() -> None:
    panel = _make_synthetic_panel(n_dates=150, n_tickers=25, noise_sigma=0.05, seed=7)

    model = train_ridge_model(panel, horizon=1, feature_cols=FEATURE_COLS, target_transform="raw")

    assert isinstance(model, TrainedModel)
    assert model.horizon == 1
    assert model.feature_names == tuple(FEATURE_COLS)
    assert model.alpha in _ALPHA_GRID  # chosen from the provided grid
    assert model.train_rows > 0
    assert model.trained_at.endswith("Z")
    # Parseable ISO dates for train window
    _dt.date.fromisoformat(model.train_start)
    _dt.date.fromisoformat(model.train_end)

    # Coefficient recovery: Ridge shrinks a bit but should be close to truth
    # after the features have been z-scored (unit variance) per date.
    recovered = model.ridge.coef_
    # Ridge with CV picks a small alpha on easy data; correlation should be high.
    corr = np.corrcoef(recovered, TRUE_COEFS)[0, 1]
    assert corr > 0.97, f"Coefficient correlation too low: {corr}"

    # Ridge predictions on training data should have high R^2.
    from tradingagents.models.har_rv_ridge import predict as _pred

    preds = _pred(model, panel.drop(columns=["rv_next_1d"]))
    y_true = panel.loc[preds.index, "rv_next_1d"]
    ss_res = ((y_true - preds) ** 2).sum()
    ss_tot = ((y_true - y_true.mean()) ** 2).sum()
    r2 = 1.0 - ss_res / ss_tot
    assert r2 > 0.9, f"In-sample R^2 too low: {r2}"


def test_ridge_alpha_selected_from_grid() -> None:
    panel = _make_synthetic_panel(n_dates=80, n_tickers=15, noise_sigma=0.1, seed=11)
    model = train_ridge_model(panel, horizon=1, feature_cols=FEATURE_COLS)
    assert float(model.alpha) in set(_ALPHA_GRID)


def test_save_and_load_model_roundtrip(tmp_path: Path) -> None:
    panel = _make_synthetic_panel(n_dates=60, n_tickers=12, seed=3)
    model = train_ridge_model(panel, horizon=1, feature_cols=FEATURE_COLS)

    path = tmp_path / "har_rv_ridge_1d.joblib"
    returned_path = save_model(model, path=path)
    assert returned_path == path
    assert path.exists()

    loaded = load_model(horizon=1, path=path)
    assert loaded is not None
    assert loaded.alpha == model.alpha
    assert loaded.feature_names == model.feature_names
    assert loaded.train_rows == model.train_rows
    assert loaded.trained_at == model.trained_at

    # Predictions should be bitwise-identical on the same input.
    feats = panel.drop(columns=["rv_next_1d"])
    p1 = predict(model, feats)
    p2 = predict(loaded, feats)
    pd.testing.assert_series_equal(p1, p2)


def test_load_model_returns_none_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "does_not_exist.joblib"
    assert load_model(horizon=1, path=path) is None


def test_predict_applies_same_preprocessing_as_training() -> None:
    """Verify predict runs the same cross-sectional winsorize+zscore pipeline
    as training by checking that it is invariant to affine rescaling of raw
    inputs (since z-scoring removes scale/location per date).
    """
    panel = _make_synthetic_panel(n_dates=60, n_tickers=20, seed=99)
    model = train_ridge_model(panel, horizon=1, feature_cols=FEATURE_COLS)

    feats = panel.drop(columns=["rv_next_1d"])

    # Rescale each feature by a different constant and add an offset.
    # After cross-sectional z-scoring this transformation should leave
    # predictions unchanged (modulo numerical precision and the fact that
    # winsorization thresholds scale with MAD -- which is equivariant
    # under affine transforms).
    rng = np.random.default_rng(0)
    scales = rng.uniform(0.5, 2.0, size=len(FEATURE_COLS))
    offsets = rng.uniform(-5.0, 5.0, size=len(FEATURE_COLS))
    feats_rescaled = feats.copy()
    for i, col in enumerate(FEATURE_COLS):
        feats_rescaled[col] = feats_rescaled[col] * scales[i] + offsets[i]

    p_original = predict(model, feats)
    p_rescaled = predict(model, feats_rescaled)

    # Same index
    assert p_original.index.equals(p_rescaled.index)
    # Same values (cross-sectional z-score absorbs affine rescaling)
    np.testing.assert_allclose(
        p_original.to_numpy(), p_rescaled.to_numpy(), rtol=1e-9, atol=1e-9
    )


def test_trained_model_metadata_populated() -> None:
    panel = _make_synthetic_panel(n_dates=50, n_tickers=10, seed=1, horizon=5)
    model = train_ridge_model(panel, horizon=5, feature_cols=FEATURE_COLS)

    assert model.horizon == 5
    assert model.train_rows == 50 * 10  # no NaNs in the synthetic data
    assert model.train_start <= model.train_end
    assert len(model.feature_names) == 10
    # trained_at is a UTC ISO timestamp
    assert "T" in model.trained_at and model.trained_at.endswith("Z")
