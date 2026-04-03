"""YFinance data source connector.

Delegates to existing functions in y_finance.py and yfinance_news.py,
providing OHLCV, technical indicators, fundamentals, financial statements,
insider transactions, and news through the unified connector interface.

No API key required — yfinance scrapes public Yahoo Finance data.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)


class YFinanceConnector(BaseConnector):
    """Connector for Yahoo Finance data via the yfinance library.

    Free tier (no API key). Self-imposed rate limit of 100 calls/min
    to avoid Yahoo throttling.
    """

    def __init__(self, rate_limit: int = 100, rate_period: float = 60.0):
        super().__init__(rate_limit=rate_limit, rate_period=rate_period)

    # -- abstract properties ---------------------------------------------------

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [
            ConnectorCategory.MARKET_DATA,
            ConnectorCategory.NEWS,
            ConnectorCategory.FUNDAMENTALS,
        ]

    # -- fetch dispatch --------------------------------------------------------

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
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- data methods ----------------------------------------------------------

    def _fetch_ohlcv(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..y_finance import get_YFin_data_online

        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")
        if not start_date or not end_date:
            raise ConnectorError(
                "ohlcv requires 'start_date' and 'end_date' in params (YYYY-MM-DD)"
            )
        result = get_YFin_data_online(ticker, start_date, end_date)
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_indicators(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..y_finance import get_stock_stats_indicators_window

        indicator = params.get("indicator", "")
        curr_date = params.get("curr_date", "")
        look_back_days = params.get("look_back_days", 30)
        if not indicator or not curr_date:
            raise ConnectorError(
                "indicators requires 'indicator' and 'curr_date' in params"
            )
        result = get_stock_stats_indicators_window(
            ticker, indicator, curr_date, look_back_days
        )
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_fundamentals(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..y_finance import get_fundamentals

        curr_date = params.get("curr_date")
        result = get_fundamentals(ticker, curr_date=curr_date)
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_balance_sheet(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..y_finance import get_balance_sheet

        freq = params.get("freq", "quarterly")
        curr_date = params.get("curr_date")
        result = get_balance_sheet(ticker, freq=freq, curr_date=curr_date)
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_cashflow(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..y_finance import get_cashflow

        freq = params.get("freq", "quarterly")
        curr_date = params.get("curr_date")
        result = get_cashflow(ticker, freq=freq, curr_date=curr_date)
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_income_statement(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..y_finance import get_income_statement

        freq = params.get("freq", "quarterly")
        curr_date = params.get("curr_date")
        result = get_income_statement(ticker, freq=freq, curr_date=curr_date)
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_news(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..yfinance_news import get_news_yfinance

        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")
        if not start_date or not end_date:
            raise ConnectorError(
                "news requires 'start_date' and 'end_date' in params (YYYY-MM-DD)"
            )
        result = get_news_yfinance(ticker, start_date, end_date)
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_global_news(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..yfinance_news import get_global_news_yfinance

        curr_date = params.get("curr_date", "")
        if not curr_date:
            raise ConnectorError("global_news requires 'curr_date' in params")
        look_back_days = params.get("look_back_days", 7)
        limit = params.get("limit", 10)
        result = get_global_news_yfinance(curr_date, look_back_days=look_back_days, limit=limit)
        return {"ticker": ticker, "data": result, "source": "yfinance"}

    def _fetch_insider_transactions(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        from ..y_finance import get_insider_transactions

        result = get_insider_transactions(ticker)
        return {"ticker": ticker, "data": result, "source": "yfinance"}
