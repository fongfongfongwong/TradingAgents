"""Unit tests for the Polygon price source and materializer integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.data.sources import polygon_price as polygon_source
from tradingagents.data.sources.polygon_price import (
    PolygonPriceResult,
    _clear_cache,
    _period_to_date_range,
    fetch_polygon_price_history,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    """Wipe the in-process polygon cache before every test."""
    _clear_cache()
    yield
    _clear_cache()


def _build_fake_polygon_payload(num_bars: int = 120) -> dict:
    """Return a Polygon aggregates-shaped payload with *num_bars* daily bars."""
    now = datetime.now(timezone.utc)
    results = []
    base_price = 200.0
    for i in range(num_bars):
        ts = now - timedelta(days=num_bars - i)
        price = base_price + i * 0.5
        results.append(
            {
                "t": int(ts.timestamp() * 1000),
                "o": price - 0.5,
                "h": price + 1.0,
                "l": price - 1.0,
                "c": price,
                "v": 50_000_000 + i * 1_000,
            }
        )
    return {"ticker": "AAPL", "resultsCount": num_bars, "results": results}


def _fake_response(status_code: int, json_payload: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# fetch_polygon_price_history — error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_returns_error_when_no_api_key(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)

    result = fetch_polygon_price_history("AAPL", "1y")

    assert isinstance(result, PolygonPriceResult)
    assert result.fetched_ok is False
    assert result.error == "POLYGON_API_KEY not set"
    assert result.df is None
    assert result.last_price is None


@pytest.mark.unit
def test_fetch_returns_error_on_401(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "fake-key")

    with patch(
        "tradingagents.data.sources.polygon_price.requests.get",
        return_value=_fake_response(401, text="Unauthorized"),
    ):
        result = fetch_polygon_price_history("AAPL", "1y")

    assert result.fetched_ok is False
    assert result.df is None
    assert "401" in (result.error or "")


@pytest.mark.unit
def test_fetch_returns_error_on_empty_results(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "fake-key")

    with patch(
        "tradingagents.data.sources.polygon_price.requests.get",
        return_value=_fake_response(200, {"results": []}),
    ):
        result = fetch_polygon_price_history("AAPL", "1y")

    assert result.fetched_ok is False
    assert result.df is None
    assert "empty" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# fetch_polygon_price_history — success path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_happy_path_returns_dataframe(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "fake-key")
    payload = _build_fake_polygon_payload(num_bars=120)

    with patch(
        "tradingagents.data.sources.polygon_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_polygon_price_history("AAPL", "1y")

    assert result.fetched_ok is True
    assert result.error is None
    assert result.df is not None
    assert list(result.df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(result.df) == 120
    assert isinstance(result.df.index, pd.DatetimeIndex)
    # Index should be monotonically increasing
    assert result.df.index.is_monotonic_increasing
    # last_price == last row's Close
    assert result.last_price == round(float(result.df["Close"].iloc[-1]), 4)
    # Data age should be non-negative
    assert result.data_age_seconds >= 0


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cache_hit_avoids_second_http_call(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "fake-key")
    payload = _build_fake_polygon_payload(num_bars=60)

    mock_get = MagicMock(return_value=_fake_response(200, payload))
    with patch("tradingagents.data.sources.polygon_price.requests.get", mock_get):
        first = fetch_polygon_price_history("AAPL", "1y")
        second = fetch_polygon_price_history("AAPL", "1y")

    assert first.fetched_ok is True
    assert second.fetched_ok is True
    # Two calls, one HTTP request thanks to the cache.
    assert mock_get.call_count == 1
    # Same object returned from cache (frozen dataclass equality).
    assert first is second


@pytest.mark.unit
def test_cache_miss_on_different_period(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "fake-key")
    payload = _build_fake_polygon_payload(num_bars=30)

    mock_get = MagicMock(return_value=_fake_response(200, payload))
    with patch("tradingagents.data.sources.polygon_price.requests.get", mock_get):
        fetch_polygon_price_history("AAPL", "1mo")
        fetch_polygon_price_history("AAPL", "1y")

    # Different periods -> different cache keys -> two HTTP calls.
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Period -> date-range mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "period,expected_days",
    [("1mo", 30), ("3mo", 90), ("6mo", 180), ("1y", 365), ("2y", 730), ("5y", 1825)],
)
def test_period_to_date_range_mapping(period: str, expected_days: int):
    from_str, to_str = _period_to_date_range(period)
    from_date = datetime.fromisoformat(from_str).date()
    to_date = datetime.fromisoformat(to_str).date()
    delta_days = (to_date - from_date).days
    assert delta_days == expected_days


@pytest.mark.unit
def test_period_to_date_range_unknown_defaults_to_1y():
    from_str, to_str = _period_to_date_range("not-a-real-period")
    from_date = datetime.fromisoformat(from_str).date()
    to_date = datetime.fromisoformat(to_str).date()
    assert (to_date - from_date).days == 365


# ---------------------------------------------------------------------------
# Materializer integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_materializer_uses_polygon_when_configured(monkeypatch):
    """Monkeypatch fetch_polygon_price_history -> stub, set runtime vendor to
    polygon, and verify the resulting briefing.price.price matches the stub.
    """
    from tradingagents.api.routes import config as config_module
    from tradingagents.data import materializer

    # Build a stub polygon result with 200 deterministic rows.
    now = datetime.now(timezone.utc)
    index = pd.DatetimeIndex(
        [now - timedelta(days=200 - i) for i in range(200)], name="Date"
    )
    base = 150.0
    closes = [base + i * 0.25 for i in range(200)]
    stub_df = pd.DataFrame(
        {
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i * 1000 for i in range(200)],
        },
        index=index,
    )
    stub_last_price = round(float(stub_df["Close"].iloc[-1]), 4)
    stub_result = PolygonPriceResult(
        df=stub_df,
        last_price=stub_last_price,
        data_age_seconds=0,
        fetched_ok=True,
        error=None,
    )

    monkeypatch.setattr(
        polygon_source, "fetch_polygon_price_history", lambda *a, **kw: stub_result
    )

    # Flip runtime config to polygon (in-memory, no disk I/O required).
    from tradingagents.api.models.responses import RuntimeConfig

    cfg = RuntimeConfig(data_vendor_price="polygon")
    monkeypatch.setattr(config_module, "_runtime_cfg_cache", cfg)

    # Stub out other network-bound context builders so the test is hermetic.
    monkeypatch.setattr(
        materializer,
        "_build_options_context",
        lambda *a, **kw: materializer.OptionsContext(data_age_seconds=0),
    )
    monkeypatch.setattr(
        materializer,
        "_build_news_context",
        lambda *a, **kw: materializer.NewsContext(data_age_seconds=0),
    )
    monkeypatch.setattr(
        materializer,
        "_build_social_context",
        lambda *a, **kw: materializer.SocialContext(
            mention_volume_vs_avg=1.0,
            sentiment_score=0.0,
            trending_narratives=[],
            data_age_seconds=0,
        ),
    )
    monkeypatch.setattr(
        materializer,
        "_build_macro_context",
        lambda *a, **kw: materializer.MacroContext(
            regime=materializer.Regime(
                label="neutral",
                confidence=0.5,
                drivers=[],
            )
            if hasattr(materializer, "Regime")
            else materializer.MacroContext().regime,
            data_age_seconds=0,
        )
        if False
        else materializer.MacroContext(data_age_seconds=0),
    )
    monkeypatch.setattr(
        materializer,
        "_build_event_calendar",
        lambda *a, **kw: materializer.EventCalendar(),
    )

    # yfinance Ticker should never be consulted for price — but we still
    # need a harmless stub so the constructor works.
    with patch("tradingagents.data.materializer.yf.Ticker") as mock_ticker:
        mock_ticker.return_value = MagicMock()
        briefing = materializer.materialize_briefing("AAPL", "2026-04-05")

    assert briefing.price.price == stub_last_price
    assert briefing.price.price > 0
    # The polygon_fallback gap must NOT be present on the happy path.
    assert not any(
        g.startswith("price:polygon_fallback") for g in briefing.data_gaps
    )


@pytest.mark.unit
def test_materializer_falls_back_when_polygon_fails(monkeypatch):
    """If polygon fetch fails, materializer must fall through to yfinance
    and append a ``price:polygon_fallback`` gap.
    """
    from tradingagents.api.routes import config as config_module
    from tradingagents.data import materializer

    failing_result = PolygonPriceResult(
        df=None,
        last_price=None,
        data_age_seconds=0,
        fetched_ok=False,
        error="simulated failure",
    )
    monkeypatch.setattr(
        polygon_source,
        "fetch_polygon_price_history",
        lambda *a, **kw: failing_result,
    )

    from tradingagents.api.models.responses import RuntimeConfig

    cfg = RuntimeConfig(data_vendor_price="polygon")
    monkeypatch.setattr(config_module, "_runtime_cfg_cache", cfg)

    data_gaps: list[str] = []
    mock_yf = MagicMock()
    # Return a DataFrame large enough for all downstream compute.
    now = datetime.now(timezone.utc)
    idx = pd.DatetimeIndex([now - timedelta(days=250 - i) for i in range(250)])
    fake_hist = pd.DataFrame(
        {
            "Open": [100.0 + i * 0.1 for i in range(250)],
            "High": [101.0 + i * 0.1 for i in range(250)],
            "Low": [99.0 + i * 0.1 for i in range(250)],
            "Close": [100.5 + i * 0.1 for i in range(250)],
            "Volume": [1_000_000 for _ in range(250)],
        },
        index=idx,
    )
    mock_yf.history.return_value = fake_hist

    ctx = materializer._build_price_context("AAPL", mock_yf, data_gaps)

    assert any(g.startswith("price:polygon_fallback") for g in data_gaps)
    assert ctx.price > 0  # yfinance fallback populated the context


@pytest.mark.unit
def test_materializer_yfinance_path_untouched(monkeypatch):
    """Default vendor (``yfinance``) must NEVER call polygon and must NOT
    append any polygon_fallback gap.
    """
    from tradingagents.api.routes import config as config_module
    from tradingagents.data import materializer

    # Sentinel: if polygon is called, raise.
    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("polygon must not be called when vendor=yfinance")

    monkeypatch.setattr(
        polygon_source, "fetch_polygon_price_history", _should_not_be_called
    )

    from tradingagents.api.models.responses import RuntimeConfig

    cfg = RuntimeConfig(data_vendor_price="yfinance")
    monkeypatch.setattr(config_module, "_runtime_cfg_cache", cfg)

    mock_yf = MagicMock()
    now = datetime.now(timezone.utc)
    idx = pd.DatetimeIndex([now - timedelta(days=250 - i) for i in range(250)])
    fake_hist = pd.DataFrame(
        {
            "Open": [100.0 + i * 0.1 for i in range(250)],
            "High": [101.0 + i * 0.1 for i in range(250)],
            "Low": [99.0 + i * 0.1 for i in range(250)],
            "Close": [100.5 + i * 0.1 for i in range(250)],
            "Volume": [1_000_000 for _ in range(250)],
        },
        index=idx,
    )
    mock_yf.history.return_value = fake_hist

    data_gaps: list[str] = []
    ctx = materializer._build_price_context("AAPL", mock_yf, data_gaps)

    assert ctx.price > 0
    assert not any("polygon" in g for g in data_gaps)
