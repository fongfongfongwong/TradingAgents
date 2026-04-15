"""Purged walk-forward evaluation for HAR-RV Ridge models.

Implements the purged K-fold cross-validation pattern from
López de Prado (2018, "Advances in Financial Machine Learning", Ch. 7):
splits are contiguous in time, and the last ``embargo_days`` of every
training fold are dropped to prevent forward-looking leakage where a
feature observed at time ``t`` partially depends on observations used as
targets in the subsequent test fold.

The evaluator is model-agnostic-ish: it expects a panel with ``(date, ticker)``
MultiIndex and trains a fresh HAR-RV Ridge model per split via
:func:`tradingagents.models.har_rv_ridge.train_ridge_model`. Each split
reports pooled R^2, Spearman IC summary, and QLIKE loss.

References
----------
López de Prado, M. (2018). "Advances in Financial Machine Learning",
Chapter 7: Cross-Validation in Finance. Wiley.

Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized
Volatility." Journal of Financial Econometrics 7(2), 174-196.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WalkForwardSplit:
    """Per-split metrics produced by :func:`walk_forward_evaluate`."""

    split_idx: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train: int
    n_test: int
    pooled_r2: float
    ic_mean: float
    ic_std: float
    ic_ir: float
    qlike: float


def _qlike(actual: np.ndarray, predicted: np.ndarray) -> float:
    """QLIKE loss for realised volatility forecasts.

    ``QLIKE(y, y_hat) = mean( y / y_hat - log(y / y_hat) - 1 )``

    QLIKE is a proper scoring rule for variance forecasts (Patton 2011) and
    is the standard RV-literature companion to R^2 / MSE. Lower is better;
    QLIKE = 0 is a perfect forecast.
    """
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    # Both sides must be strictly positive for the logarithm.
    mask = np.isfinite(a) & np.isfinite(p) & (a > 0.0) & (p > 0.0)
    if mask.sum() == 0:
        return float("nan")
    a = a[mask]
    p = p[mask]
    ratio = a / p
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def _pooled_r2_arr(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Pooled R^2 from raw numpy arrays."""
    mask = np.isfinite(actual) & np.isfinite(predicted)
    if mask.sum() == 0:
        return float("nan")
    a = actual[mask]
    p = predicted[mask]
    ss_res = float(np.sum((a - p) ** 2))
    ss_tot = float(np.sum((a - np.mean(a)) ** 2))
    if ss_tot == 0.0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def _cross_section_ic_mean(
    dates: np.ndarray, actual: np.ndarray, predicted: np.ndarray
) -> tuple[float, float, float]:
    """Return (mean_ic, std_ic, ir) for per-date Spearman IC."""
    from scipy import stats

    df = pd.DataFrame({"date": dates, "actual": actual, "predicted": predicted})
    ics: list[float] = []
    for _, group in df.groupby("date", sort=True):
        a = group["actual"].to_numpy(dtype=float)
        p = group["predicted"].to_numpy(dtype=float)
        mask = np.isfinite(a) & np.isfinite(p)
        if mask.sum() < 3:
            continue
        a = a[mask]
        p = p[mask]
        if np.nanstd(a) == 0 or np.nanstd(p) == 0:
            continue
        try:
            r, _ = stats.spearmanr(a, p)
        except Exception:  # noqa: BLE001
            continue
        if r is not None and not (isinstance(r, float) and math.isnan(r)):
            ics.append(float(r))
    if not ics:
        return float("nan"), float("nan"), float("nan")
    arr = np.asarray(ics, dtype=float)
    mean_ic = float(arr.mean())
    std_ic = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    ir = mean_ic / std_ic if std_ic > 1e-12 else float("nan")
    return mean_ic, std_ic, ir


def _split_by_unique_date(
    unique_dates: np.ndarray, n_splits: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Split ``unique_dates`` into contiguous (train_dates, test_dates) folds.

    Matches ``sklearn.model_selection.TimeSeriesSplit`` behaviour: the k-th
    fold trains on all dates strictly before test fold k, then tests on a
    contiguous block of dates. Because dates are contiguous and sorted, the
    resulting splits never overlap in their test segments.
    """
    if n_splits < 2:
        raise ValueError(f"n_splits must be >= 2, got {n_splits}")
    n = len(unique_dates)
    if n < n_splits + 1:
        raise ValueError(
            f"not enough unique dates ({n}) to form {n_splits} walk-forward splits"
        )

    # Test fold size: partition the tail evenly into n_splits blocks.
    test_size = n // (n_splits + 1)
    if test_size < 1:
        raise ValueError(f"test_size computed as 0 from n={n}, n_splits={n_splits}")

    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(n_splits):
        test_start = n - (n_splits - k) * test_size
        test_end = test_start + test_size if k < n_splits - 1 else n
        if test_start <= 0:
            continue
        train_dates = unique_dates[:test_start]
        test_dates = unique_dates[test_start:test_end]
        splits.append((train_dates, test_dates))
    return splits


def walk_forward_evaluate(
    panel: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    n_splits: int = 5,
    embargo_days: int = 10,
    target_transform: str = "log",
) -> dict[str, Any]:
    """Purged walk-forward evaluation for a HAR-RV Ridge model.

    For each of ``n_splits`` contiguous time splits, the function:

    1. Identifies the sorted unique dates of the panel and partitions them
       into a train prefix and a contiguous test block (López de Prado
       2018, Ch. 7).
    2. Drops the last ``embargo_days`` of *unique training dates* — not
       rows — so that any feature measured on a training date cannot have
       been computed from overlapping future information that leaks into
       the test fold.
    3. Fits :func:`tradingagents.models.har_rv_ridge.train_ridge_model` on
       the purged training panel with the requested ``target_transform``.
    4. Predicts on the test fold and records pooled R^2, mean Spearman
       cross-sectional IC, and QLIKE loss.

    Parameters
    ----------
    panel : pd.DataFrame
        MultiIndex ``(date, ticker)`` panel containing the feature columns
        and the target column.
    feature_cols : list[str]
        Feature column names.
    target_col : str
        Name of the raw (level) forward RV target column — e.g.
        ``"rv_next_1d"``. QLIKE and R^2 are computed on the raw level
        regardless of ``target_transform``; the transform only affects how
        the model is fit.
    n_splits : int
        Number of purged walk-forward folds.
    embargo_days : int
        Number of unique training dates to drop from the end of each
        training fold before model fitting.
    target_transform : {"raw", "log"}
        Passed through to :func:`train_ridge_model`.

    Returns
    -------
    dict
        Dictionary with keys ``"splits"`` (list of per-split dicts) and
        ``"summary"`` (aggregate mean/std across splits for R^2, IC, QLIKE).
    """
    from tradingagents.models.har_rv_ridge import predict, train_ridge_model

    if panel.empty:
        raise ValueError("panel is empty")
    if not isinstance(panel.index, pd.MultiIndex):
        raise ValueError("panel must have a MultiIndex (date, ticker)")
    if target_col not in panel.columns:
        raise KeyError(f"target_col {target_col!r} not in panel columns")
    missing = [c for c in feature_cols if c not in panel.columns]
    if missing:
        raise KeyError(f"feature columns missing from panel: {missing}")
    if embargo_days < 0:
        raise ValueError(f"embargo_days must be >= 0, got {embargo_days}")
    if target_transform not in ("raw", "log"):
        raise ValueError(f"Unknown target_transform={target_transform!r}")

    # Infer horizon from target column name (e.g. "rv_next_5d" -> 5).
    horizon = _parse_horizon_from_target(target_col)

    sorted_panel = panel.sort_index()
    all_dates = pd.to_datetime(
        sorted_panel.index.get_level_values(0)
    ).unique().sort_values()
    unique_dates = np.asarray(all_dates)

    date_splits = _split_by_unique_date(unique_dates, n_splits)

    split_results: list[dict[str, Any]] = []
    for k, (train_dates, test_dates) in enumerate(date_splits):
        # Apply embargo: drop the last `embargo_days` unique training dates.
        if embargo_days > 0 and len(train_dates) > embargo_days:
            purged_train_dates = train_dates[:-embargo_days]
        else:
            purged_train_dates = train_dates

        if len(purged_train_dates) == 0 or len(test_dates) == 0:
            logger.warning(
                "walk_forward_evaluate split %d: empty train or test after purge; skipping",
                k,
            )
            continue

        train_mask = np.isin(
            sorted_panel.index.get_level_values(0).values,
            purged_train_dates,
        )
        test_mask = np.isin(
            sorted_panel.index.get_level_values(0).values,
            test_dates,
        )
        train_fold = sorted_panel.loc[train_mask]
        test_fold = sorted_panel.loc[test_mask]

        if train_fold.empty or test_fold.empty:
            logger.warning("walk_forward split %d: empty fold; skipping", k)
            continue

        try:
            model = train_ridge_model(
                panel=train_fold,
                horizon=horizon,
                feature_cols=list(feature_cols),
                target_transform=target_transform,  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "walk_forward split %d: training failed: %s", k, exc
            )
            continue

        pred_series = predict(model, test_fold, min_tickers=1)
        if pred_series.empty:
            logger.warning(
                "walk_forward split %d: predict returned empty series", k
            )
            continue

        # predict() returns in the model's native space (log-scale for log
        # models). Invert so predictions are comparable to raw targets.
        _transform = getattr(model, "target_transform", "raw")
        if _transform == "log":
            pred_series = np.exp(pred_series)

        actual_series = test_fold[target_col].reindex(pred_series.index)
        merged = pd.DataFrame(
            {"actual": actual_series, "predicted": pred_series.values},
            index=pred_series.index,
        ).dropna()
        if merged.empty:
            logger.warning("walk_forward split %d: no valid preds", k)
            continue

        dates_arr = pd.to_datetime(
            merged.index.get_level_values(0)
        ).to_numpy()
        actual_arr = merged["actual"].to_numpy(dtype=float)
        pred_arr = merged["predicted"].to_numpy(dtype=float)

        r2 = _pooled_r2_arr(actual_arr, pred_arr)
        ic_mean, ic_std, ic_ir = _cross_section_ic_mean(
            dates_arr, actual_arr, pred_arr
        )
        qlike = _qlike(actual_arr, pred_arr)

        split_results.append(
            {
                "split_idx": k,
                "train_start": str(pd.Timestamp(purged_train_dates[0]).date()),
                "train_end": str(pd.Timestamp(purged_train_dates[-1]).date()),
                "test_start": str(pd.Timestamp(test_dates[0]).date()),
                "test_end": str(pd.Timestamp(test_dates[-1]).date()),
                "n_train": int(train_mask.sum()),
                "n_test": int(len(merged)),
                "pooled_r2": r2,
                "ic_mean": ic_mean,
                "ic_std": ic_std,
                "ic_ir": ic_ir,
                "qlike": qlike,
            }
        )

    summary = _summarise_splits(split_results)
    return {
        "target_col": target_col,
        "target_transform": target_transform,
        "n_splits": n_splits,
        "embargo_days": embargo_days,
        "splits": split_results,
        "summary": summary,
    }


def _parse_horizon_from_target(target_col: str) -> int:
    """Extract horizon integer from a column name like ``rv_next_{h}d``.

    Supports ``rv_next_{h}d``, ``rv_next_{h}d_log``, and the daily variant
    ``rv_daily_next_{h}d`` / ``rv_daily_next_{h}d_log``.
    """
    m = re.fullmatch(r"rv_(?:daily_)?next_(\d+)d(?:_log)?", target_col)
    if m is None:
        raise ValueError(
            f"Cannot parse horizon from target_col={target_col!r}"
        )
    return int(m.group(1))


def _summarise_splits(splits: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate mean and std of per-split metrics across folds."""
    if not splits:
        return {
            "r2_mean": float("nan"),
            "r2_std": float("nan"),
            "ic_mean": float("nan"),
            "ic_std": float("nan"),
            "qlike_mean": float("nan"),
            "qlike_std": float("nan"),
            "n_splits_ok": 0,
        }

    def _agg(key: str) -> tuple[float, float]:
        vals = np.asarray(
            [s[key] for s in splits if np.isfinite(s.get(key, float("nan")))],
            dtype=float,
        )
        if len(vals) == 0:
            return float("nan"), float("nan")
        return float(vals.mean()), float(vals.std(ddof=1) if len(vals) > 1 else 0.0)

    r2_mean, r2_std = _agg("pooled_r2")
    ic_mean, ic_std = _agg("ic_mean")
    ql_mean, ql_std = _agg("qlike")

    return {
        "r2_mean": r2_mean,
        "r2_std": r2_std,
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "qlike_mean": ql_mean,
        "qlike_std": ql_std,
        "n_splits_ok": len(splits),
    }
