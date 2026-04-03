"""Unit tests for the SEC EDGAR connector – all HTTP calls are mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from tradingagents.dataflows.connectors.base import ConnectorCategory, ConnectorError
from tradingagents.dataflows.connectors.sec_edgar_connector import SECEdgarConnector


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

COMPANY_TICKERS_RESPONSE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
}

SUBMISSIONS_RESPONSE = {
    "cik": "0000320193",
    "name": "Apple Inc.",
    "entityType": "operating",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "stateOfIncorporation": "CA",
    "fiscalYearEnd": "0928",
    "exchanges": ["Nasdaq"],
    "ein": "942404110",
    "website": "https://www.apple.com",
    "phone": "408-996-1010",
    "addresses": {"mailing": {}, "business": {}},
    "filings": {
        "recent": {
            "form": ["10-K", "10-Q", "8-K", "10-Q"],
            "filingDate": ["2024-11-01", "2024-08-02", "2024-07-15", "2024-05-03"],
            "accessionNumber": [
                "0000320193-24-000100",
                "0000320193-24-000080",
                "0000320193-24-000070",
                "0000320193-24-000050",
            ],
            "primaryDocument": [
                "aapl-20240928.htm",
                "aapl-20240629.htm",
                "aapl-20240715.htm",
                "aapl-20240330.htm",
            ],
        }
    },
}

XBRL_FACTS_RESPONSE = {
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {"end": "2023-09-30", "val": 383285000000, "form": "10-K", "filed": "2023-11-02"},
                        {"end": "2024-09-28", "val": 391035000000, "form": "10-K", "filed": "2024-11-01"},
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {"end": "2024-09-28", "val": 93736000000, "form": "10-K", "filed": "2024-11-01"},
                    ]
                }
            },
        }
    },
}


@pytest.fixture
def connector():
    return SECEdgarConnector()


def _mock_get_factory(url_to_json: dict[str, dict]):
    """Return a side_effect function that dispatches on the requested URL."""

    def side_effect(url, *, params=None, timeout=None):
        resp = MagicMock()
        for pattern, json_data in url_to_json.items():
            if pattern in url:
                resp.status_code = 200
                resp.json.return_value = json_data
                resp.raise_for_status.return_value = None
                return resp
        # Default: 404
        http_err = requests.exceptions.HTTPError(response=MagicMock(status_code=404))
        resp.raise_for_status.side_effect = http_err
        return resp

    return side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProperties:
    def test_name(self, connector):
        assert connector.name == "sec_edgar"

    def test_tier(self, connector):
        assert connector.tier == 1

    def test_categories(self, connector):
        assert ConnectorCategory.REGULATORY in connector.categories
        assert ConnectorCategory.FUNDAMENTALS in connector.categories


class TestCIKResolution:
    @patch.object(SECEdgarConnector, "_get")
    def test_resolve_cik_success(self, mock_get, connector):
        mock_get.return_value = COMPANY_TICKERS_RESPONSE
        cik = connector._resolve_cik("AAPL")
        assert cik == "0000320193"
        assert len(cik) == 10

    @patch.object(SECEdgarConnector, "_get")
    def test_resolve_cik_case_insensitive(self, mock_get, connector):
        mock_get.return_value = COMPANY_TICKERS_RESPONSE
        cik = connector._resolve_cik("aapl")
        assert cik == "0000320193"

    @patch.object(SECEdgarConnector, "_get")
    def test_resolve_cik_cached(self, mock_get, connector):
        mock_get.return_value = COMPANY_TICKERS_RESPONSE
        connector._resolve_cik("AAPL")
        connector._resolve_cik("AAPL")
        # _get called only once because second call hits cache
        mock_get.assert_called_once()

    @patch.object(SECEdgarConnector, "_get")
    def test_resolve_cik_unknown_ticker(self, mock_get, connector):
        mock_get.return_value = COMPANY_TICKERS_RESPONSE
        with pytest.raises(ConnectorError, match="not found"):
            connector._resolve_cik("ZZZZZZ")


class TestFetchFilings:
    @patch.object(SECEdgarConnector, "_get")
    def test_fetch_filings_all(self, mock_get, connector):
        def route(url, params=None, timeout=None):
            if "company_tickers" in url:
                return COMPANY_TICKERS_RESPONSE
            return SUBMISSIONS_RESPONSE

        mock_get.side_effect = route
        connector._connected = True

        result = connector.fetch("AAPL", {"data_type": "filings"})
        assert result["ticker"] == "AAPL"
        assert result["cik"] == "0000320193"
        assert result["total"] == 4
        assert result["filings"][0]["form_type"] == "10-K"
        assert result["source"] == "sec_edgar"

    @patch.object(SECEdgarConnector, "_get")
    def test_fetch_filings_with_form_filter(self, mock_get, connector):
        def route(url, params=None, timeout=None):
            if "company_tickers" in url:
                return COMPANY_TICKERS_RESPONSE
            return SUBMISSIONS_RESPONSE

        mock_get.side_effect = route
        connector._connected = True

        result = connector.fetch("AAPL", {"data_type": "filings", "form_type": "10-K"})
        assert all(f["form_type"] == "10-K" for f in result["filings"])
        assert result["total"] == 1

    @patch.object(SECEdgarConnector, "_get")
    def test_fetch_filings_with_limit(self, mock_get, connector):
        def route(url, params=None, timeout=None):
            if "company_tickers" in url:
                return COMPANY_TICKERS_RESPONSE
            return SUBMISSIONS_RESPONSE

        mock_get.side_effect = route
        connector._connected = True

        result = connector.fetch("AAPL", {"data_type": "filings", "limit": 2})
        assert result["total"] == 2


class TestFetchFinancials:
    @patch.object(SECEdgarConnector, "_get")
    def test_fetch_financials(self, mock_get, connector):
        def route(url, params=None, timeout=None):
            if "company_tickers" in url:
                return COMPANY_TICKERS_RESPONSE
            return XBRL_FACTS_RESPONSE

        mock_get.side_effect = route
        connector._connected = True

        result = connector.fetch("AAPL", {"data_type": "financials"})
        assert result["entity_name"] == "Apple Inc."
        assert "Revenues" in result["financials"]
        rev = result["financials"]["Revenues"]
        assert rev["unit"] == "USD"
        assert len(rev["recent_values"]) == 2
        assert result["source"] == "sec_edgar"


class TestFetchCompanyInfo:
    @patch.object(SECEdgarConnector, "_get")
    def test_fetch_company_info(self, mock_get, connector):
        def route(url, params=None, timeout=None):
            if "company_tickers" in url:
                return COMPANY_TICKERS_RESPONSE
            return SUBMISSIONS_RESPONSE

        mock_get.side_effect = route
        connector._connected = True

        result = connector.fetch("AAPL", {"data_type": "company_info"})
        assert result["name"] == "Apple Inc."
        assert result["sic"] == "3571"
        assert result["cik"] == "0000320193"
        assert result["source"] == "sec_edgar"


class TestErrorHandling:
    def test_unknown_data_type(self, connector):
        connector._connected = True
        with pytest.raises(ConnectorError, match="Unknown data_type"):
            connector.fetch("AAPL", {"data_type": "nonexistent"})

    def test_http_429_raises_rate_limit(self, connector):
        """Test that _get converts HTTP 429 into ConnectorError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {}
        http_err = requests.exceptions.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err
        connector._connected = True

        with patch.object(connector._session, "get", return_value=mock_resp):
            with pytest.raises(ConnectorError, match="rate limit"):
                connector.fetch("AAPL", {"data_type": "company_info"})

    def test_connection_error(self, connector):
        """Test that _get converts ConnectionError into ConnectorError."""
        connector._connected = True

        with patch.object(
            connector._session, "get",
            side_effect=requests.exceptions.ConnectionError("timeout"),
        ):
            with pytest.raises(ConnectorError, match="connection error"):
                connector.fetch("AAPL", {"data_type": "company_info"})


class TestUserAgent:
    def test_default_user_agent(self):
        c = SECEdgarConnector()
        assert "TradingAgents" in c._session.headers["User-Agent"]

    def test_custom_user_agent(self):
        c = SECEdgarConnector(user_agent="MyApp admin@my.com")
        assert c._session.headers["User-Agent"] == "MyApp admin@my.com"
