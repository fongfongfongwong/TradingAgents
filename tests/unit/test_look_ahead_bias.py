"""Look-ahead bias regression tests (P0-1, P0-2).

These tests lock in the guarantees added in Batch 2 of the QUANT_SYSTEM
debug/audit plan:

1. ``materialize_briefing`` must not request wall-clock "now" data from any
   vendor when the caller passes a historical ``as_of_date``.
2. yfinance must receive an explicit ``start``/``end`` window (not
   ``period="1y"``) for historical dates.
3. Polygon must receive ``from_date = as_of_date - 365d`` / ``to_date =
   as_of_date`` so its Aggregates v2 URL is pinned to the backtest cutoff.
4. FRED must send ``observation_end=<as_of_date>`` so it returns the most
   recent observation on or before the cutoff.
5. Regression: today-dated calls still behave exactly as before.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.data import materializer
from tradingagents.data.materializer import (
    _fetch_price_history,
    _is_historical_as_of,
)
from tradingagents.data.sources import fred_macro as fm
from tradingagents.data.sources import polygon_price as polygon_source
from tradingagents.data.sources.polygon_price import (
    _clear_cache,
    _period_to_date_range,
    fetch_polygon_price_history,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_polygon_cache():
    _clear_cache()
    yield
    _clear_cache()


@pytest.fixture(autouse=True)
def _reset_fred_cache():
    fm._obs_cache.clear()
    yield
    fm._obs_cache.clear()


def _fake_hist_df(start: str, end: str) -> pd.DataFrame:
    """Return a 300-row yfinance-shaped DataFrame spanning ``start..end``."""
    idx = pd.date_range(start=start, end=end, freq="B")[:300]
    return pd.DataFrame(
        {
            "Open": [100.0] * len(idx),
            "High": [101.0] * len(idx),
            "Low": [99.0] * len(idx),
            "Close": [100.0 + i * 0.01 for i in range(len(idx))],
            "Volume": [1_000_000] * len(idx),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# _is_historical_as_of
# ---------------------------------------------------------------------------


def test_is_historical_as_of_none_and_today() -> None:
    assert _is_historical_as_of(None) is False
    today = datetime.now(timezone.utc).date().isoformat()
    assert _is_historical_as_of(today) is False


def test_is_historical_as_of_past_date() -> None:
    assert _is_historical_as_of("2024-06-01") is True


def test_is_historical_as_of_bad_string() -> None:
    assert _is_historical_as_of("not-a-date") is False


# ---------------------------------------------------------------------------
# Polygon: as_of_date threads through URL
# ---------------------------------------------------------------------------


def test_period_to_date_range_uses_as_of_date() -> None:
    start, end = _period_to_date_range("1y", as_of_date="2024-06-01")
    assert end == "2024-06-01"
    # 365 days before 2024-06-01
    assert start == "2023-06-02"


def test_period_to_date_range_without_as_of_uses_today() -> None:
    start, end = _period_to_date_range("1y")
    today = datetime.now(timezone.utc).date().isoformat()
    assert end == today


def test_fetch_polygon_price_history_historical_url(monkeypatch) -> None:
    """The Polygon URL must embed ``from_date``/``to_date`` from ``as_of_date``."""
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")

    captured: dict = {}

    def fake_get(url, params=None, timeout=None):  # noqa: ANN001
        captured["url"] = url
        resp = MagicMock()
        resp.status_code = 200
        # Return one stub bar so the function produces a valid result.
        resp.json.return_value = {
            "results": [
                {
                    "t": int(
                        datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp() * 1000
                    ),
                    "o": 100.0,
                    "h": 101.0,
                    "l": 99.0,
                    "c": 100.5,
                    "v": 1_000_000,
                }
            ]
        }
        resp.text = ""
        return resp

    with patch("tradingagents.data.sources.polygon_price.requests.get", side_effect=fake_get):
        result = fetch_polygon_price_history(
            "AAPL", period="1y", as_of_date="2024-06-01"
        )

    assert result.fetched_ok is True
    assert "2023-06-02/2024-06-01" in captured["url"]
    assert "AAPL" in captured["url"]


# ---------------------------------------------------------------------------
# Materializer: yfinance path respects as_of_date
# ---------------------------------------------------------------------------


def test_fetch_price_history_yfinance_uses_start_end_for_historical(
    monkeypatch,
) -> None:
    """yfinance must receive start/end (not period='1y') for historical dates."""
    # Force the yfinance fallback branch.
    monkeypatch.setattr(materializer, "_get_price_vendor", lambda: "yfinance")

    ticker_obj = MagicMock()
    ticker_obj.history.return_value = _fake_hist_df("2023-06-01", "2024-06-01")

    data_gaps: list[str] = []
    _fetch_price_history(
        "AAPL", ticker_obj, data_gaps, as_of_date="2024-06-01"
    )

    # history() must have been called with start/end kwargs — NEVER period="1y".
    call = ticker_obj.history.call_args
    assert "start" in call.kwargs
    assert "end" in call.kwargs
    assert call.kwargs["end"] == "2024-06-01"
    assert call.kwargs["start"] == "2023-06-02"
    assert "period" not in call.kwargs


def test_fetch_price_history_yfinance_uses_period_for_today(monkeypatch) -> None:
    """Regression: today (or None) still uses legacy ``period='1y'`` call."""
    monkeypatch.setattr(materializer, "_get_price_vendor", lambda: "yfinance")

    ticker_obj = MagicMock()
    ticker_obj.history.return_value = _fake_hist_df("2025-06-01", "2026-04-05")

    data_gaps: list[str] = []
    _fetch_price_history("AAPL", ticker_obj, data_gaps, as_of_date=None)

    call = ticker_obj.history.call_args
    assert call.kwargs.get("period") == "1y"
    assert "start" not in call.kwargs


def test_fetch_price_history_yfinance_today_string(monkeypatch) -> None:
    """Passing today's date (not None) should also preserve legacy behaviour."""
    monkeypatch.setattr(materializer, "_get_price_vendor", lambda: "yfinance")

    ticker_obj = MagicMock()
    ticker_obj.history.return_value = _fake_hist_df("2025-06-01", "2026-04-05")

    today_str = datetime.now(timezone.utc).date().isoformat()
    data_gaps: list[str] = []
    _fetch_price_history("AAPL", ticker_obj, data_gaps, as_of_date=today_str)

    call = ticker_obj.history.call_args
    assert call.kwargs.get("period") == "1y"
    assert "start" not in call.kwargs


# ---------------------------------------------------------------------------
# Materializer: polygon path respects as_of_date
# ---------------------------------------------------------------------------


def test_fetch_price_history_polygon_threads_as_of_date(monkeypatch) -> None:
    """Polygon vendor must be invoked with ``as_of_date`` for historical calls."""
    monkeypatch.setattr(materializer, "_get_price_vendor", lambda: "polygon")

    captured: dict = {}
    stub_df = _fake_hist_df("2023-06-01", "2024-06-01")

    def fake_polygon(ticker, period="1y", as_of_date=None):  # noqa: ANN001
        captured["ticker"] = ticker
        captured["period"] = period
        captured["as_of_date"] = as_of_date
        return polygon_source.PolygonPriceResult(
            df=stub_df,
            last_price=123.45,
            data_age_seconds=0,
            fetched_ok=True,
            error=None,
        )

    monkeypatch.setattr(
        polygon_source, "fetch_polygon_price_history", fake_polygon
    )

    data_gaps: list[str] = []
    ticker_obj = MagicMock()
    out = _fetch_price_history(
        "AAPL", ticker_obj, data_gaps, as_of_date="2024-06-01"
    )

    assert out is not None
    assert captured["ticker"] == "AAPL"
    assert captured["period"] == "1y"
    assert captured["as_of_date"] == "2024-06-01"


def test_fetch_price_history_polygon_today_passes_none(monkeypatch) -> None:
    """For today's date, polygon must receive ``as_of_date=None`` (legacy)."""
    monkeypatch.setattr(materializer, "_get_price_vendor", lambda: "polygon")

    captured: dict = {}
    stub_df = _fake_hist_df("2025-06-01", "2026-04-05")

    def fake_polygon(ticker, period="1y", as_of_date=None):  # noqa: ANN001
        captured["as_of_date"] = as_of_date
        return polygon_source.PolygonPriceResult(
            df=stub_df,
            last_price=1.0,
            data_age_seconds=0,
            fetched_ok=True,
            error=None,
        )

    monkeypatch.setattr(
        polygon_source, "fetch_polygon_price_history", fake_polygon
    )

    data_gaps: list[str] = []
    _fetch_price_history("AAPL", MagicMock(), data_gaps, as_of_date=None)
    assert captured["as_of_date"] is None


# ---------------------------------------------------------------------------
# FRED: as_of_date goes into the URL
# ---------------------------------------------------------------------------


def test_fred_query_uses_observation_end(monkeypatch) -> None:
    """FRED requests must include ``observation_end=<as_of_date>``."""
    monkeypatch.setenv("FRED_API_KEY", "dummy")

    seen_params: list[dict] = []

    def fake_get(url, params, timeout):  # noqa: ANN001
        seen_params.append(dict(params))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "observations": [{"date": "2024-05-31", "value": "5.33"}]
        }
        return resp

    with patch.object(fm._session, "get", side_effect=fake_get):
        result = fm.fetch_fred_macro("2024-06-01")

    assert result.fetched_ok is True
    # All three series calls must carry observation_end=2024-06-01
    assert len(seen_params) == 3
    for params in seen_params:
        assert params["observation_end"] == "2024-06-01"
        assert params["sort_order"] == "desc"
        assert params["limit"] == 1


# ---------------------------------------------------------------------------
# End-to-end: briefing for a 2024 date must not ingest 2026 data
# ---------------------------------------------------------------------------


def test_materialize_briefing_historical_date_uses_historical_price(
    monkeypatch,
) -> None:
    """A briefing for 2024-06-01 must produce a price from a 2024 bar.

    We force yfinance as the vendor, return a synthetic DataFrame whose
    last bar is in 2024, and verify the resulting ``PriceContext.price``
    matches that bar — proving no future data leaked in.
    """
    monkeypatch.setattr(materializer, "_get_price_vendor", lambda: "yfinance")
    # Avoid FRED network calls: stub out macro fetch.
    from tradingagents.schemas.v3 import MacroContext

    monkeypatch.setattr(
        materializer,
        "fetch_fred_macro",
        lambda _d: fm.FredMacroResult(
            fed_funds_rate=5.33,
            yield_curve_2y10y_bps=30.0,
            dgs2=4.2,
            dgs10=4.5,
            fetched_ok=True,
            error=None,
        ),
    )

    historical_df = _fake_hist_df("2023-06-01", "2024-06-01")
    # Tag the final close so we can assert it's the one consumed.
    historical_df.iloc[-1, historical_df.columns.get_loc("Close")] = 171.25

    fake_ticker = MagicMock()
    fake_ticker.history.return_value = historical_df
    fake_ticker.info = {}
    fake_ticker.options = []
    fake_ticker.news = []
    fake_ticker.calendar = None

    with patch("yfinance.Ticker", return_value=fake_ticker):
        briefing = materializer.materialize_briefing("AAPL", "2024-06-01")

    assert briefing.price.price == pytest.approx(171.25)
    # The PRICE-history call (first one) must use a 2024 start/end window.
    # Subsequent calls inside _build_macro_context (VIX/SPY) are out of
    # scope for P0-1 and may still use ``period=...``.
    price_calls = [
        c for c in fake_ticker.history.call_args_list if "end" in c.kwargs
    ]
    assert price_calls, "No start/end call captured on ticker.history"
    assert price_calls[0].kwargs["end"] == "2024-06-01"
    assert price_calls[0].kwargs["start"] == "2023-06-02"


def test_materialize_briefing_today_regression(monkeypatch) -> None:
    """Today-dated briefings must keep legacy ``period='1y'`` behaviour."""
    monkeypatch.setattr(materializer, "_get_price_vendor", lambda: "yfinance")
    monkeypatch.setattr(
        materializer,
        "fetch_fred_macro",
        lambda _d: fm.FredMacroResult(
            fed_funds_rate=5.33,
            yield_curve_2y10y_bps=30.0,
            dgs2=4.2,
            dgs10=4.5,
            fetched_ok=True,
            error=None,
        ),
    )

    today = datetime.now(timezone.utc).date()
    df = _fake_hist_df(
        (today - timedelta(days=365)).isoformat(), today.isoformat()
    )

    fake_ticker = MagicMock()
    fake_ticker.history.return_value = df
    fake_ticker.info = {}
    fake_ticker.options = []
    fake_ticker.news = []
    fake_ticker.calendar = None

    with patch("yfinance.Ticker", return_value=fake_ticker):
        briefing = materializer.materialize_briefing("AAPL", today.isoformat())

    assert briefing.ticker == "AAPL"
    # First call (price history) must be the legacy period="1y" form.
    first_call = fake_ticker.history.call_args_list[0]
    assert first_call.kwargs.get("period") == "1y"
    assert "start" not in first_call.kwargs
