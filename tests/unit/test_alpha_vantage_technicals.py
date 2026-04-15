"""Unit tests for the Alpha Vantage server-side technical indicators source."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.data.sources import alpha_vantage_technicals as av_tech
from tradingagents.data.sources.alpha_vantage_technicals import (
    AlphaVantageTechnicalsResult,
    _clear_cache,
    fetch_alpha_vantage_technicals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    """Wipe cache AND disable inter-request sleeps so tests stay fast."""
    _clear_cache()
    monkeypatch.setattr(av_tech, "_INTER_REQUEST_SLEEP_SECONDS", 0)
    yield
    _clear_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(status_code: int, json_payload: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    resp.text = text
    return resp


def _rsi_payload(latest_value: float = 55.1234, num_dates: int = 1) -> dict:
    series = {}
    # Use decreasing date strings so "max" -> most recent.
    for i in range(num_dates):
        day = 30 - i
        series[f"2026-04-{day:02d}"] = {"RSI": f"{latest_value - i * 0.1:.4f}"}
    return {"Meta Data": {}, "Technical Analysis: RSI": series}


def _macd_payload(
    macd: float = 2.1, signal: float = 1.5, hist: float = 0.6
) -> dict:
    return {
        "Meta Data": {},
        "Technical Analysis: MACD": {
            "2026-04-04": {
                "MACD": f"{macd}",
                "MACD_Signal": f"{signal}",
                "MACD_Hist": f"{hist}",
            },
            "2026-04-03": {
                "MACD": "1.9",
                "MACD_Signal": "1.4",
                "MACD_Hist": "0.5",
            },
        },
    }


def _bbands_payload(
    upper: float = 210.0, middle: float = 200.0, lower: float = 190.0
) -> dict:
    return {
        "Meta Data": {},
        "Technical Analysis: BBANDS": {
            "2026-04-04": {
                "Real Upper Band": f"{upper}",
                "Real Middle Band": f"{middle}",
                "Real Lower Band": f"{lower}",
            }
        },
    }


def _atr_payload(atr: float = 3.25) -> dict:
    return {
        "Meta Data": {},
        "Technical Analysis: ATR": {"2026-04-04": {"ATR": f"{atr}"}},
    }


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_api_key_returns_failure(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    result = fetch_alpha_vantage_technicals("AAPL")

    assert isinstance(result, AlphaVantageTechnicalsResult)
    assert result.fetched_ok is False
    assert result.error == "ALPHA_VANTAGE_API_KEY not set"
    assert result.rsi_14 is None
    assert result.macd is None


# ---------------------------------------------------------------------------
# Happy path — all 4 endpoints succeed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_all_four_endpoints_success(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")

    responses = [
        _fake_response(200, _rsi_payload(latest_value=55.1234)),
        _fake_response(200, _macd_payload(macd=2.1, signal=1.5, hist=0.6)),
        _fake_response(200, _bbands_payload(upper=210.0, middle=200.0, lower=190.0)),
        _fake_response(200, _atr_payload(atr=3.25)),
    ]
    mock_get = MagicMock(side_effect=responses)

    with patch(
        "tradingagents.data.sources.alpha_vantage_technicals.requests.get",
        mock_get,
    ):
        result = fetch_alpha_vantage_technicals("AAPL")

    assert result.fetched_ok is True
    assert result.error is None
    assert result.rsi_14 == pytest.approx(55.1234)
    assert result.macd == pytest.approx(2.1)
    assert result.macd_signal == pytest.approx(1.5)
    assert result.macd_hist == pytest.approx(0.6)
    assert result.bbands_upper == pytest.approx(210.0)
    assert result.bbands_middle == pytest.approx(200.0)
    assert result.bbands_lower == pytest.approx(190.0)
    assert result.atr_14 == pytest.approx(3.25)
    assert mock_get.call_count == 4


# ---------------------------------------------------------------------------
# Partial failure — rate limit mid-batch
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rate_limit_on_second_endpoint_returns_partial(monkeypatch):
    """If MACD hits a rate limit, RSI should still be populated and
    fetched_ok=False."""
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")

    responses = [
        _fake_response(200, _rsi_payload(latest_value=60.0)),
        _fake_response(
            200,
            {"Note": "Thank you for using Alpha Vantage! ... 5 calls per minute ..."},
        ),
        # These shouldn't be hit because we abort after first rate-limit.
        _fake_response(200, _bbands_payload()),
        _fake_response(200, _atr_payload()),
    ]
    mock_get = MagicMock(side_effect=responses)

    with patch(
        "tradingagents.data.sources.alpha_vantage_technicals.requests.get",
        mock_get,
    ):
        result = fetch_alpha_vantage_technicals("AAPL")

    assert result.fetched_ok is False
    assert result.error is not None
    assert "rate limit" in result.error.lower()
    # RSI was populated before the rate limit hit
    assert result.rsi_14 == pytest.approx(60.0)
    # MACD fields were NOT populated
    assert result.macd is None
    assert result.macd_signal is None
    assert result.macd_hist is None
    # Later endpoints were aborted
    assert result.bbands_upper is None
    assert result.atr_14 is None
    # Exactly 2 HTTP calls (RSI + MACD rate-limited), rest aborted.
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Latest-date extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_latest_date_extraction_picks_max_key(monkeypatch):
    """With 30 dates in the RSI series, the result should use the MAX date."""
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")

    # Build a series where the newest date (2026-04-30) has RSI=99,
    # and older dates have distinctly lower values.
    rsi_series = {
        f"2026-04-{day:02d}": {"RSI": f"{50.0 + day * 0.1:.4f}"}
        for day in range(1, 31)
    }
    rsi_payload = {
        "Meta Data": {},
        "Technical Analysis: RSI": rsi_series,
    }
    expected_latest = 50.0 + 30 * 0.1  # 53.0

    responses = [
        _fake_response(200, rsi_payload),
        _fake_response(200, _macd_payload()),
        _fake_response(200, _bbands_payload()),
        _fake_response(200, _atr_payload()),
    ]
    mock_get = MagicMock(side_effect=responses)

    with patch(
        "tradingagents.data.sources.alpha_vantage_technicals.requests.get",
        mock_get,
    ):
        result = fetch_alpha_vantage_technicals("AAPL")

    assert result.fetched_ok is True
    assert result.rsi_14 == pytest.approx(expected_latest)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cache_hit_avoids_second_batch(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-key")

    responses = [
        _fake_response(200, _rsi_payload()),
        _fake_response(200, _macd_payload()),
        _fake_response(200, _bbands_payload()),
        _fake_response(200, _atr_payload()),
    ]
    mock_get = MagicMock(side_effect=responses)

    with patch(
        "tradingagents.data.sources.alpha_vantage_technicals.requests.get",
        mock_get,
    ):
        first = fetch_alpha_vantage_technicals("AAPL")
        second = fetch_alpha_vantage_technicals("AAPL")

    assert first.fetched_ok is True
    assert second.fetched_ok is True
    # Cache hit: still only 4 HTTP calls (not 8).
    assert mock_get.call_count == 4
    assert first is second
