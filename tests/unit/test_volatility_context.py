"""Unit tests for the VolatilityContext builder + helpers.

Covers:
    1. compute_realized_vol_pct — exact formula on a known series.
    2. compute_realized_vol_pct — insufficient data returns None.
    3. compute_realized_vol_pct — zero-variance series returns None.
    4. compute_bollinger_width_pct — flat series returns 0.0.
    5. compute_bollinger_width_pct — volatile series returns positive.
    6. classify_vol_regime — boundary thresholds + None fallback.
    7. compute_vol_percentile — rank against a known history series.
    8. extract_kline_last_n — takes the tail and matches last row.
    9. Materializer integration — real AAPL briefing populates VolatilityContext.
    10. Backward compat — old JSON without ``volatility`` field still parses.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.data.materializer import (
    classify_vol_regime,
    compute_bollinger_width_pct,
    compute_realized_vol_pct,
    compute_vol_percentile,
    extract_kline_last_n,
)
from tradingagents.schemas.v3 import (
    KlineBar,
    TickerBriefing,
    VolatilityContext,
    VolRegime,
)


# ---------------------------------------------------------------------------
# compute_realized_vol_pct
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_realized_vol_pct_known_series() -> None:
    """Annualized vol must equal ``stdev(ddof=1) * sqrt(252) * 100``."""
    returns = pd.Series([0.01, -0.01, 0.02, -0.02, 0.015, -0.005, 0.0, 0.01])
    expected = float(returns.std(ddof=1)) * math.sqrt(252.0) * 100.0
    result = compute_realized_vol_pct(returns)
    assert result is not None
    assert result == pytest.approx(expected, rel=1e-6)


@pytest.mark.unit
def test_compute_realized_vol_pct_insufficient_data_returns_none() -> None:
    assert compute_realized_vol_pct(pd.Series([0.01])) is None
    assert compute_realized_vol_pct(pd.Series([], dtype=float)) is None


@pytest.mark.unit
def test_compute_realized_vol_pct_zero_variance_returns_none() -> None:
    """Flat returns -> std is 0 -> function returns None (documented choice)."""
    flat = pd.Series([0.0] * 20)
    assert compute_realized_vol_pct(flat) is None


# ---------------------------------------------------------------------------
# compute_bollinger_width_pct
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_bollinger_width_pct_flat_series_is_zero() -> None:
    flat = pd.Series([100.0] * 20)
    assert compute_bollinger_width_pct(flat, period=20) == 0.0


@pytest.mark.unit
def test_compute_bollinger_width_pct_volatile_series_is_positive() -> None:
    prices = pd.Series(
        [100.0, 105.0, 95.0, 110.0, 90.0, 108.0, 92.0, 107.0, 93.0, 109.0,
         91.0, 106.0, 94.0, 104.0, 96.0, 103.0, 97.0, 111.0, 89.0, 100.0]
    )
    width = compute_bollinger_width_pct(prices, period=20)
    assert width is not None
    assert width > 0.0


# ---------------------------------------------------------------------------
# classify_vol_regime
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, VolRegime.NORMAL),
        (10.0, VolRegime.LOW),
        (14.99, VolRegime.LOW),
        (15.0, VolRegime.NORMAL),
        (20.0, VolRegime.NORMAL),
        (29.99, VolRegime.NORMAL),
        (30.0, VolRegime.HIGH),
        (40.0, VolRegime.HIGH),
        (59.99, VolRegime.HIGH),
        (60.0, VolRegime.EXTREME),
        (80.0, VolRegime.EXTREME),
    ],
)
def test_classify_vol_regime(value: float | None, expected: VolRegime) -> None:
    assert classify_vol_regime(value) is expected


# ---------------------------------------------------------------------------
# compute_vol_percentile
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_vol_percentile_middle_of_series() -> None:
    series = pd.Series([10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0])
    # 25 is the 4th of 7 sorted values -> (4 / 7) * 100 ≈ 57.1428...
    # We use "<= current" rank convention, so rank = 4.
    result = compute_vol_percentile(25.0, series)
    assert result is not None
    assert result == pytest.approx(4.0 / 7.0 * 100.0, rel=1e-6)


# ---------------------------------------------------------------------------
# extract_kline_last_n
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_kline_last_n_returns_tail() -> None:
    idx = pd.date_range("2025-01-01", periods=50, freq="D")
    df = pd.DataFrame(
        {
            "Open": np.linspace(100, 150, 50),
            "High": np.linspace(101, 151, 50),
            "Low": np.linspace(99, 149, 50),
            "Close": np.linspace(100.5, 150.5, 50),
            "Volume": np.arange(1_000_000, 1_000_050, dtype=int),
        },
        index=idx,
    )

    bars = extract_kline_last_n(df, n=20)
    assert len(bars) == 20
    assert all(isinstance(b, KlineBar) for b in bars)

    last = bars[-1]
    assert last.date == "2025-02-19"  # day 50 starting 2025-01-01
    assert last.close == pytest.approx(150.5)
    assert last.volume == 1_000_049


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ticker_briefing_parses_without_volatility_field() -> None:
    """Older briefing JSON dumps lack ``volatility`` — default_factory kicks in."""
    payload = {
        "ticker": "AAPL",
        "date": "2026-04-05",
        "snapshot_id": "snap_AAPL_2026-04-05_0",
        "price": {
            "price": 200.0,
            "change_1d_pct": 0.0,
            "change_5d_pct": 0.0,
            "change_20d_pct": 0.0,
            "sma_20": 200.0,
            "sma_50": 200.0,
            "sma_200": 200.0,
            "rsi_14": 50.0,
            "macd_above_signal": False,
            "macd_crossover_days": 0,
            "bollinger_position": "middle_third",
            "volume_vs_avg_20d": 1.0,
            "atr_14": 0.0,
            "data_age_seconds": 0,
        },
        "options": {},
        "news": {},
        "social": {},
        "macro": {"regime": "TRANSITIONING"},
        "events": {},
    }
    briefing = TickerBriefing.model_validate(payload)
    assert isinstance(briefing.volatility, VolatilityContext)
    assert briefing.volatility.vol_regime is VolRegime.NORMAL
    assert briefing.volatility.kline_last_20 == []

    # And round-trip: dumping and re-parsing must preserve the defaults.
    reparsed = TickerBriefing.model_validate(
        json.loads(briefing.model_dump_json())
    )
    assert reparsed.volatility.vol_regime is VolRegime.NORMAL


# ---------------------------------------------------------------------------
# Materializer integration (network-dependent)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_materialize_briefing_populates_volatility_context() -> None:
    """Live integration check: AAPL briefing must carry real vol numbers.

    Skipped automatically if the upstream data fetch fails (offline runs).
    """
    from tradingagents.data.materializer import materialize_briefing

    try:
        briefing = materialize_briefing("AAPL", "2026-04-05")
    except Exception as exc:  # pragma: no cover - network dependent
        pytest.skip(f"materialize_briefing unavailable: {exc}")

    if briefing.price.price <= 0.0:
        pytest.skip("Upstream price history unavailable — skipping live check")

    vol = briefing.volatility
    assert isinstance(vol, VolatilityContext)
    assert isinstance(vol.realized_vol_20d_pct, float)
    assert vol.realized_vol_20d_pct > 0.0
    assert isinstance(vol.vol_regime, VolRegime)
    assert len(vol.kline_last_20) == 20
    assert all(isinstance(b, KlineBar) for b in vol.kline_last_20)
