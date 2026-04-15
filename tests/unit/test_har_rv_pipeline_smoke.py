"""End-to-end smoke test for the HAR-RV Ridge baseline pipeline.

This test wires together every layer of the pipeline:

    assemble_panel (synthetic OHLC, no network)
      -> split_by_date
      -> train_ridge_model
      -> predict
      -> full_evaluation

It is the piece that was missing after Round 1 — the individual unit tests
each exercise a single layer, but none of them prove that the layers
compose. Target runtime: well under 5 seconds.

NO NETWORK: we feed ``assemble_panel`` a prebuilt ``ohlc_cache`` dict so
yfinance is never called.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.evaluation.ic_metrics import full_evaluation
from tradingagents.models.data_assembly import assemble_panel, split_by_date
from tradingagents.models.har_rv_ridge import predict, train_ridge_model


def _synthetic_ohlc(
    ticker: str,
    n_days: int = 300,
    start: str = "2022-01-03",
    seed: int = 1,
) -> pd.DataFrame:
    """Build a deterministic synthetic OHLC frame for a single ticker.

    The return series is a small iid Gaussian. Intraday high/low are
    constructed from the same log-return so the Garman-Klass RV estimator
    has a non-trivial (but finite) signal.
    """
    rng = np.random.default_rng(seed + hash(ticker) % 10_000)
    dates = pd.bdate_range(start=start, periods=n_days)
    log_ret = rng.normal(loc=0.0, scale=0.015, size=n_days)
    close = 100.0 * np.exp(np.cumsum(log_ret))
    # Open = previous close (first open = first close / exp(first ret))
    open_ = np.empty(n_days, dtype=float)
    open_[0] = close[0] / np.exp(log_ret[0])
    open_[1:] = close[:-1]
    # Construct a plausible high/low band from a secondary noise term.
    band = np.abs(rng.normal(loc=0.0, scale=0.012, size=n_days)) * close
    high = np.maximum(open_, close) + band
    low = np.minimum(open_, close) - band
    low = np.maximum(low, 1e-3)  # avoid zero/negative prices
    volume = rng.integers(low=1_000_000, high=5_000_000, size=n_days).astype(float)

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=pd.DatetimeIndex(dates, name="date"),
    )
    return df


@pytest.mark.unit
def test_har_rv_pipeline_end_to_end_smoke():
    """Full pipeline runs and produces a well-formed evaluation dict."""
    tickers = [f"T{i:02d}" for i in range(10)]
    ohlc_cache = {t: _synthetic_ohlc(t, n_days=300, seed=i) for i, t in enumerate(tickers)}

    # 1) assemble_panel via the cache path (no network)
    panel = assemble_panel(
        tickers=tickers,
        start="2022-01-03",
        end="2023-12-31",
        horizons=(1, 5),
        ohlc_cache=ohlc_cache,
    )
    assert not panel.empty, "assemble_panel should produce a non-empty panel"
    assert isinstance(panel.index, pd.MultiIndex)
    assert "rv_next_1d" in panel.columns
    assert "rv_next_5d" in panel.columns

    # 2) split_by_date — choose cutoffs well inside the synthetic range.
    dates = panel.index.get_level_values(0)
    min_d = dates.min()
    max_d = dates.max()
    # Split at ~60%/80% of the observed date span.
    span = max_d - min_d
    train_end = (min_d + span * 0.6).normalize()
    valid_end = (min_d + span * 0.8).normalize()

    train, valid, test = split_by_date(
        panel,
        train_end=str(train_end.date()),
        valid_end=str(valid_end.date()),
    )
    assert len(train) > 0
    assert len(valid) > 0
    assert len(test) > 0

    # 3) train_ridge_model for the 1-day horizon.
    model = train_ridge_model(train, horizon=1)
    assert model.horizon == 1
    assert model.train_rows > 0
    assert len(model.feature_names) == 18  # 10 legacy + 8 tier-0 HAR features

    # 4) predict on the test split with inference-time min_tickers=1.
    pred = predict(model, test, min_tickers=1)
    assert not pred.empty, "predict should produce non-empty output on test"
    assert pred.name == "rv_next_1d_pred"

    # 5) Build a prediction DataFrame and run full_evaluation.
    actual = test.loc[pred.index, "rv_next_1d"]
    pred_df = (
        pd.DataFrame({"actual": actual, "predicted": pred.to_numpy()})
        .dropna()
        .reset_index()  # (date, ticker) -> columns
    )
    assert {"date", "ticker", "actual", "predicted"}.issubset(pred_df.columns)
    assert len(pred_df) > 0

    report = full_evaluation(pred_df, period_name="test")

    # Schema assertions on the evaluation output.
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
    assert expected_keys.issubset(report.keys())
    assert report["period"] == "test"
    assert report["n_obs"] == len(pred_df)
    assert report["n_tickers"] >= 1
    assert report["n_dates"] >= 1


@pytest.mark.unit
def test_predict_single_ticker_inference_not_dropped():
    """Regression test for MAJOR-3: predict must not silently drop a single-ticker cross-section.

    At inference time a caller may want a prediction for a single ticker on
    a single date. With the previous default (``min_tickers=5``) that entire
    date would be dropped inside ``preprocess_features`` and ``predict``
    would return an empty series.
    """
    tickers = [f"T{i:02d}" for i in range(10)]
    ohlc_cache = {t: _synthetic_ohlc(t, n_days=300, seed=i) for i, t in enumerate(tickers)}
    panel = assemble_panel(
        tickers=tickers,
        start="2022-01-03",
        end="2023-12-31",
        horizons=(1,),
        ohlc_cache=ohlc_cache,
    )
    assert not panel.empty

    dates = panel.index.get_level_values(0)
    split_date = str((dates.min() + (dates.max() - dates.min()) * 0.6).normalize().date())
    train, _valid, test = split_by_date(panel, train_end=split_date, valid_end=split_date)

    model = train_ridge_model(train, horizon=1)

    # Take the last row of the test set for ONE ticker only.
    one_ticker = test.xs(tickers[0], level=1, drop_level=False).dropna(
        subset=list(model.feature_names)
    )
    assert len(one_ticker) > 0
    last_row = one_ticker.iloc[[-1]]

    pred = predict(model, last_row, min_tickers=1)
    assert not pred.empty, "single-ticker inference must not be dropped"
    assert len(pred) == 1
