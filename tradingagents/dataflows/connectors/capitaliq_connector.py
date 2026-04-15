"""Capital IQ data source connector.

Queries the S&P Capital IQ PostgreSQL database (flab2:5432/postgres)
providing institutional-grade OHLCV, fundamentals, financial statements,
news (key developments), insider transactions, and macro economic data.

This is a $70K-80K dataset covering 22M+ companies, 39M+ key developments,
and full Compustat financial data.

DB: flab2:5432/postgres, schema=capitaliq, user=readonly
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_DB_CONFIG = {
    "host": os.environ.get("CAPITALIQ_HOST", "flab2"),
    "port": int(os.environ.get("CAPITALIQ_PORT", "5432")),
    "dbname": os.environ.get("CAPITALIQ_DBNAME", "postgres"),
    "user": os.environ.get("CAPITALIQ_USER", "readonly"),
    "password": os.environ.get("CAPITALIQ_PASSWORD", ""),
    "options": "-c search_path=capitaliq,public",
}


class CapitalIQConnector(BaseConnector):
    """Connector for S&P Capital IQ PostgreSQL database.

    Provides institutional-grade data for all 9 TradingAgents vendor methods:
    OHLCV, indicators, fundamentals, balance sheet, cashflow, income statement,
    news (key developments), global news (macro), insider transactions.
    """

    def __init__(self, db_config: dict | None = None):
        super().__init__(rate_limit=100, rate_period=1.0)  # DB can handle high throughput
        self._db_config = db_config or dict(_DB_CONFIG)
        self._conn = None

    @property
    def name(self) -> str:
        return "capitaliq"

    @property
    def tier(self) -> int:
        return 4  # Institutional grade ($70K-80K dataset)

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [
            ConnectorCategory.MARKET_DATA,
            ConnectorCategory.FUNDAMENTALS,
            ConnectorCategory.NEWS,
            ConnectorCategory.REGULATORY,
            ConnectorCategory.MACRO,
        ]

    def connect(self) -> None:
        """Test database connectivity."""
        try:
            import psycopg2
            conn = psycopg2.connect(**self._db_config)
            conn.close()
            super().connect()
            logger.info("CapitalIQ database connection verified (host=%s)", self._db_config["host"])
        except ImportError:
            raise ConnectorError("psycopg2-binary not installed. Run: pip install psycopg2-binary")
        except Exception as exc:
            raise ConnectorError(f"Cannot connect to Capital IQ database: {exc}") from exc

    @property
    def probe_data_type(self) -> str:
        return "ohlcv"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "ohlcv")
        dispatch = {
            "ohlcv": self._fetch_ohlcv,
            "indicators": self._fetch_indicators,
            "fundamentals": self._fetch_fundamentals,
            "balance_sheet": self._fetch_balance_sheet,
            "cashflow": self._fetch_cashflow,
            "income_statement": self._fetch_income_statement,
            "news": self._fetch_news,
            "global_news": self._fetch_global_news,
            "insider_transactions": self._fetch_insider_transactions,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- Data methods (delegate to capitaliq_provider) -------------------------

    def _fetch_ohlcv(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_stock
        start = params.get("start_date", "2024-01-01")
        end = params.get("end_date", "2025-01-01")
        data = get_capitaliq_stock(ticker, start, end)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "ohlcv"}

    def _fetch_indicators(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_indicator
        indicator = params.get("indicator", "close_50_sma")
        curr_date = params.get("curr_date", "2025-01-01")
        lookback = params.get("look_back_days", 30)
        data = get_capitaliq_indicator(ticker, indicator, curr_date, lookback)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "indicators"}

    def _fetch_fundamentals(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_fundamentals
        curr_date = params.get("curr_date")
        data = get_capitaliq_fundamentals(ticker, curr_date)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "fundamentals"}

    def _fetch_balance_sheet(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_balance_sheet
        freq = params.get("freq", "quarterly")
        curr_date = params.get("curr_date")
        data = get_capitaliq_balance_sheet(ticker, freq, curr_date)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "balance_sheet"}

    def _fetch_cashflow(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_cashflow
        freq = params.get("freq", "quarterly")
        curr_date = params.get("curr_date")
        data = get_capitaliq_cashflow(ticker, freq, curr_date)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "cashflow"}

    def _fetch_income_statement(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_income_statement
        freq = params.get("freq", "quarterly")
        curr_date = params.get("curr_date")
        data = get_capitaliq_income_statement(ticker, freq, curr_date)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "income_statement"}

    def _fetch_news(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_news
        start = params.get("start_date", "2024-01-01")
        end = params.get("end_date", "2025-01-01")
        data = get_capitaliq_news(ticker, start, end)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "news"}

    def _fetch_global_news(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_global_news
        curr_date = params.get("curr_date", "2025-01-01")
        lookback = params.get("look_back_days", 7)
        limit = params.get("limit", 10)
        data = get_capitaliq_global_news(curr_date, lookback, limit)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "global_news"}

    def _fetch_insider_transactions(self, ticker: str, params: dict) -> dict[str, Any]:
        from tradingagents.dataflows.connectors._capitaliq_provider import get_capitaliq_insider_transactions
        data = get_capitaliq_insider_transactions(ticker)
        return {"ticker": ticker, "data": data, "source": "capitaliq", "data_type": "insider_transactions"}
