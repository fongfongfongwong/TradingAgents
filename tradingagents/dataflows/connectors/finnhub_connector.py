"""Finnhub data source connector.

Finnhub provides real-time market data, news, sentiment, insider transactions,
and analyst ratings with a generous free tier (60 calls/min).

Requires FINNHUB_API_KEY environment variable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubConnector(BaseConnector):
    """Connector for Finnhub financial data API.

    Free tier: 60 API calls/minute, WebSocket for real-time quotes.
    """

    def __init__(self, api_key: str | None = None):
        super().__init__(rate_limit=60, rate_period=60.0)
        self._api_key = api_key or os.environ.get("FINNHUB_API_KEY", "")
        self._session = requests.Session()

    @property
    def name(self) -> str:
        return "finnhub"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [
            ConnectorCategory.MARKET_DATA,
            ConnectorCategory.NEWS,
            ConnectorCategory.SENTIMENT,
        ]

    def connect(self) -> None:
        if not self._api_key:
            raise ConnectorError(
                "FINNHUB_API_KEY not set. Get a free key at https://finnhub.io/"
            )
        self._session.params = {"token": self._api_key}  # type: ignore[assignment]
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "quote")
        dispatch = {
            "quote": self._fetch_quote,
            "news": self._fetch_news,
            "sentiment": self._fetch_sentiment,
            "insider_transactions": self._fetch_insider_transactions,
            "analyst_ratings": self._fetch_analyst_ratings,
            "earnings": self._fetch_earnings,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- data methods ---------------------------------------------------------

    def _fetch_quote(self, ticker: str, params: dict) -> dict[str, Any]:
        resp = self._get("/quote", {"symbol": ticker})
        return {
            "ticker": ticker,
            "current_price": resp.get("c"),
            "change": resp.get("d"),
            "percent_change": resp.get("dp"),
            "high": resp.get("h"),
            "low": resp.get("l"),
            "open": resp.get("o"),
            "previous_close": resp.get("pc"),
            "timestamp": resp.get("t"),
            "source": "finnhub",
        }

    def _fetch_news(self, ticker: str, params: dict) -> dict[str, Any]:
        days_back = params.get("days_back", 7)
        end = datetime.now()
        start = end - timedelta(days=days_back)
        resp = self._get(
            "/company-news",
            {
                "symbol": ticker,
                "from": start.strftime("%Y-%m-%d"),
                "to": end.strftime("%Y-%m-%d"),
            },
        )
        articles = []
        for item in resp if isinstance(resp, list) else []:
            articles.append({
                "title": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "published_at": item.get("datetime"),
                "tickers": [ticker],
                "sentiment_score": None,
            })
        return {
            "ticker": ticker,
            "articles": articles,
            "total": len(articles),
            "source": "finnhub",
        }

    def _fetch_sentiment(self, ticker: str, params: dict) -> dict[str, Any]:
        resp = self._get("/news-sentiment", {"symbol": ticker})
        sentiment = resp.get("sentiment", {})
        buzz = resp.get("buzz", {})
        return {
            "ticker": ticker,
            "bullish_percent": sentiment.get("bullishPercent"),
            "bearish_percent": sentiment.get("bearishPercent"),
            "articles_in_last_week": buzz.get("articlesInLastWeek"),
            "buzz_score": buzz.get("buzz"),
            "weighted_average": buzz.get("weeklyAverage"),
            "company_news_score": resp.get("companyNewsScore"),
            "sector_average_bullish": resp.get("sectorAverageBullishPercent"),
            "sector_average_news_score": resp.get("sectorAverageNewsScore"),
            "source": "finnhub",
        }

    def _fetch_insider_transactions(self, ticker: str, params: dict) -> dict[str, Any]:
        resp = self._get("/stock/insider-transactions", {"symbol": ticker})
        transactions = []
        for txn in resp.get("data", [])[:20]:  # limit to recent 20
            transactions.append({
                "insider_name": txn.get("name", ""),
                "share": txn.get("share", 0),
                "change": txn.get("change", 0),
                "transaction_date": txn.get("transactionDate", ""),
                "transaction_code": txn.get("transactionCode", ""),
                "filing_date": txn.get("filingDate", ""),
            })
        return {
            "ticker": ticker,
            "transactions": transactions,
            "total": len(transactions),
            "source": "finnhub",
        }

    def _fetch_analyst_ratings(self, ticker: str, params: dict) -> dict[str, Any]:
        resp = self._get("/stock/recommendation", {"symbol": ticker})
        ratings = []
        for item in resp if isinstance(resp, list) else []:
            ratings.append({
                "period": item.get("period", ""),
                "strong_buy": item.get("strongBuy", 0),
                "buy": item.get("buy", 0),
                "hold": item.get("hold", 0),
                "sell": item.get("sell", 0),
                "strong_sell": item.get("strongSell", 0),
            })
        return {
            "ticker": ticker,
            "ratings": ratings[:6],  # last 6 months
            "source": "finnhub",
        }

    def _fetch_earnings(self, ticker: str, params: dict) -> dict[str, Any]:
        resp = self._get("/stock/earnings", {"symbol": ticker})
        earnings = []
        for item in resp if isinstance(resp, list) else []:
            earnings.append({
                "period": item.get("period", ""),
                "actual": item.get("actual"),
                "estimate": item.get("estimate"),
                "surprise": item.get("surprise"),
                "surprise_percent": item.get("surprisePercent"),
            })
        return {
            "ticker": ticker,
            "earnings": earnings,
            "source": "finnhub",
        }

    # -- HTTP helper ----------------------------------------------------------

    def _get(self, endpoint: str, params: dict) -> Any:
        """Execute GET request with error handling."""
        url = f"{_BASE_URL}{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                raise ConnectorError("Finnhub API rate limit hit") from exc
            raise ConnectorError(f"Finnhub API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"Finnhub connection error: {exc}") from exc
