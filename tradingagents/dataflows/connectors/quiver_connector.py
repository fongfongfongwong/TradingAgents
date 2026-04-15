"""Quiver Quant data source connector.

Provides congressional trading data, Reddit sentiment, and lobbying
expenditure data. Requires QUIVER_API_KEY environment variable for
live API access; falls back to realistic mock data when unavailable.
"""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.quiverquant.com/beta"


class QuiverConnector(BaseConnector):
    """Connector for Quiver Quant alternative data API.

    Tier 2: paid API with congressional trades, Reddit sentiment, and
    lobbying data. Falls back to realistic mock data when API key is absent.
    """

    TIER = 2
    CATEGORIES = ["SENTIMENT", "ALTERNATIVE"]

    _DATA_TYPES = ("congressional_trades", "reddit_sentiment", "lobbying")

    def __init__(self, api_key: str | None = None) -> None:
        super().__init__(rate_limit=30, rate_period=60.0)
        self._api_key = api_key or os.environ.get("QUIVER_API_KEY", "")
        self._session = requests.Session()
        self._use_mock = not bool(self._api_key)

    @property
    def name(self) -> str:
        return "quiver"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.SENTIMENT, ConnectorCategory.ALTERNATIVE]

    def connect(self) -> None:
        if self._api_key:
            self._session.headers.update(
                {"Authorization": f"Bearer {self._api_key}"}
            )
        else:
            logger.warning(
                "QUIVER_API_KEY not set — using mock data. "
                "Get a key at https://www.quiverquant.com/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "congressional_trades"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "congressional_trades")
        dispatch = {
            "congressional_trades": self._fetch_congressional_trades,
            "reddit_sentiment": self._fetch_reddit_sentiment,
            "lobbying": self._fetch_lobbying,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- congressional trades ---------------------------------------------------

    def _fetch_congressional_trades(
        self, ticker: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self._use_mock:
            return self._mock_congressional_trades(ticker)
        return self._live_congressional_trades(ticker)

    def _live_congressional_trades(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/historical/congresstrading/{ticker}")
        trades = []
        for item in data if isinstance(data, list) else []:
            trades.append({
                "politician": item.get("Representative", ""),
                "party": item.get("Party", ""),
                "action": item.get("Transaction", ""),
                "ticker": ticker,
                "amount_range": item.get("Range", ""),
                "filing_date": item.get("ReportDate", ""),
            })
        return {
            "ticker": ticker,
            "trades": trades[:20],
            "total": len(trades),
            "source": "quiver",
        }

    @staticmethod
    def _mock_congressional_trades(ticker: str) -> dict[str, Any]:
        today = datetime.now()
        trades = [
            {
                "politician": "Nancy Pelosi",
                "party": "Democrat",
                "action": "purchase",
                "ticker": ticker,
                "amount_range": "$1,000,001 - $5,000,000",
                "filing_date": (today - timedelta(days=12)).strftime("%Y-%m-%d"),
            },
            {
                "politician": "Dan Crenshaw",
                "party": "Republican",
                "action": "sale_full",
                "ticker": ticker,
                "amount_range": "$15,001 - $50,000",
                "filing_date": (today - timedelta(days=18)).strftime("%Y-%m-%d"),
            },
            {
                "politician": "Tommy Tuberville",
                "party": "Republican",
                "action": "purchase",
                "ticker": ticker,
                "amount_range": "$50,001 - $100,000",
                "filing_date": (today - timedelta(days=25)).strftime("%Y-%m-%d"),
            },
            {
                "politician": "Ro Khanna",
                "party": "Democrat",
                "action": "sale_partial",
                "ticker": ticker,
                "amount_range": "$100,001 - $250,000",
                "filing_date": (today - timedelta(days=33)).strftime("%Y-%m-%d"),
            },
            {
                "politician": "Mark Green",
                "party": "Republican",
                "action": "purchase",
                "ticker": ticker,
                "amount_range": "$15,001 - $50,000",
                "filing_date": (today - timedelta(days=40)).strftime("%Y-%m-%d"),
            },
        ]
        return {
            "ticker": ticker,
            "trades": trades,
            "total": len(trades),
            "source": "quiver_mock",
        }

    # -- reddit sentiment -------------------------------------------------------

    def _fetch_reddit_sentiment(
        self, ticker: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self._use_mock:
            return self._mock_reddit_sentiment(ticker)
        return self._live_reddit_sentiment(ticker)

    def _live_reddit_sentiment(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/historical/wallstreetbets/{ticker}")
        latest = data[0] if isinstance(data, list) and data else {}
        return {
            "ticker": ticker,
            "mentions_24h": latest.get("Mentions", 0),
            "mentions_7d": latest.get("Mentions7d", 0),
            "rank": latest.get("Rank", 0),
            "sentiment_score": latest.get("Sentiment", 0.0),
            "date": latest.get("Date", ""),
            "source": "quiver",
        }

    @staticmethod
    def _mock_reddit_sentiment(ticker: str) -> dict[str, Any]:
        random.seed(hash(ticker) % 2**32)
        mentions_24h = random.randint(40, 850)
        return {
            "ticker": ticker,
            "mentions_24h": mentions_24h,
            "mentions_7d": mentions_24h * random.randint(4, 8),
            "rank": random.randint(1, 50),
            "sentiment_score": round(random.uniform(-0.6, 0.8), 3),
            "subreddit_breakdown": {
                "wallstreetbets": random.randint(20, 500),
                "stocks": random.randint(10, 200),
                "investing": random.randint(5, 120),
            },
            "source": "quiver_mock",
        }

    # -- lobbying ---------------------------------------------------------------

    def _fetch_lobbying(
        self, ticker: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self._use_mock:
            return self._mock_lobbying(ticker)
        return self._live_lobbying(ticker)

    def _live_lobbying(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/historical/lobbying/{ticker}")
        entries = []
        for item in data if isinstance(data, list) else []:
            entries.append({
                "company": item.get("Client", ""),
                "issue": item.get("Issue", ""),
                "amount": item.get("Amount", 0),
                "year": item.get("Year", 0),
            })
        return {
            "ticker": ticker,
            "lobbying": entries[:20],
            "total": len(entries),
            "source": "quiver",
        }

    @staticmethod
    def _mock_lobbying(ticker: str) -> dict[str, Any]:
        entries = [
            {
                "company": ticker,
                "issue": "Taxation/Internal Revenue Code",
                "amount": 3_420_000,
                "year": 2025,
            },
            {
                "company": ticker,
                "issue": "Trade (Domestic & Foreign)",
                "amount": 1_870_000,
                "year": 2025,
            },
            {
                "company": ticker,
                "issue": "Science/Technology",
                "amount": 2_150_000,
                "year": 2024,
            },
        ]
        return {
            "ticker": ticker,
            "lobbying": entries,
            "total": len(entries),
            "source": "quiver_mock",
        }

    # -- HTTP helper ------------------------------------------------------------

    def _get(self, endpoint: str) -> Any:
        url = f"{_BASE_URL}{endpoint}"
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                raise ConnectorError("Quiver API rate limit hit") from exc
            raise ConnectorError(f"Quiver API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"Quiver connection error: {exc}") from exc
