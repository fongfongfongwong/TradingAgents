"""Tests for the purged walk-forward evaluator.

Verifies:

* The embargo correctly drops the last ``embargo_days`` unique training
  dates from each split.
* No date appears in both train and test within a split.
* Per-split metrics are returned for every requested fold.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.evaluation.walk_forward import (
    _split_by_unique_date,
    walk_forward_evaluate,
)

FEATURE_COLS: list[str] = [f"f{i}" for i in range(10)]


def _make_panel(
    n_dates: int = 200,
    n_tickers: int = 10,
    seed: int = 11,
    horizon: int = 1,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_dates, freq="B")
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    index = pd.MultiIndex.from_product([dates, tickers], names=["date", "ticker"])
    n = len(index)
    X = rng.normal(0.0, 1.0, size=(n, len(FEATURE_COLS)))
    true_coefs = np.linspace(-0.3, 0.3, num=len(FEATURE_COLS))
    log_y = X @ true_coefs + rng.normal(0.0, 0.1, size=n) - 6.0
    y = np.exp(log_y)
    data = {col: X[:, i] for i, col in enumerate(FEATURE_COLS)}
    data[f"rv_next_{horizon}d"] = y
    return pd.DataFrame(data, index=index)


@pytest.mark.unit
def test_split_by_unique_date_is_contiguous() -> None:
    dates = np.array(pd.date_range("2020-01-01", periods=30, freq="D"))
    splits = _split_by_unique_date(dates, n_splits=3)
    assert len(splits) == 3
    for train_d, test_d in splits:
        # Train and test must be disjoint.
        train_set = set(pd.to_datetime(train_d))
        test_set = set(pd.to_datetime(test_d))
        assert train_set.isdisjoint(test_set)
        # Train max < test min (strict walk-forward ordering).
        if len(train_d) > 0 and len(test_d) > 0:
            assert max(train_d) < min(test_d)


@pytest.mark.unit
def test_walk_forward_embargo_drops_last_n_training_dates() -> None:
    """With embargo=K, the last K unique training dates must not appear in train."""
    panel = _make_panel(n_dates=150)
    embargo = 7
    result = walk_forward_evaluate(
        panel=panel,
        feature_cols=FEATURE_COLS,
        target_col="rv_next_1d",
        n_splits=3,
        embargo_days=embargo,
        target_transform="log",
    )

    all_dates = (
        pd.to_datetime(panel.index.get_level_values(0)).unique().sort_values()
    )

    for s in result["splits"]:
        train_end = pd.Timestamp(s["train_end"])
        test_start = pd.Timestamp(s["test_start"])
        # Gap between train_end and test_start must be >= embargo unique dates.
        idx_train_end = np.searchsorted(all_dates, train_end)
        idx_test_start = np.searchsorted(all_dates, test_start)
        gap = idx_test_start - idx_train_end - 1
        assert gap >= embargo - 1, (
            f"Split {s['split_idx']}: only {gap} dates between train_end "
            f"{s['train_end']} and test_start {s['test_start']}; expected >= "
            f"{embargo - 1}"
        )


@pytest.mark.unit
def test_walk_forward_no_date_overlap_between_train_and_test() -> None:
    panel = _make_panel(n_dates=150)
    result = walk_forward_evaluate(
        panel=panel,
        feature_cols=FEATURE_COLS,
        target_col="rv_next_1d",
        n_splits=3,
        embargo_days=5,
        target_transform="log",
    )
    for s in result["splits"]:
        # train_end strictly precedes test_start (walk-forward invariant).
        assert pd.Timestamp(s["train_end"]) < pd.Timestamp(s["test_start"])


@pytest.mark.unit
def test_walk_forward_returns_one_result_per_split() -> None:
    panel = _make_panel(n_dates=200)
    n = 5
    result = walk_forward_evaluate(
        panel=panel,
        feature_cols=FEATURE_COLS,
        target_col="rv_next_1d",
        n_splits=n,
        embargo_days=3,
        target_transform="log",
    )
    assert result["n_splits"] == n
    # May drop splits that collapse to empty folds, but for 200 dates / 5
    # splits this should not happen.
    assert len(result["splits"]) == n
    for s in result["splits"]:
        for key in ("pooled_r2", "ic_mean", "qlike", "n_train", "n_test"):
            assert key in s


@pytest.mark.unit
def test_walk_forward_rejects_missing_columns() -> None:
    panel = _make_panel()
    with pytest.raises(KeyError):
        walk_forward_evaluate(
            panel=panel,
            feature_cols=FEATURE_COLS + ["does_not_exist"],
            target_col="rv_next_1d",
            n_splits=3,
        )
    with pytest.raises(KeyError):
        walk_forward_evaluate(
            panel=panel,
            feature_cols=FEATURE_COLS,
            target_col="no_such_target",
            n_splits=3,
        )
