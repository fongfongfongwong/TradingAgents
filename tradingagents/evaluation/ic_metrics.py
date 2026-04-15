"""Information Coefficient (IC) and R^2 evaluation for RV prediction.

All functions operate on prediction DataFrames with columns:
    date (DatetimeIndex or column), ticker, actual, predicted
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

_REQUIRED_COLS = ("date", "ticker", "actual", "predicted")


def _ensure_frame(predictions: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `predictions` with a `date` column (not index)."""
    if predictions is None or len(predictions) == 0:
        return pd.DataFrame(columns=list(_REQUIRED_COLS))

    df = predictions.copy()
    if "date" not in df.columns:
        if isinstance(df.index, pd.DatetimeIndex) or df.index.name == "date":
            df = df.reset_index().rename(columns={df.index.name or "index": "date"})
        else:
            raise ValueError("predictions must have a 'date' column or DatetimeIndex")

    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"predictions missing required columns: {missing}")
    return df


def _safe_corr(x: np.ndarray, y: np.ndarray, method: str) -> float:
    """Correlation that returns NaN for degenerate inputs instead of warning."""
    if len(x) < 3 or len(y) < 3:
        return float("nan")
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 3:
        return float("nan")
    x = x[mask]
    y = y[mask]
    if np.nanstd(x) == 0 or np.nanstd(y) == 0:
        return float("nan")
    try:
        if method == "spearman":
            r, _ = stats.spearmanr(x, y)
        elif method == "pearson":
            r, _ = stats.pearsonr(x, y)
        else:
            raise ValueError(f"unknown method: {method!r}")
    except Exception:
        return float("nan")
    if r is None or (isinstance(r, float) and math.isnan(r)):
        return float("nan")
    return float(r)


def cross_section_ic(
    predictions: pd.DataFrame,
    method: str = "spearman",
) -> pd.DataFrame:
    """Compute per-date cross-sectional IC.

    For each date, compute correlation between `actual` and `predicted` across
    all tickers in the cross-section.

    Returns DataFrame with columns ['date', 'ic', 'n'].
    NaN IC for dates with < 3 tickers or zero-variance inputs.
    """
    df = _ensure_frame(predictions)
    if df.empty:
        return pd.DataFrame(columns=["date", "ic", "n"])

    rows: list[dict[str, Any]] = []
    for date, group in df.groupby("date", sort=True):
        actual = group["actual"].to_numpy(dtype=float)
        predicted = group["predicted"].to_numpy(dtype=float)
        ic = _safe_corr(actual, predicted, method)
        rows.append({"date": date, "ic": ic, "n": int(len(group))})
    return pd.DataFrame(rows, columns=["date", "ic", "n"])


def time_series_ic(
    predictions: pd.DataFrame,
    method: str = "spearman",
) -> pd.DataFrame:
    """Compute per-ticker time-series IC.

    Returns DataFrame with columns ['ticker', 'ic', 'n'].
    """
    df = _ensure_frame(predictions)
    if df.empty:
        return pd.DataFrame(columns=["ticker", "ic", "n"])

    rows: list[dict[str, Any]] = []
    for ticker, group in df.groupby("ticker", sort=True):
        actual = group["actual"].to_numpy(dtype=float)
        predicted = group["predicted"].to_numpy(dtype=float)
        ic = _safe_corr(actual, predicted, method)
        rows.append({"ticker": ticker, "ic": ic, "n": int(len(group))})
    return pd.DataFrame(rows, columns=["ticker", "ic", "n"])


def ic_summary(ic_series: pd.DataFrame) -> dict[str, float]:
    """Summary statistics for a per-date IC DataFrame.

    Returns mean_ic, std_ic, ir, t_stat, pct_positive, n_days.
    Handles edge cases: zero std -> IR=nan, t_stat=nan. Empty -> all nan.
    """
    nan_result = {
        "mean_ic": float("nan"),
        "std_ic": float("nan"),
        "ir": float("nan"),
        "t_stat": float("nan"),
        "pct_positive": float("nan"),
        "n_days": 0,
    }
    if ic_series is None or len(ic_series) == 0 or "ic" not in ic_series.columns:
        return nan_result

    ic_vals = pd.to_numeric(ic_series["ic"], errors="coerce").dropna().to_numpy()
    n = int(len(ic_vals))
    if n == 0:
        return nan_result

    mean_ic = float(np.mean(ic_vals))
    std_ic = float(np.std(ic_vals, ddof=1)) if n > 1 else 0.0
    pct_pos = float(np.mean(ic_vals > 0))

    # Guard: treat near-zero std (floating-point artifact on constant input)
    # as zero so IR / t_stat become NaN instead of exploding.
    _EPS = 1e-12
    if not np.isfinite(std_ic) or std_ic <= _EPS:
        ir = float("nan")
        t_stat = float("nan")
    else:
        ir = mean_ic / std_ic
        t_stat = mean_ic / (std_ic / math.sqrt(n))

    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "ir": ir,
        "t_stat": t_stat,
        "pct_positive": pct_pos,
        "n_days": n,
    }


def time_series_ic_summary(ts_ic: pd.DataFrame) -> dict[str, float]:
    """Summary statistics for per-ticker time-series IC."""
    nan_result = {
        "mean": float("nan"),
        "median": float("nan"),
        "p25": float("nan"),
        "p75": float("nan"),
        "n_tickers": 0,
    }
    if ts_ic is None or len(ts_ic) == 0 or "ic" not in ts_ic.columns:
        return nan_result

    vals = pd.to_numeric(ts_ic["ic"], errors="coerce").dropna().to_numpy()
    if len(vals) == 0:
        return nan_result

    return {
        "mean": float(np.mean(vals)),
        "median": float(np.median(vals)),
        "p25": float(np.percentile(vals, 25)),
        "p75": float(np.percentile(vals, 75)),
        "n_tickers": int(len(vals)),
    }


def pooled_r2(predictions: pd.DataFrame) -> float:
    """Pooled R^2 across all (date, ticker) observations."""
    df = _ensure_frame(predictions)
    if df.empty:
        return float("nan")

    actual = pd.to_numeric(df["actual"], errors="coerce").to_numpy(dtype=float)
    predicted = pd.to_numeric(df["predicted"], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(actual) & np.isfinite(predicted)
    if mask.sum() == 0:
        return float("nan")
    actual = actual[mask]
    predicted = predicted[mask]

    ss_res = float(np.sum((actual - predicted) ** 2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def full_evaluation(
    predictions: pd.DataFrame,
    period_name: str = "test",
) -> dict[str, Any]:
    """Full IC + R^2 evaluation for one period (train/valid/test)."""
    df = _ensure_frame(predictions)

    cs_spearman = cross_section_ic(df, method="spearman")
    cs_pearson = cross_section_ic(df, method="pearson")
    ts_spearman = time_series_ic(df, method="spearman")
    ts_pearson = time_series_ic(df, method="pearson")

    return {
        "period": period_name,
        "n_obs": int(len(df)),
        "n_dates": int(df["date"].nunique()) if len(df) else 0,
        "n_tickers": int(df["ticker"].nunique()) if len(df) else 0,
        "pooled_r2": pooled_r2(df),
        "cs_ic_spearman": ic_summary(cs_spearman),
        "cs_ic_pearson": ic_summary(cs_pearson),
        "ts_ic_spearman": time_series_ic_summary(ts_spearman),
        "ts_ic_pearson": time_series_ic_summary(ts_pearson),
    }
