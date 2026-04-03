"""Tests for FinnhubConnector with mocked HTTP responses."""

import pytest
from unittest.mock import patch, MagicMock

from tradingagents.dataflows.connectors.base import ConnectorError
from tradingagents.dataflows.connectors.finnhub_connector import FinnhubConnector


@pytest.fixture
def connector():
    return FinnhubConnector(api_key="test_key_123")


class TestFinnhubLifecycle:
    def test_name(self, connector):
        assert connector.name == "finnhub"

    def test_tier(self, connector):
        assert connector.tier == 1

    def test_connect_without_key_raises(self):
        c = FinnhubConnector(api_key="")
        with pytest.raises(ConnectorError, match="FINNHUB_API_KEY"):
            c.connect()

    def test_connect_with_key_succeeds(self, connector):
        connector.connect()
        assert connector.is_connected


class TestFetchQuote:
    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_fetch_quote(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "c": 150.25, "d": 2.5, "dp": 1.69,
            "h": 151.0, "l": 148.0, "o": 149.0, "pc": 147.75, "t": 1700000000,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("AAPL", {"data_type": "quote"})
        assert result["ticker"] == "AAPL"
        assert result["current_price"] == 150.25
        assert result["source"] == "finnhub"


class TestFetchNews:
    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_fetch_news(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "headline": "AAPL beats earnings",
                "summary": "Apple reported strong Q4",
                "source": "Reuters",
                "url": "https://example.com/1",
                "datetime": 1700000000,
            },
            {
                "headline": "AAPL new product",
                "summary": "Apple announces Vision Pro 2",
                "source": "Bloomberg",
                "url": "https://example.com/2",
                "datetime": 1700100000,
            },
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("AAPL", {"data_type": "news", "days_back": 7})
        assert result["total"] == 2
        assert result["articles"][0]["title"] == "AAPL beats earnings"
        assert result["articles"][1]["source"] == "Bloomberg"


class TestFetchSentiment:
    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_fetch_sentiment(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "buzz": {"articlesInLastWeek": 45, "buzz": 1.2, "weeklyAverage": 30},
            "companyNewsScore": 0.85,
            "sectorAverageBullishPercent": 0.55,
            "sectorAverageNewsScore": 0.5,
            "sentiment": {"bearishPercent": 0.2, "bullishPercent": 0.8},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("AAPL", {"data_type": "sentiment"})
        assert result["bullish_percent"] == 0.8
        assert result["bearish_percent"] == 0.2
        assert result["articles_in_last_week"] == 45


class TestFetchInsiderTransactions:
    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_fetch_insider(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {
                    "name": "Tim Cook",
                    "share": 100000,
                    "change": -5000,
                    "transactionDate": "2024-01-15",
                    "transactionCode": "S",
                    "filingDate": "2024-01-17",
                },
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("AAPL", {"data_type": "insider_transactions"})
        assert result["total"] == 1
        assert result["transactions"][0]["insider_name"] == "Tim Cook"


class TestFetchAnalystRatings:
    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_fetch_ratings(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"period": "2024-01", "strongBuy": 15, "buy": 20, "hold": 5, "sell": 2, "strongSell": 0},
            {"period": "2024-02", "strongBuy": 16, "buy": 18, "hold": 6, "sell": 1, "strongSell": 1},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("AAPL", {"data_type": "analyst_ratings"})
        assert len(result["ratings"]) == 2
        assert result["ratings"][0]["strong_buy"] == 15


class TestFetchEarnings:
    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_fetch_earnings(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"period": "2024-Q4", "actual": 2.18, "estimate": 2.10, "surprise": 0.08, "surprisePercent": 3.81},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("AAPL", {"data_type": "earnings"})
        assert result["earnings"][0]["actual"] == 2.18
        assert result["earnings"][0]["surprise_percent"] == 3.81


class TestErrorHandling:
    def test_unknown_data_type_raises(self, connector):
        connector.connect()
        with pytest.raises(ConnectorError, match="Unknown data_type"):
            connector._fetch_impl("AAPL", {"data_type": "invalid"})

    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_http_error_raises(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = __import__("requests").exceptions.HTTPError(
            response=MagicMock(status_code=500)
        )
        mock_get.return_value = mock_resp

        with pytest.raises(ConnectorError, match="Finnhub API error"):
            connector.fetch("AAPL", {"data_type": "quote"})

    @patch("tradingagents.dataflows.connectors.finnhub_connector.requests.Session.get")
    def test_connection_error_raises(self, mock_get, connector):
        mock_get.side_effect = __import__("requests").exceptions.ConnectionError("timeout")

        with pytest.raises(ConnectorError, match="Finnhub connection error"):
            connector.fetch("AAPL", {"data_type": "quote"})
