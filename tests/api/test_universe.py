"""Tests for GET /api/v3/universe/top-volatile endpoint.

Covers:
1. Correct response structure (equity + etf arrays, computed_at, universe_size)
2. n_equity / n_etf query params are respected
3. Results sorted by predicted_rv_1d_pct descending
4. Caching (second call within 60s returns same result)
5. Graceful fallback when no HAR-RV model exists
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fake_ohlc(n_days: int = 25, base_price: float = 100.0, vol: float = 0.03) -> pd.DataFrame:
    """Generate synthetic OHLC data for one ticker."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(end="2026-04-03", periods=n_days)
    actual_n = len(dates)  # may differ from n_days due to weekends
    closes = base_price * np.exp(np.cumsum(rng.normal(0, vol, actual_n)))
    highs = closes * (1 + rng.uniform(0.005, 0.02, actual_n))
    lows = closes * (1 - rng.uniform(0.005, 0.02, actual_n))
    opens = closes * (1 + rng.normal(0, 0.005, actual_n))
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes},
        index=dates,
    )


def _build_batch_download_result(tickers: list[str]) -> pd.DataFrame:
    """Build a multi-level DataFrame mimicking yfinance batch download output."""
    frames: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        # Vary volatility so rankings are deterministic
        vol = 0.01 + i * 0.0005
        frames[ticker] = _make_fake_ohlc(vol=vol)

    # yfinance batch download returns MultiIndex columns: (ticker, OHLC)
    combined = pd.concat(frames, axis=1)
    return combined


# Small stub tickers for testing (avoid downloading 306 real tickers)
_STUB_STOCKS = tuple(f"STK{i}" for i in range(10))
_STUB_ETFS = tuple(f"ETF{i}" for i in range(5))


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the in-process cache before each test."""
    from tradingagents.api.routes.universe import _CACHE
    _CACHE.clear()


@pytest.fixture()
def _patch_tickers_and_yf():
    """Patch clean_tickers and yfinance to avoid real network calls."""
    all_tickers = list(_STUB_STOCKS) + list(_STUB_ETFS)
    fake_data = _build_batch_download_result(all_tickers)

    with (
        patch(
            "tradingagents.api.routes.universe.CLEAN_STOCK_TICKERS",
            _STUB_STOCKS,
            create=True,
        ),
        patch(
            "tradingagents.api.routes.universe.CLEAN_ETF_TICKERS",
            _STUB_ETFS,
            create=True,
        ),
    ):
        # Patch at the import location inside _compute_top_volatile
        with patch("yfinance.download", return_value=fake_data):
            yield


def _get_client() -> TestClient:
    from tradingagents.api.main import create_app
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# 1. Correct response structure
# ---------------------------------------------------------------------------


def test_response_structure(_patch_tickers_and_yf: None) -> None:
    """Response must contain equity, etf, computed_at, and universe_size."""
    # We need to patch the import inside the function
    with patch(
        "tradingagents.factors.clean_tickers.CLEAN_STOCK_TICKERS", _STUB_STOCKS
    ), patch(
        "tradingagents.factors.clean_tickers.CLEAN_ETF_TICKERS", _STUB_ETFS
    ):
        client = _get_client()
        resp = client.get("/api/v3/universe/top-volatile")

    assert resp.status_code == 200
    data = resp.json()

    assert "equity" in data
    assert "etf" in data
    assert "computed_at" in data
    assert "universe_size" in data

    assert isinstance(data["equity"], list)
    assert isinstance(data["etf"], list)
    assert isinstance(data["universe_size"], dict)
    assert "equity" in data["universe_size"]
    assert "etf" in data["universe_size"]

    # Verify individual record structure
    if data["equity"]:
        rec = data["equity"][0]
        assert "ticker" in rec
        assert "predicted_rv_1d_pct" in rec
        assert "realized_vol_20d_pct" in rec
        assert "rank" in rec


# ---------------------------------------------------------------------------
# 2. n_equity / n_etf params respected
# ---------------------------------------------------------------------------


def test_n_params_respected(_patch_tickers_and_yf: None) -> None:
    """Custom n_equity and n_etf should limit the result count."""
    with patch(
        "tradingagents.factors.clean_tickers.CLEAN_STOCK_TICKERS", _STUB_STOCKS
    ), patch(
        "tradingagents.factors.clean_tickers.CLEAN_ETF_TICKERS", _STUB_ETFS
    ):
        client = _get_client()
        resp = client.get("/api/v3/universe/top-volatile?n_equity=3&n_etf=2")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["equity"]) <= 3
    assert len(data["etf"]) <= 2


# ---------------------------------------------------------------------------
# 3. Sorted by predicted_rv_1d_pct descending
# ---------------------------------------------------------------------------


def test_results_sorted_descending(_patch_tickers_and_yf: None) -> None:
    """Equity and ETF arrays must be sorted by predicted_rv_1d_pct descending."""
    with patch(
        "tradingagents.factors.clean_tickers.CLEAN_STOCK_TICKERS", _STUB_STOCKS
    ), patch(
        "tradingagents.factors.clean_tickers.CLEAN_ETF_TICKERS", _STUB_ETFS
    ):
        client = _get_client()
        resp = client.get("/api/v3/universe/top-volatile")

    data = resp.json()

    equity_vols = [r["predicted_rv_1d_pct"] for r in data["equity"]]
    assert equity_vols == sorted(equity_vols, reverse=True), "Equity not sorted descending"

    etf_vols = [r["predicted_rv_1d_pct"] for r in data["etf"]]
    assert etf_vols == sorted(etf_vols, reverse=True), "ETF not sorted descending"


# ---------------------------------------------------------------------------
# 4. Caching (second call within TTL returns same computed_at)
# ---------------------------------------------------------------------------


def test_caching_within_ttl(_patch_tickers_and_yf: None) -> None:
    """Second call within 60s should return the cached result (same computed_at)."""
    with patch(
        "tradingagents.factors.clean_tickers.CLEAN_STOCK_TICKERS", _STUB_STOCKS
    ), patch(
        "tradingagents.factors.clean_tickers.CLEAN_ETF_TICKERS", _STUB_ETFS
    ):
        client = _get_client()
        resp1 = client.get("/api/v3/universe/top-volatile")
        resp2 = client.get("/api/v3/universe/top-volatile")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["computed_at"] == resp2.json()["computed_at"]


# ---------------------------------------------------------------------------
# 5. Graceful fallback when no HAR-RV model
# ---------------------------------------------------------------------------


def test_fallback_when_no_model(_patch_tickers_and_yf: None) -> None:
    """Endpoint should work and return GK RV fallback when model is missing."""
    with patch(
        "tradingagents.factors.clean_tickers.CLEAN_STOCK_TICKERS", _STUB_STOCKS
    ), patch(
        "tradingagents.factors.clean_tickers.CLEAN_ETF_TICKERS", _STUB_ETFS
    ), patch(
        "tradingagents.api.routes.universe._load_har_rv_model", return_value=None
    ):
        client = _get_client()
        resp = client.get("/api/v3/universe/top-volatile")

    assert resp.status_code == 200
    data = resp.json()

    # Should still have results despite no model
    assert len(data["equity"]) > 0 or len(data["etf"]) > 0

    # All predicted_rv_1d_pct should be positive numbers (GK RV fallback)
    for rec in data["equity"] + data["etf"]:
        assert rec["predicted_rv_1d_pct"] > 0
