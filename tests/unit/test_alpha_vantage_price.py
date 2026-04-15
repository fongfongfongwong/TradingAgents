"""Unit tests for the Alpha Vantage price source and materializer integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.data.sources import alpha_vantage_price as av_source
from tradingagents.data.sources.alpha_vantage_price import (
    AlphaVantagePriceResult,
    _clear_cache,
    fetch_alpha_vantage_price_history,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    """Wipe the in-process Alpha Vantage cache before every test."""
    _clear_cache()
    yield
    _clear_cache()


def _build_fake_daily_payload(num_bars: int = 120) -> dict:
    """Return an Alpha Vantage TIME_SERIES_DAILY_ADJUSTED-shaped payload.

    ``"5. adjusted close"`` is set distinctly from ``"4. close"`` so the
    tests can verify the parser picks the *adjusted* close.
    """
    today = datetime.now(timezone.utc).date()
    series: dict[str, dict[str, str]] = {}
    base_price = 200.0
    for i in range(num_bars):
        d = today - timedelta(days=num_bars - 1 - i)
        price = base_price + i * 0.5
        series[d.isoformat()] = {
            "1. open": f"{price - 0.5:.4f}",
            "2. high": f"{price + 1.0:.4f}",
            "3. low": f"{price - 1.0:.4f}",
            "4. close": f"{price - 10.0:.4f}",  # raw close — should NOT be used
            "5. adjusted close": f"{price:.4f}",
            "6. volume": f"{50_000_000 + i * 1000}",
            "7. dividend amount": "0.0000",
            "8. split coefficient": "1.0",
        }
    return {
        "Meta Data": {"1. Information": "fake", "2. Symbol": "AAPL"},
        "Time Series (Daily)": series,
    }


def _fake_response(status_code: int, json_payload: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# fetch_alpha_vantage_price_history — error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_returns_error_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    result = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert isinstance(result, AlphaVantagePriceResult)
    assert result.fetched_ok is False
    assert result.error == "ALPHA_VANTAGE_API_KEY not set"
    assert result.df is None
    assert result.last_price is None


@pytest.mark.unit
def test_fetch_returns_error_on_non_200(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")

    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(500, text="server down"),
    ):
        result = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert result.fetched_ok is False
    assert result.df is None
    assert "500" in (result.error or "")


@pytest.mark.unit
def test_fetch_returns_error_on_note_rate_limit(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    payload = {
        "Note": (
            "Thank you for using Alpha Vantage! Our standard API call "
            "frequency is 5 calls per minute and 500 calls per day."
        )
    }
    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert result.fetched_ok is False
    assert result.df is None
    assert "rate limit" in (result.error or "").lower()


@pytest.mark.unit
def test_fetch_returns_error_on_information_rate_limit(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    payload = {
        "Information": (
            "Thank you for using Alpha Vantage! This is a premium endpoint. "
            "Please subscribe to a premium plan."
        )
    }
    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert result.fetched_ok is False
    assert result.df is None
    assert "rate limit" in (result.error or "").lower()


@pytest.mark.unit
def test_fetch_returns_error_on_error_message(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    payload = {
        "Error Message": (
            "Invalid API call. Please retry or visit the documentation."
        )
    }
    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_alpha_vantage_price_history("NOT_A_TICKER", "1y")

    assert result.fetched_ok is False
    assert result.df is None
    assert "error" in (result.error or "").lower()


@pytest.mark.unit
def test_fetch_returns_error_on_empty_time_series(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    payload = {"Meta Data": {}, "Time Series (Daily)": {}}
    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert result.fetched_ok is False
    assert result.df is None
    assert "empty" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# fetch_alpha_vantage_price_history — success path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_happy_path_returns_dataframe(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    payload = _build_fake_daily_payload(num_bars=120)

    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert result.fetched_ok is True
    assert result.error is None
    assert result.df is not None
    assert list(result.df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(result.df) == 120
    assert isinstance(result.df.index, pd.DatetimeIndex)
    # Sort ascending: first index < last index
    assert result.df.index[0] < result.df.index[-1]
    assert result.df.index.is_monotonic_increasing
    # last_price == last row's adjusted Close
    assert result.last_price == round(float(result.df["Close"].iloc[-1]), 4)
    # Data age non-negative
    assert result.data_age_seconds >= 0


@pytest.mark.unit
def test_fetch_uses_adjusted_close(monkeypatch):
    """Close column must come from "5. adjusted close", not "4. close"."""
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    payload = _build_fake_daily_payload(num_bars=10)

    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert result.fetched_ok is True
    assert result.df is not None
    # adjusted_close ~ base + i*0.5, raw close is adjusted - 10.
    # Smallest Close should therefore be ~200.0 (not ~190.0).
    min_close = float(result.df["Close"].min())
    assert min_close >= 199.9, f"expected adjusted close ~200, got {min_close}"


@pytest.mark.unit
def test_period_filtering_1mo(monkeypatch):
    """Period='1mo' must limit the DataFrame to the last ~30 days."""
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    # 365 days of data, but ask for 1mo -> should trim to ~30.
    payload = _build_fake_daily_payload(num_bars=365)

    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get",
        return_value=_fake_response(200, payload),
    ):
        result = fetch_alpha_vantage_price_history("AAPL", "1mo")

    assert result.fetched_ok is True
    assert result.df is not None
    # 1mo = 30 days; allow some slack for calendar arithmetic.
    assert len(result.df) <= 32
    assert len(result.df) >= 28


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cache_hit_avoids_second_http_call(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")
    payload = _build_fake_daily_payload(num_bars=60)

    mock_get = MagicMock(return_value=_fake_response(200, payload))
    with patch(
        "tradingagents.data.sources.alpha_vantage_price.requests.get", mock_get
    ):
        first = fetch_alpha_vantage_price_history("AAPL", "1y")
        second = fetch_alpha_vantage_price_history("AAPL", "1y")

    assert first.fetched_ok is True
    assert second.fetched_ok is True
    assert mock_get.call_count == 1
    assert first is second


# ---------------------------------------------------------------------------
# Materializer integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_materializer_uses_alpha_vantage_when_configured(monkeypatch):
    """Monkeypatch fetch_alpha_vantage_price_history -> stub, set runtime vendor
    to alpha_vantage, and verify briefing.price.price matches the stub."""
    from tradingagents.api.routes import config as config_module
    from tradingagents.data import materializer

    # Pin index to end at the test date so _slice_to_as_of doesn't cut rows
    as_of = datetime(2026, 4, 5, tzinfo=timezone.utc)
    index = pd.DatetimeIndex(
        [as_of - timedelta(days=200 - i) for i in range(200)], name="Date"
    )
    base = 175.0
    closes = [base + i * 0.25 for i in range(200)]
    stub_df = pd.DataFrame(
        {
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [2_000_000 + i * 1000 for i in range(200)],
        },
        index=index,
    )
    stub_last_price = round(float(stub_df["Close"].iloc[-1]), 4)
    stub_result = AlphaVantagePriceResult(
        df=stub_df,
        last_price=stub_last_price,
        data_age_seconds=0,
        fetched_ok=True,
        error=None,
    )

    monkeypatch.setattr(
        av_source, "fetch_alpha_vantage_price_history", lambda *a, **kw: stub_result
    )

    from tradingagents.api.models.responses import RuntimeConfig

    cfg = RuntimeConfig(data_vendor_price="alpha_vantage")
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
        lambda *a, **kw: materializer.MacroContext(data_age_seconds=0),
    )
    monkeypatch.setattr(
        materializer,
        "_build_event_calendar",
        lambda *a, **kw: materializer.EventCalendar(),
    )

    with patch("tradingagents.data.materializer.yf.Ticker") as mock_ticker:
        mock_ticker.return_value = MagicMock()
        briefing = materializer.materialize_briefing("AAPL", "2026-04-05")

    assert briefing.price.price == stub_last_price
    assert briefing.price.price > 0
    # No fallback gap on the happy path.
    assert not any(
        g.startswith("price:alpha_vantage_fallback") for g in briefing.data_gaps
    )


@pytest.mark.unit
def test_materializer_falls_back_when_alpha_vantage_fails(monkeypatch):
    """If Alpha Vantage fails (rate limit), materializer must fall through to
    yfinance and append a ``price:alpha_vantage_fallback`` gap."""
    from tradingagents.api.routes import config as config_module
    from tradingagents.data import materializer

    failing_result = AlphaVantagePriceResult(
        df=None,
        last_price=None,
        data_age_seconds=0,
        fetched_ok=False,
        error="alpha_vantage rate limit: 5/min hit",
    )
    monkeypatch.setattr(
        av_source,
        "fetch_alpha_vantage_price_history",
        lambda *a, **kw: failing_result,
    )

    from tradingagents.api.models.responses import RuntimeConfig

    cfg = RuntimeConfig(data_vendor_price="alpha_vantage")
    monkeypatch.setattr(config_module, "_runtime_cfg_cache", cfg)

    data_gaps: list[str] = []
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

    ctx = materializer._build_price_context("AAPL", mock_yf, data_gaps)

    assert any(g.startswith("price:alpha_vantage_fallback") for g in data_gaps)
    assert ctx.price > 0  # yfinance fallback populated the context
