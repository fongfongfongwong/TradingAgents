"""Unit tests for FREDConnector."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.connectors.base import ConnectorCategory, ConnectorError
from tradingagents.dataflows.connectors.fred_connector import FREDConnector, KEY_SERIES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def connector():
    """Return a FREDConnector with a dummy API key."""
    return FREDConnector(api_key="test-key-123")


@pytest.fixture
def connected(connector):
    """Return a connected FREDConnector."""
    connector.connect()
    return connector


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_name(self, connector):
        assert connector.name == "fred"

    def test_tier(self, connector):
        assert connector.tier == 1

    def test_categories(self, connector):
        assert connector.categories == [ConnectorCategory.MACRO]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class TestConnection:
    def test_connect_without_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            c = FREDConnector(api_key="")
            with pytest.raises(ConnectorError, match="FRED_API_KEY not set"):
                c.connect()

    def test_connect_with_env_var(self):
        with patch.dict(os.environ, {"FRED_API_KEY": "env-key"}):
            c = FREDConnector()
            c.connect()
            assert c.is_connected

    def test_disconnect(self, connected):
        connected.disconnect()
        assert not connected.is_connected


# ---------------------------------------------------------------------------
# Series fetch
# ---------------------------------------------------------------------------

class TestFetchSeries:
    _MOCK_RESPONSE = {
        "count": 2,
        "units": "Percent",
        "frequency": "Monthly",
        "observations": [
            {"date": "2024-01-01", "value": "3.7"},
            {"date": "2024-02-01", "value": "3.9"},
        ],
    }

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_fetch_series_basic(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        result = c._fetch_impl("UNRATE", {"data_type": "series"})

        assert result["series_id"] == "UNRATE"
        assert len(result["observations"]) == 2
        assert result["observations"][0]["date"] == "2024-01-01"
        assert result["source"] == "fred"

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_fetch_series_with_date_params(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        c._fetch_impl("GDP", {
            "data_type": "series",
            "observation_start": "2023-01-01",
            "observation_end": "2024-01-01",
        })

        call_kwargs = mock_session.get.call_args
        sent_params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert sent_params["series_id"] == "GDP"
        assert sent_params["observation_start"] == "2023-01-01"
        assert sent_params["observation_end"] == "2024-01-01"

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_fetch_series_empty_observations(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"observations": []}
        mock_resp.raise_for_status.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        result = c._fetch_impl("FAKE_SERIES", {"data_type": "series"})

        assert result["observations"] == []
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestFetchSearch:
    _MOCK_SEARCH = {
        "count": 1,
        "seriess": [
            {
                "id": "UNRATE",
                "title": "Unemployment Rate",
                "frequency": "Monthly",
                "units": "Percent",
                "observation_start": "1948-01-01",
                "observation_end": "2024-03-01",
                "popularity": 95,
            }
        ],
    }

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_search(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._MOCK_SEARCH
        mock_resp.raise_for_status.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        result = c._fetch_impl("unemployment", {"data_type": "search"})

        assert result["query"] == "unemployment"
        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == "UNRATE"
        assert result["source"] == "fred"


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

class TestFetchReleases:
    _MOCK_RELEASES = {
        "releases": [
            {"id": 53, "name": "GDP", "press_release": True, "link": "https://example.com"},
        ],
    }

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_releases(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._MOCK_RELEASES
        mock_resp.raise_for_status.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        result = c._fetch_impl("", {"data_type": "releases"})

        assert len(result["releases"]) == 1
        assert result["releases"][0]["name"] == "GDP"
        assert result["source"] == "fred"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_unknown_data_type(self, connected):
        with pytest.raises(ConnectorError, match="Unknown data_type 'invalid'"):
            connected._fetch_impl("X", {"data_type": "invalid"})

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_http_error(self, mock_session_cls):
        import requests as req

        mock_resp = MagicMock()
        http_error = req.exceptions.HTTPError(response=MagicMock(status_code=500))
        mock_resp.raise_for_status.side_effect = http_error

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        with pytest.raises(ConnectorError, match="FRED API error"):
            c._fetch_impl("GDP", {"data_type": "series"})

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_rate_limit_error(self, mock_session_cls):
        import requests as req

        mock_resp_obj = MagicMock(status_code=429)
        http_error = req.exceptions.HTTPError(response=mock_resp_obj)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = http_error

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        with pytest.raises(ConnectorError, match="FRED API rate limit hit"):
            c._fetch_impl("GDP", {"data_type": "series"})

    @patch("tradingagents.dataflows.connectors.fred_connector.requests.Session")
    def test_connection_error(self, mock_session_cls):
        import requests as req

        mock_session = MagicMock()
        mock_session.get.side_effect = req.exceptions.ConnectionError("timeout")
        mock_session_cls.return_value = mock_session

        c = FREDConnector(api_key="test-key")
        c.connect()
        with pytest.raises(ConnectorError, match="FRED connection error"):
            c._fetch_impl("GDP", {"data_type": "series"})


# ---------------------------------------------------------------------------
# Key series constant
# ---------------------------------------------------------------------------

class TestKeySeries:
    def test_key_series_contains_expected(self):
        for sid in ("GDP", "UNRATE", "CPIAUCSL", "FEDFUNDS", "T10Y2Y",
                     "T10YIE", "VIXCLS", "DGS10", "DGS2"):
            assert sid in KEY_SERIES
