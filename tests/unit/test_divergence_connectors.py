"""Tests for divergence data source connectors with mocked HTTP responses."""

import pytest
from unittest.mock import patch, MagicMock

from tradingagents.dataflows.connectors.base import ConnectorError, ConnectorCategory
from tradingagents.dataflows.connectors.cboe_connector import CBOEConnector
from tradingagents.dataflows.connectors.apewisdom_connector import ApeWisdomConnector
from tradingagents.dataflows.connectors.aaii_connector import AAIIConnector
from tradingagents.dataflows.connectors.fear_greed_connector import (
    FearGreedConnector,
    _classify_score,
)


# =============================================================================
# CBOE Connector Tests
# =============================================================================

class TestCBOEConnector:
    @pytest.fixture
    def connector(self):
        return CBOEConnector()

    def test_name_and_tier(self, connector):
        assert connector.name == "cboe"
        assert connector.tier == 1
        assert ConnectorCategory.DIVERGENCE in connector.categories

    @patch("tradingagents.dataflows.connectors.cboe_connector.requests.Session.get")
    def test_fetch_vix(self, mock_get, connector):
        csv_data = (
            "DATE,OPEN,HIGH,LOW,CLOSE\n"
            "01/02/2024,13.20,13.85,12.80,13.10\n"
            "01/03/2024,13.50,14.20,13.00,14.00\n"
        )
        mock_resp = MagicMock()
        mock_resp.text = csv_data
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("VIX", {"data_type": "vix"})
        assert result["ticker"] == "VIX"
        assert result["close"] == 14.00
        assert result["date"] == "01/03/2024"
        assert result["source"] == "cboe"

    @patch("tradingagents.dataflows.connectors.cboe_connector.requests.Session.get")
    def test_fetch_put_call_ratio(self, mock_get, connector):
        csv_data = (
            "TRADE_DATE,EQUITY_PC_RATIO,INDEX_PC_RATIO,TOTAL_PC_RATIO\n"
            "2024-01-02,0.65,1.20,0.82\n"
            "2024-01-03,0.70,1.15,0.85\n"
        )
        mock_resp = MagicMock()
        mock_resp.text = csv_data
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("SPX", {"data_type": "put_call_ratio"})
        assert result["equity_pc_ratio"] == 0.70
        assert result["index_pc_ratio"] == 1.15
        assert result["total_pc_ratio"] == 0.85
        assert result["source"] == "cboe"

    @patch("tradingagents.dataflows.connectors.cboe_connector.requests.Session.get")
    def test_fetch_vix_http_error(self, mock_get, connector):
        mock_get.side_effect = __import__("requests").exceptions.ConnectionError("timeout")
        with pytest.raises(ConnectorError, match="CBOE VIX fetch error"):
            connector.fetch("VIX", {"data_type": "vix"})

    def test_unknown_data_type(self, connector):
        connector.connect()
        with pytest.raises(ConnectorError, match="Unknown data_type"):
            connector._fetch_impl("VIX", {"data_type": "invalid"})


# =============================================================================
# ApeWisdom Connector Tests
# =============================================================================

class TestApeWisdomConnector:
    @pytest.fixture
    def connector(self):
        return ApeWisdomConnector()

    def test_name_and_tier(self, connector):
        assert connector.name == "apewisdom"
        assert connector.tier == 1
        assert ConnectorCategory.DIVERGENCE in connector.categories
        assert ConnectorCategory.SENTIMENT in connector.categories

    @patch("tradingagents.dataflows.connectors.apewisdom_connector.requests.Session.get")
    def test_fetch_ticker_mentions(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "ticker": "GME",
                    "name": "GameStop Corp",
                    "rank": 1,
                    "mentions": 542,
                    "upvotes": 12345,
                    "rank_24h_ago": 2,
                    "mentions_24h_ago": 410,
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("GME", {"data_type": "mentions"})
        assert result["ticker"] == "GME"
        assert result["mentions"] == 542
        assert result["upvotes"] == 12345
        assert result["rank"] == 1
        assert result["source"] == "apewisdom"

    @patch("tradingagents.dataflows.connectors.apewisdom_connector.requests.Session.get")
    def test_fetch_trending(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"ticker": "GME", "name": "GameStop", "rank": 1, "mentions": 542, "upvotes": 12345},
                {"ticker": "AMC", "name": "AMC Ent", "rank": 2, "mentions": 320, "upvotes": 8900},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("", {"data_type": "trending"})
        assert result["total"] == 2
        assert result["trending"][0]["ticker"] == "GME"
        assert result["source"] == "apewisdom"

    @patch("tradingagents.dataflows.connectors.apewisdom_connector.requests.Session.get")
    def test_fetch_empty_results(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("ZZZZ", {"data_type": "mentions"})
        assert result["mentions"] == 0
        assert result["rank"] is None

    def test_unknown_data_type(self, connector):
        connector.connect()
        with pytest.raises(ConnectorError, match="Unknown data_type"):
            connector._fetch_impl("GME", {"data_type": "invalid"})


# =============================================================================
# AAII Connector Tests
# =============================================================================

class TestAAIIConnector:
    @pytest.fixture
    def connector(self):
        return AAIIConnector()

    def test_name_and_tier(self, connector):
        assert connector.name == "aaii"
        assert connector.tier == 1
        assert ConnectorCategory.DIVERGENCE in connector.categories

    @patch("tradingagents.dataflows.connectors.aaii_connector.requests.Session.get")
    def test_fetch_sentiment_parsed(self, mock_get, connector):
        html = """
        <html><body>
        <p>Bullish: 38.5%</p>
        <p>Neutral: 30.2%</p>
        <p>Bearish: 31.3%</p>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("", {"data_type": "sentiment"})
        assert result["bullish_pct"] == 38.5
        assert result["bearish_pct"] == 31.3
        assert result["neutral_pct"] == 30.2
        assert result["bull_bear_spread"] == 7.2
        assert result["source"] == "aaii"

    @patch("tradingagents.dataflows.connectors.aaii_connector.requests.Session.get")
    def test_fetch_sentiment_fallback(self, mock_get, connector):
        mock_get.side_effect = __import__("requests").exceptions.ConnectionError("timeout")

        result = connector.fetch("", {"data_type": "sentiment"})
        assert result["bullish_pct"] is None
        assert result["source"] == "aaii"
        assert "note" in result

    def test_unknown_data_type(self, connector):
        connector.connect()
        with pytest.raises(ConnectorError, match="Unknown data_type"):
            connector._fetch_impl("", {"data_type": "invalid"})


# =============================================================================
# Fear & Greed Connector Tests
# =============================================================================

class TestFearGreedConnector:
    @pytest.fixture
    def connector(self):
        return FearGreedConnector()

    def test_name_and_tier(self, connector):
        assert connector.name == "fear_greed"
        assert connector.tier == 1
        assert ConnectorCategory.DIVERGENCE in connector.categories
        assert ConnectorCategory.SENTIMENT in connector.categories

    @patch("tradingagents.dataflows.connectors.fear_greed_connector.requests.Session.get")
    def test_fetch_current(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "fear_and_greed": {
                "score": 72.5,
                "timestamp": "2024-01-15T16:00:00Z",
                "previous_close": 70.0,
                "previous_1_week": 65.0,
                "previous_1_month": 55.0,
                "previous_1_year": 40.0,
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("", {"data_type": "current"})
        assert result["value"] == 72.5
        assert result["rating"] == "Greed"
        assert result["timestamp"] == "2024-01-15T16:00:00Z"
        assert result["source"] == "cnn_fear_greed"

    @patch("tradingagents.dataflows.connectors.fear_greed_connector.requests.Session.get")
    def test_fetch_extreme_fear(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "fear_and_greed": {
                "score": 15.0,
                "timestamp": "2024-01-15T16:00:00Z",
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch("", {"data_type": "current"})
        assert result["value"] == 15.0
        assert result["rating"] == "Extreme Fear"

    @patch("tradingagents.dataflows.connectors.fear_greed_connector.requests.Session.get")
    def test_fetch_http_error(self, mock_get, connector):
        mock_get.side_effect = __import__("requests").exceptions.ConnectionError("timeout")
        with pytest.raises(ConnectorError, match="CNN Fear & Greed API error"):
            connector.fetch("", {"data_type": "current"})

    def test_unknown_data_type(self, connector):
        connector.connect()
        with pytest.raises(ConnectorError, match="Unknown data_type"):
            connector._fetch_impl("", {"data_type": "invalid"})

    def test_classify_score_boundaries(self):
        assert _classify_score(0) == "Extreme Fear"
        assert _classify_score(25) == "Extreme Fear"
        assert _classify_score(26) == "Fear"
        assert _classify_score(45) == "Fear"
        assert _classify_score(50) == "Neutral"
        assert _classify_score(56) == "Greed"
        assert _classify_score(75) == "Greed"
        assert _classify_score(76) == "Extreme Greed"
        assert _classify_score(100) == "Extreme Greed"
