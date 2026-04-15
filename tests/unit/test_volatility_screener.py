"""Unit tests for the high-volatility screener (FLAB MASA v3 step 1)."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

import pytest

from tradingagents.screener import volatility_screener as vs
from tradingagents.screener.volatility_screener import (
    ScreenerResult,
    VolRank,
    _GroupedRow,
    _Metrics,
    _is_etf,
    _parse_grouped_rows,
    _prefilter,
    _range_20d_pct,
    _realized_vol_annualized,
    _score_and_rank,
    _wilder_atr_pct,
    _zscore,
    run_screener,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point the cache DB at a tmp path per test so runs never collide."""
    fake_db = tmp_path / "screener_cache.db"
    monkeypatch.setattr(vs, "_CACHE_DB_PATH", fake_db)
    yield
    # Cleanup handled automatically by tmp_path.


@pytest.fixture
def _polygon_env(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")
    yield


def _make_bar(c: float, h: float | None = None, l: float | None = None, o: float | None = None, v: float = 1_000_000.0) -> dict[str, float]:
    if h is None:
        h = c * 1.01
    if l is None:
        l = c * 0.99
    if o is None:
        o = c
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


# ---------------------------------------------------------------------------
# 1. Composite scoring math
# ---------------------------------------------------------------------------


def test_composite_score_weighted_zscore():
    metrics = [
        _Metrics("AAA", 10.0, 1_000_000, 10_000_000, 0.20, 0.02, 0.02),
        _Metrics("BBB", 20.0, 2_000_000, 40_000_000, 0.40, 0.04, 0.04),
        _Metrics("CCC", 30.0, 3_000_000, 90_000_000, 0.60, 0.06, 0.06),
    ]
    ranks = _score_and_rank(metrics)
    assert [r.ticker for r in ranks] == ["AAA", "BBB", "CCC"]
    # Monotonic: the highest-vol row must have the highest composite score.
    scores = [r.composite_score for r in ranks]
    assert scores[0] < scores[1] < scores[2]
    # Middle row should be ~0 (it's the mean).
    assert abs(scores[1]) < 1e-9


# ---------------------------------------------------------------------------
# 2. Per-metric math on synthetic data with known answers
# ---------------------------------------------------------------------------


def test_realized_vol_known_series():
    # Alternating +1% / -1% returns -> daily stdev ~ 0.01, annualized ~0.1587.
    closes = [100.0]
    mult = 1.01
    for i in range(20):
        closes.append(closes[-1] * mult)
        mult = 1.01 if mult < 1 else 0.99
    rv = _realized_vol_annualized(closes)
    assert rv is not None
    # Expected around ln(1.01) * sqrt(252) ~ 0.158
    assert 0.12 < rv < 0.20


def test_wilder_atr_pct_on_flat_series_returns_zero():
    bars = [_make_bar(100.0, h=100.0, l=100.0) for _ in range(20)]
    # flat high==low -> ATR = 0 -> atr_pct = 0
    val = _wilder_atr_pct(bars)
    assert val == 0.0


def test_wilder_atr_pct_known_series():
    # Constant TR of 2 per bar on a 100 close -> ATR/close = 0.02
    bars: list[dict[str, float]] = []
    for i in range(20):
        close = 100.0
        bars.append({"o": 100.0, "h": 101.0, "l": 99.0, "c": close, "v": 1.0})
    val = _wilder_atr_pct(bars, period=14)
    assert val is not None
    assert abs(val - 0.02) < 1e-9


def test_range_20d_pct_known_series():
    # Every bar has high=105, low=95, mid=100 -> range pct = 10/100 = 0.10
    bars = [{"o": 100.0, "h": 105.0, "l": 95.0, "c": 100.0, "v": 1.0} for _ in range(20)]
    val = _range_20d_pct(bars)
    assert val is not None
    assert abs(val - 0.10) < 1e-9


# ---------------------------------------------------------------------------
# 3. Z-score normalization
# ---------------------------------------------------------------------------


def test_zscore_known_values():
    z = _zscore([1.0, 2.0, 3.0])
    # mean=2, stdev (sample) = 1 -> z = [-1, 0, 1]
    assert len(z) == 3
    assert abs(z[0] + 1.0) < 1e-9
    assert abs(z[1]) < 1e-9
    assert abs(z[2] - 1.0) < 1e-9


def test_zscore_constant_values_returns_zero():
    z = _zscore([5.0, 5.0, 5.0])
    assert z == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# 4. ETF classification
# ---------------------------------------------------------------------------


def test_etf_classification_known_etfs():
    for t in ("SPY", "QQQ", "TQQQ", "SQQQ", "ARKK", "UVXY", "SOXL"):
        assert _is_etf(t) is True


def test_etf_classification_equities():
    for t in ("AAPL", "MSFT", "NVDA", "TSLA", "GME", "AMC"):
        assert _is_etf(t) is False


# ---------------------------------------------------------------------------
# 5. Shortlist cutoff -- 200 items -> top 40 correctly sorted
# ---------------------------------------------------------------------------


def test_shortlist_cutoff_sorted_descending():
    # Create 200 synthetic metrics with monotonic realized vol.
    metrics: list[_Metrics] = []
    for i in range(200):
        metrics.append(
            _Metrics(
                ticker=f"T{i:03d}",
                last_close=10.0,
                volume=1_000_000,
                dollar_volume=50_000_000,
                realized_vol_20d=0.1 + i * 0.001,
                atr_pct=0.02,
                range_20d_pct=0.02,
            )
        )
    ranks = _score_and_rank(metrics)
    ranks.sort(key=lambda r: r.composite_score, reverse=True)
    top40 = ranks[:40]
    assert len(top40) == 40
    # Highest realized-vol row must be first
    assert top40[0].ticker == "T199"
    # Scores strictly decreasing
    scores = [r.composite_score for r in top40]
    assert all(scores[i] > scores[i + 1] for i in range(len(scores) - 1))


# ---------------------------------------------------------------------------
# 6. Liquidity filter (volume < 500K removed)
# ---------------------------------------------------------------------------


def test_prefilter_removes_low_volume():
    rows = [
        _GroupedRow("HIGH", 10.0, 1_000_000, 15_000_000, 10.5, 9.5, 0.1),
        _GroupedRow("LOWV", 10.0, 100_000,   15_000_000, 10.5, 9.5, 0.1),
    ]
    out = _prefilter(rows)
    tickers = [r.ticker for r in out]
    assert "HIGH" in tickers
    assert "LOWV" not in tickers


# ---------------------------------------------------------------------------
# 7. Penny-stock filter
# ---------------------------------------------------------------------------


def test_prefilter_removes_penny_stocks():
    rows = [
        _GroupedRow("OK",    5.00, 1_000_000, 15_000_000, 5.1, 4.9, 0.05),
        _GroupedRow("PENNY", 1.50, 5_000_000, 15_000_000, 1.6, 1.4, 0.12),
    ]
    out = _prefilter(rows)
    tickers = [r.ticker for r in out]
    assert "OK" in tickers
    assert "PENNY" not in tickers


def test_prefilter_removes_low_dollar_volume():
    rows = [
        _GroupedRow("OK",   10.0, 1_000_000, 15_000_000, 10.5, 9.5, 0.1),
        _GroupedRow("ILQD", 10.0, 600_000,   5_000_000,  10.5, 9.5, 0.1),
    ]
    out = _prefilter(rows)
    tickers = [r.ticker for r in out]
    assert "OK" in tickers
    assert "ILQD" not in tickers


def test_parse_grouped_rows_drops_malformed():
    raw = [
        {"T": "GOOD", "c": 10.0, "v": 1_000_000, "h": 10.5, "l": 9.5, "vw": 10.0},
        {"T": "BAD"},
        "not a dict",
        {"T": None, "c": 5.0, "v": 1_000_000, "h": 5.1, "l": 4.9},
        {"T": "ZERO", "c": 0.0, "v": 1_000_000, "h": 0.1, "l": 0.0},
        {"T": "TOOLONGTICKER", "c": 10.0, "v": 100, "h": 10.5, "l": 9.5},
    ]
    rows = _parse_grouped_rows(raw)
    assert [r.ticker for r in rows] == ["GOOD"]


# ---------------------------------------------------------------------------
# 8. LLM filter with monkeypatched anthropic client
# ---------------------------------------------------------------------------


def _make_sample_candidates(n: int) -> list[VolRank]:
    out: list[VolRank] = []
    for i in range(n):
        out.append(
            VolRank(
                ticker=f"T{i:03d}",
                name=None,
                last_close=10.0,
                volume=1_000_000,
                dollar_volume=50_000_000,
                realized_vol_20d=0.3,
                atr_pct=0.03,
                range_20d_pct=0.03,
                composite_score=float(n - i),
                is_etf=False,
            )
        )
    return out


class _FakeUsage:
    def __init__(self, inp: int, out: int) -> None:
        self.input_tokens = inp
        self.output_tokens = out


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContentBlock(text)]
        self.usage = _FakeUsage(500, 200)


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(self._text)


class _FakeAnthropicClient:
    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


def test_llm_filter_happy_path(monkeypatch):
    from tradingagents.screener import llm_filter as lf

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    payload = json.dumps(
        [
            {"ticker": "T000", "reason": "clean vol regime"},
            {"ticker": "T002", "reason": "good liquidity"},
            {"ticker": "T001", "reason": "earnings next week"},
        ]
    )
    fake_client = _FakeAnthropicClient(payload)

    class _FakeAnthropicModule:
        @staticmethod
        def Anthropic(api_key: str):  # noqa: N802 -- mimic class name
            return fake_client

    monkeypatch.setitem(__import__("sys").modules, "anthropic", _FakeAnthropicModule)

    candidates = _make_sample_candidates(10)
    kept = lf.llm_filter_shortlist(candidates, "US equities", top_n=3)
    assert [r.ticker for r in kept] == ["T000", "T002", "T001"]
    assert all(r.kept_by_llm for r in kept)
    assert all(r.llm_reason for r in kept)


# ---------------------------------------------------------------------------
# 9. LLM filter fallback when anthropic raises
# ---------------------------------------------------------------------------


class _ExplodingMessages:
    def create(self, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")


class _ExplodingClient:
    def __init__(self) -> None:
        self.messages = _ExplodingMessages()


def test_llm_filter_fallback_on_exception(monkeypatch):
    from tradingagents.screener import llm_filter as lf

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _FakeAnthropicModule:
        @staticmethod
        def Anthropic(api_key: str):  # noqa: N802
            return _ExplodingClient()

    monkeypatch.setitem(__import__("sys").modules, "anthropic", _FakeAnthropicModule)

    candidates = _make_sample_candidates(5)
    kept = lf.llm_filter_shortlist(candidates, "US equities", top_n=3)
    assert len(kept) == 3
    assert [r.ticker for r in kept] == ["T000", "T001", "T002"]
    assert all(not r.kept_by_llm for r in kept)
    assert all(r.llm_reason is None for r in kept)


def test_llm_filter_fallback_when_no_api_key(monkeypatch):
    from tradingagents.screener import llm_filter as lf

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    candidates = _make_sample_candidates(5)
    kept = lf.llm_filter_shortlist(candidates, "US equities", top_n=2)
    assert len(kept) == 2
    assert all(not r.kept_by_llm for r in kept)


# ---------------------------------------------------------------------------
# 10. Cache hit - second call with same date hits zero Polygon calls
# ---------------------------------------------------------------------------


def _install_fake_polygon(monkeypatch, call_counter: dict[str, int]) -> None:
    """Monkeypatch both the grouped + ticker-history HTTP helpers."""

    def fake_grouped(target_date, api_key):  # noqa: ARG001
        call_counter["grouped"] = call_counter.get("grouped", 0) + 1
        # Five tickers, all passing prefilters, with diverse proxy ranges.
        return [
            {"T": "NVDA", "c": 500.0, "v": 10_000_000, "h": 515.0, "l": 490.0, "vw": 500.0},
            {"T": "TSLA", "c": 200.0, "v": 12_000_000, "h": 210.0, "l": 195.0, "vw": 200.0},
            {"T": "SPY",  "c": 450.0, "v": 50_000_000, "h": 452.0, "l": 449.0, "vw": 450.0},
            {"T": "TQQQ", "c":  60.0, "v": 20_000_000, "h":  63.0, "l":  58.0, "vw":  60.0},
            {"T": "AAPL", "c": 180.0, "v": 40_000_000, "h": 181.0, "l": 179.0, "vw": 180.0},
        ]

    def fake_history(ticker, end_date, api_key):  # noqa: ARG001
        call_counter["history"] = call_counter.get("history", 0) + 1
        # Different vol profile per ticker so composites differ.
        base = 100.0
        bars: list[dict[str, float]] = []
        amp = {"NVDA": 0.05, "TSLA": 0.04, "SPY": 0.005, "TQQQ": 0.08, "AAPL": 0.01}.get(ticker, 0.02)
        for i in range(25):
            c = base * (1 + (i % 5 - 2) * amp)
            bars.append({"o": c, "h": c * (1 + amp), "l": c * (1 - amp), "c": c, "v": 1_000_000.0})
        return bars

    monkeypatch.setattr(vs, "_fetch_grouped_daily", fake_grouped)
    monkeypatch.setattr(vs, "_fetch_ticker_history", fake_history)


def test_cache_hit_zero_http_on_second_call(monkeypatch, _polygon_env):
    counter: dict[str, int] = {}
    _install_fake_polygon(monkeypatch, counter)

    r1 = run_screener(target_date=date(2025, 1, 6), use_llm_filter=False)
    assert r1.fetched_ok is True
    assert counter.get("grouped", 0) == 1
    assert counter.get("history", 0) >= 1

    before_hist = counter["history"]
    before_group = counter["grouped"]

    r2 = run_screener(target_date=date(2025, 1, 6), use_llm_filter=False)
    assert r2.fetched_ok is True
    # No additional HTTP calls on cached hit.
    assert counter["grouped"] == before_group
    assert counter["history"] == before_hist
    # Equivalent payload.
    assert [r.ticker for r in r1.equities] == [r.ticker for r in r2.equities]


def test_run_screener_splits_equities_and_etfs(monkeypatch, _polygon_env):
    counter: dict[str, int] = {}
    _install_fake_polygon(monkeypatch, counter)
    r = run_screener(target_date=date(2025, 1, 7), use_llm_filter=False)
    assert r.fetched_ok is True
    eq_tickers = {v.ticker for v in r.equities}
    etf_tickers = {v.ticker for v in r.etfs}
    assert "SPY" in etf_tickers
    assert "TQQQ" in etf_tickers
    assert "NVDA" in eq_tickers or "TSLA" in eq_tickers or "AAPL" in eq_tickers
    assert eq_tickers.isdisjoint(etf_tickers)


# ---------------------------------------------------------------------------
# 11. Missing POLYGON_API_KEY -> fetched_ok=False with clean error
# ---------------------------------------------------------------------------


def test_missing_polygon_key_returns_clean_error(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    r = run_screener(target_date=date(2025, 1, 6))
    assert r.fetched_ok is False
    assert r.error is not None
    assert "POLYGON_API_KEY" in r.error
    assert r.equities == []
    assert r.etfs == []


# ---------------------------------------------------------------------------
# 12. Endpoint integration: GET /api/v3/screener/latest when cache empty -> 404
# ---------------------------------------------------------------------------


def test_screener_latest_endpoint_404_on_empty(monkeypatch, tmp_path):
    # Point both the screener cache AND the route's view of it at an empty dir.
    fake_db = tmp_path / "empty.db"
    monkeypatch.setattr(vs, "_CACHE_DB_PATH", fake_db)

    from fastapi.testclient import TestClient

    from tradingagents.api.routes import screener as screener_route

    # The route imports _CACHE_DB_PATH as a name; patch it on the route module too.
    monkeypatch.setattr(screener_route, "_CACHE_DB_PATH", fake_db)

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(screener_route.router)
    client = TestClient(app)

    resp = client.get("/api/v3/screener/latest")
    assert resp.status_code == 404
    assert "no cached screener result" in resp.json().get("detail", "")


def test_screener_routes_registered():
    from tradingagents.api.routes.screener import router

    paths = {r.path for r in router.routes}
    assert "/api/v3/screener/run" in paths
    assert "/api/v3/screener/latest" in paths
