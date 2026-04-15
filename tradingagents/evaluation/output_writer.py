"""Write baseline evaluation outputs matching BASELINE.md structure.

Output layout (rooted at ~/.tradingagents/outputs/rv_prediction/baseline/):
    summary.json                      # Top-level leaderboard
    rv_daily_next_1d/
        metrics.json                  # Full evaluation for all periods
        predictions_train.parquet
        predictions_valid.parquet
        predictions_test.parquet
        cs_ic_spearman.csv            # test period, per-date IC
        cs_ic_pearson.csv
        ts_ic.csv                     # test period, per-ticker IC
    rv_daily_next_5d/
        ... same structure
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingagents.evaluation.ic_metrics import (
    cross_section_ic,
    time_series_ic,
)

_DEFAULT_ROOT = Path.home() / ".tradingagents" / "outputs" / "rv_prediction" / "baseline"


def _default_root(root: Path | None) -> Path:
    return Path(root) if root is not None else _DEFAULT_ROOT


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_target_outputs(
    target_name: str,
    metrics: dict[str, dict[str, Any]],
    predictions: dict[str, pd.DataFrame],
    root: Path | None = None,
) -> Path:
    """Write all files for one target.

    Args:
        target_name: e.g. "rv_daily_next_1d"
        metrics: {"train": metrics_dict, "valid": ..., "test": ...}
        predictions: {"train": df, "valid": df, "test": df}
        root: Override output root (default ~/.tradingagents/outputs/...)

    Returns the target subdirectory path.
    """
    base = _default_root(root)
    target_dir = base / target_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # Write metrics.json (all periods)
    metrics_path = target_dir / "metrics.json"
    with metrics_path.open("w") as f:
        json.dump(metrics, f, indent=2, default=str)

    # Write predictions as parquet (per period)
    for period, df in predictions.items():
        if df is None:
            continue
        out = target_dir / f"predictions_{period}.parquet"
        df.to_parquet(out, index=False)

    # Write test-period per-date IC CSVs and per-ticker IC CSV
    test_df = predictions.get("test")
    if test_df is not None and len(test_df) > 0:
        cs_spear = cross_section_ic(test_df, method="spearman")
        cs_pear = cross_section_ic(test_df, method="pearson")
        ts_spear = time_series_ic(test_df, method="spearman")
        ts_pear = time_series_ic(test_df, method="pearson")

        cs_spear.to_csv(target_dir / "cs_ic_spearman.csv", index=False)
        cs_pear.to_csv(target_dir / "cs_ic_pearson.csv", index=False)

        # Merge ts_ic spearman + pearson into one file with spec-compliant
        # columns: ticker, spearman_ic, pearson_ic
        ts_combined = ts_spear[["ticker", "ic"]].rename(
            columns={"ic": "spearman_ic"}
        ).merge(
            ts_pear[["ticker", "ic"]].rename(columns={"ic": "pearson_ic"}),
            on="ticker",
            how="outer",
        )
        ts_combined.to_csv(target_dir / "ts_ic.csv", index=False)

    return target_dir


def _leaderboard_row(period_metrics: dict[str, Any]) -> dict[str, Any]:
    """Extract compact leaderboard fields from a full_evaluation dict."""
    cs_spear = period_metrics.get("cs_ic_spearman", {}) or {}
    cs_pear = period_metrics.get("cs_ic_pearson", {}) or {}
    return {
        "pooled_r2": period_metrics.get("pooled_r2"),
        "cs_ic_spearman_mean": cs_spear.get("mean_ic"),
        "cs_ic_spearman_ir": cs_spear.get("ir"),
        "cs_ic_spearman_t_stat": cs_spear.get("t_stat"),
        "cs_ic_pearson_mean": cs_pear.get("mean_ic"),
        "n_obs": period_metrics.get("n_obs"),
        "n_dates": period_metrics.get("n_dates"),
        "n_tickers": period_metrics.get("n_tickers"),
    }


def write_summary(
    target_metrics: dict[str, dict[str, dict[str, Any]]],
    root: Path | None = None,
) -> Path:
    """Write top-level summary.json with leaderboard view.

    Args:
        target_metrics: {
            "rv_daily_next_1d": {"train": metrics, "valid": metrics, "test": metrics},
            "rv_daily_next_5d": {...},
        }
    """
    base = _default_root(root)
    base.mkdir(parents=True, exist_ok=True)

    leaderboard: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "targets": {},
    }
    for target_name, periods in target_metrics.items():
        leaderboard["targets"][target_name] = {
            period: _leaderboard_row(m) for period, m in periods.items()
        }

    summary_path = base / "summary.json"
    with summary_path.open("w") as f:
        json.dump(leaderboard, f, indent=2, default=str)
    return summary_path
