"""Unit tests for tradingagents.evaluation.ic_metrics and output_writer."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.evaluation.ic_metrics import (
    cross_section_ic,
    full_evaluation,
    ic_summary,
    pooled_r2,
    time_series_ic,
    time_series_ic_summary,
)
from tradingagents.evaluation.output_writer import (
    write_summary,
    write_target_outputs,
)


def _make_panel(
    n_dates: int = 10,
    n_tickers: int = 8,
    mode: str = "perfect",
    seed: int = 42,
) -> pd.DataFrame:
    """Build a synthetic (date, ticker, actual, predicted) panel."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    rows = []
    for d in dates:
        actual = rng.normal(loc=1.0, scale=0.5, size=n_tickers)
        if mode == "perfect":
            predicted = actual.copy()
        elif mode == "anti":
            predicted = -actual
        elif mode == "random":
            predicted = rng.normal(size=n_tickers)
        elif mode == "mean":
            predicted = np.full(n_tickers, actual.mean())
        else:
            raise ValueError(mode)
        for t, a, p in zip(tickers, actual, predicted):
            rows.append({"date": d, "ticker": t, "actual": a, "predicted": p})
    return pd.DataFrame(rows)


# ---- cross_section_ic ----

def test_cs_ic_perfect_correlation():
    df = _make_panel(n_dates=5, n_tickers=6, mode="perfect")
    out = cross_section_ic(df, method="spearman")
    assert len(out) == 5
    assert np.allclose(out["ic"].to_numpy(), 1.0)
    assert (out["n"] == 6).all()


def test_cs_ic_anti_correlation():
    df = _make_panel(n_dates=5, n_tickers=6, mode="anti")
    out = cross_section_ic(df, method="spearman")
    assert np.allclose(out["ic"].to_numpy(), -1.0)


def test_cs_ic_random_mean_near_zero():
    df = _make_panel(n_dates=200, n_tickers=20, mode="random", seed=7)
    out = cross_section_ic(df, method="spearman")
    mean_ic = out["ic"].mean()
    assert abs(mean_ic) < 0.1


# ---- ic_summary ----

def test_ic_summary_t_stat_formula():
    ic_vals = [0.1, 0.2, 0.15, 0.05, 0.25]
    ic_df = pd.DataFrame({"ic": ic_vals, "n": [10] * 5, "date": range(5)})
    summ = ic_summary(ic_df)
    mean = float(np.mean(ic_vals))
    std = float(np.std(ic_vals, ddof=1))
    expected_t = mean / (std / math.sqrt(len(ic_vals)))
    assert summ["mean_ic"] == pytest.approx(mean)
    assert summ["std_ic"] == pytest.approx(std)
    assert summ["t_stat"] == pytest.approx(expected_t)
    assert summ["ir"] == pytest.approx(mean / std)
    assert summ["pct_positive"] == pytest.approx(1.0)
    assert summ["n_days"] == 5


def test_ic_summary_zero_std():
    ic_df = pd.DataFrame({"ic": [0.1, 0.1, 0.1], "n": [5, 5, 5], "date": range(3)})
    summ = ic_summary(ic_df)
    assert summ["mean_ic"] == pytest.approx(0.1)
    assert math.isnan(summ["ir"])
    assert math.isnan(summ["t_stat"])


def test_ic_summary_empty():
    summ = ic_summary(pd.DataFrame(columns=["ic", "n", "date"]))
    assert math.isnan(summ["mean_ic"])
    assert summ["n_days"] == 0


# ---- pooled_r2 ----

def test_pooled_r2_perfect():
    df = _make_panel(n_dates=4, n_tickers=5, mode="perfect")
    assert pooled_r2(df) == pytest.approx(1.0)


def test_pooled_r2_mean_predictor_zero():
    df = _make_panel(n_dates=4, n_tickers=5, mode="mean")
    # predicted == mean(actual) per date but pooled mean differs.
    # Construct a stricter case: predicted = global mean for all rows.
    df = _make_panel(n_dates=4, n_tickers=5, mode="perfect")
    df["predicted"] = df["actual"].mean()
    r2 = pooled_r2(df)
    assert r2 == pytest.approx(0.0, abs=1e-10)


def test_pooled_r2_empty():
    empty = pd.DataFrame(columns=["date", "ticker", "actual", "predicted"])
    assert math.isnan(pooled_r2(empty))


# ---- time_series_ic ----

def test_time_series_ic_perfect():
    df = _make_panel(n_dates=30, n_tickers=5, mode="perfect")
    out = time_series_ic(df, method="spearman")
    assert len(out) == 5
    assert np.allclose(out["ic"].to_numpy(), 1.0)
    assert (out["n"] == 30).all()


# ---- full_evaluation ----

def test_full_evaluation_keys():
    df = _make_panel(n_dates=20, n_tickers=10, mode="perfect")
    result = full_evaluation(df, period_name="test")
    expected_keys = {
        "period",
        "n_obs",
        "n_dates",
        "n_tickers",
        "pooled_r2",
        "cs_ic_spearman",
        "cs_ic_pearson",
        "ts_ic_spearman",
        "ts_ic_pearson",
    }
    assert expected_keys <= set(result.keys())
    assert result["period"] == "test"
    assert result["n_obs"] == 200
    assert result["n_dates"] == 20
    assert result["n_tickers"] == 10
    assert result["pooled_r2"] == pytest.approx(1.0)
    assert result["cs_ic_spearman"]["mean_ic"] == pytest.approx(1.0)


def test_time_series_ic_summary_basic():
    ts = pd.DataFrame({"ticker": ["A", "B", "C", "D"], "ic": [0.1, 0.2, 0.3, 0.4], "n": [10] * 4})
    summ = time_series_ic_summary(ts)
    assert summ["mean"] == pytest.approx(0.25)
    assert summ["median"] == pytest.approx(0.25)
    assert summ["n_tickers"] == 4


# ---- output_writer ----

def test_write_target_outputs(tmp_path: Path):
    df_train = _make_panel(n_dates=5, n_tickers=4, mode="perfect", seed=1)
    df_valid = _make_panel(n_dates=3, n_tickers=4, mode="perfect", seed=2)
    df_test = _make_panel(n_dates=4, n_tickers=4, mode="perfect", seed=3)

    metrics = {
        "train": full_evaluation(df_train, "train"),
        "valid": full_evaluation(df_valid, "valid"),
        "test": full_evaluation(df_test, "test"),
    }
    predictions = {"train": df_train, "valid": df_valid, "test": df_test}

    target_dir = write_target_outputs(
        "rv_daily_next_1d",
        metrics=metrics,
        predictions=predictions,
        root=tmp_path,
    )
    assert target_dir.exists()
    assert (target_dir / "metrics.json").exists()
    assert (target_dir / "predictions_train.parquet").exists()
    assert (target_dir / "predictions_valid.parquet").exists()
    assert (target_dir / "predictions_test.parquet").exists()
    assert (target_dir / "cs_ic_spearman.csv").exists()
    assert (target_dir / "cs_ic_pearson.csv").exists()
    assert (target_dir / "ts_ic.csv").exists()

    # Parquet is readable
    round_trip = pd.read_parquet(target_dir / "predictions_test.parquet")
    assert set(round_trip.columns) >= {"date", "ticker", "actual", "predicted"}
    assert len(round_trip) == len(df_test)

    # CSV schema
    cs = pd.read_csv(target_dir / "cs_ic_spearman.csv")
    assert list(cs.columns) == ["date", "ic", "n"]

    ts = pd.read_csv(target_dir / "ts_ic.csv")
    assert list(ts.columns) == ["ticker", "spearman_ic", "pearson_ic"]


def test_write_summary(tmp_path: Path):
    df = _make_panel(n_dates=6, n_tickers=5, mode="perfect")
    metrics = full_evaluation(df, "test")
    target_metrics = {
        "rv_daily_next_1d": {"train": metrics, "valid": metrics, "test": metrics},
        "rv_daily_next_5d": {"train": metrics, "valid": metrics, "test": metrics},
    }
    path = write_summary(target_metrics, root=tmp_path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert "targets" in data
    assert "generated_at" in data
    assert "rv_daily_next_1d" in data["targets"]
    assert "test" in data["targets"]["rv_daily_next_1d"]
    row = data["targets"]["rv_daily_next_1d"]["test"]
    assert "pooled_r2" in row
    assert "cs_ic_spearman_mean" in row
    assert "cs_ic_pearson_mean" in row
