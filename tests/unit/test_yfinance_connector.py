"""Unit tests for YFinanceConnector."""

import pytest
from unittest.mock import patch, MagicMock

from tradingagents.dataflows.connectors.yfinance_connector import YFinanceConnector
from tradingagents.dataflows.connectors.base import ConnectorCategory, ConnectorError


class TestYFinanceConnectorProperties:
    """Test static connector properties."""

    def setup_method(self):
        self.connector = YFinanceConnector()

    def test_name(self):
        assert self.connector.name == "yfinance"

    def test_tier(self):
        assert self.connector.tier == 1

    def test_categories(self):
        cats = self.connector.categories
        assert ConnectorCategory.MARKET_DATA in cats
        assert ConnectorCategory.NEWS in cats
        assert ConnectorCategory.FUNDAMENTALS in cats
        assert len(cats) == 3

    def test_default_rate_limit(self):
        status = self.connector.rate_limit_status()
        assert status["max"] == 100


class TestYFinanceConnectorDispatch:
    """Test _fetch_impl dispatch to underlying functions."""

    def setup_method(self):
        self.connector = YFinanceConnector()
        self.connector._connected = True  # skip connect() for unit tests

    def test_unknown_data_type_raises(self):
        with pytest.raises(ConnectorError, match="Unknown data_type 'bogus'"):
            self.connector._fetch_impl("AAPL", {"data_type": "bogus"})

    def test_unknown_data_type_lists_supported(self):
        with pytest.raises(ConnectorError, match="ohlcv"):
            self.connector._fetch_impl("AAPL", {"data_type": "nope"})

    @patch("tradingagents.dataflows.y_finance.get_YFin_data_online")
    def test_ohlcv_delegates(self, mock_fn):
        mock_fn.return_value = "Date,Open,Close\n2024-01-01,150,155\n"
        result = self.connector._fetch_impl(
            "AAPL",
            {"data_type": "ohlcv", "start_date": "2024-01-01", "end_date": "2024-01-31"},
        )
        mock_fn.assert_called_once_with("AAPL", "2024-01-01", "2024-01-31")
        assert result["ticker"] == "AAPL"
        assert result["source"] == "yfinance"
        assert "Date,Open,Close" in result["data"]

    @patch("yfinance.download")
    def test_ohlcv_missing_dates_returns_probe(self, mock_download):
        """When no start_date/end_date, connector does a 5d probe download."""
        import pandas as pd

        mock_data = pd.DataFrame(
            {"Close": [155.0], "Volume": [1000000]},
            index=pd.DatetimeIndex(["2024-01-05"]),
        )
        mock_download.return_value = mock_data
        result = self.connector._fetch_impl("AAPL", {"data_type": "ohlcv"})
        assert result["ticker"] == "AAPL"
        assert result["source"] == "yfinance"

    @patch("tradingagents.dataflows.y_finance.get_stock_stats_indicators_window")
    def test_indicators_delegates(self, mock_fn):
        mock_fn.return_value = "## rsi values ...\n2024-01-01: 55.2\n"
        result = self.connector._fetch_impl(
            "AAPL",
            {"data_type": "indicators", "indicator": "rsi", "curr_date": "2024-01-31"},
        )
        mock_fn.assert_called_once_with("AAPL", "rsi", "2024-01-31", 30)
        assert result["data"].startswith("## rsi")

    def test_indicators_missing_params_raises(self):
        with pytest.raises(ConnectorError, match="indicator"):
            self.connector._fetch_impl("AAPL", {"data_type": "indicators"})

    @patch("tradingagents.dataflows.y_finance.get_fundamentals")
    def test_fundamentals_delegates(self, mock_fn):
        mock_fn.return_value = "# Company Fundamentals for AAPL\nPE Ratio: 28"
        result = self.connector._fetch_impl(
            "AAPL", {"data_type": "fundamentals"}
        )
        mock_fn.assert_called_once_with("AAPL", curr_date=None)
        assert result["ticker"] == "AAPL"
        assert "Fundamentals" in result["data"]

    @patch("tradingagents.dataflows.y_finance.get_balance_sheet")
    def test_balance_sheet_delegates(self, mock_fn):
        mock_fn.return_value = "# Balance Sheet data for AAPL (quarterly)\ncsv..."
        result = self.connector._fetch_impl(
            "AAPL",
            {"data_type": "balance_sheet", "freq": "annual", "curr_date": "2024-06-01"},
        )
        mock_fn.assert_called_once_with("AAPL", freq="annual", curr_date="2024-06-01")
        assert result["source"] == "yfinance"

    @patch("tradingagents.dataflows.y_finance.get_cashflow")
    def test_cashflow_delegates(self, mock_fn):
        mock_fn.return_value = "# Cash Flow data\ncsv..."
        result = self.connector._fetch_impl(
            "AAPL", {"data_type": "cashflow"}
        )
        mock_fn.assert_called_once_with("AAPL", freq="quarterly", curr_date=None)
        assert result["ticker"] == "AAPL"

    @patch("tradingagents.dataflows.y_finance.get_income_statement")
    def test_income_statement_delegates(self, mock_fn):
        mock_fn.return_value = "# Income Statement data\ncsv..."
        result = self.connector._fetch_impl(
            "AAPL", {"data_type": "income_statement"}
        )
        mock_fn.assert_called_once_with("AAPL", freq="quarterly", curr_date=None)
        assert result["data"].startswith("# Income Statement")

    @patch("tradingagents.dataflows.yfinance_news.get_news_yfinance")
    def test_news_delegates(self, mock_fn):
        mock_fn.return_value = "## AAPL News, from 2024-01-01 to 2024-01-31:\n..."
        result = self.connector._fetch_impl(
            "AAPL",
            {"data_type": "news", "start_date": "2024-01-01", "end_date": "2024-01-31"},
        )
        mock_fn.assert_called_once_with("AAPL", "2024-01-01", "2024-01-31")
        assert result["source"] == "yfinance"

    def test_news_missing_dates_raises(self):
        with pytest.raises(ConnectorError, match="start_date"):
            self.connector._fetch_impl("AAPL", {"data_type": "news"})

    @patch("tradingagents.dataflows.yfinance_news.get_global_news_yfinance")
    def test_global_news_delegates(self, mock_fn):
        mock_fn.return_value = "## Global Market News\n..."
        result = self.connector._fetch_impl(
            "AAPL",
            {"data_type": "global_news", "curr_date": "2024-01-31"},
        )
        mock_fn.assert_called_once_with("2024-01-31", look_back_days=7, limit=10)
        assert "Global" in result["data"]

    def test_global_news_missing_date_raises(self):
        with pytest.raises(ConnectorError, match="curr_date"):
            self.connector._fetch_impl("AAPL", {"data_type": "global_news"})

    @patch("tradingagents.dataflows.y_finance.get_insider_transactions")
    def test_insider_transactions_delegates(self, mock_fn):
        mock_fn.return_value = "# Insider Transactions data for AAPL\ncsv..."
        result = self.connector._fetch_impl(
            "AAPL", {"data_type": "insider_transactions"}
        )
        mock_fn.assert_called_once_with("AAPL")
        assert result["ticker"] == "AAPL"

    @patch("yfinance.download")
    def test_default_data_type_is_ohlcv(self, mock_download):
        """When no data_type is given, default is 'ohlcv' which does a probe download."""
        import pandas as pd

        mock_data = pd.DataFrame(
            {"Close": [155.0], "Volume": [1000000]},
            index=pd.DatetimeIndex(["2024-01-05"]),
        )
        mock_download.return_value = mock_data
        result = self.connector._fetch_impl("AAPL", {})
        assert result["ticker"] == "AAPL"
        assert result["source"] == "yfinance"
