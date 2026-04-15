"""Alpaca News data source connector.

Provides real-time and historical news articles via the Alpaca free news
feed. Requires ALPACA_API_KEY_ID and ALPACA_API_SECRET environment variables
for live access; falls back to realistic mock data when unavailable.
"""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.alpaca.markets/v1beta1"


class AlpacaNewsConnector(BaseConnector):
    """Connector for Alpaca Markets free news feed.

    Tier 1 (free): real-time and historical market news with generous
    rate limits. Falls back to realistic mock articles when API
    credentials are absent.
    """

    TIER = 1
    CATEGORIES = ["NEWS"]

    _DATA_TYPES = ("news",)

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        super().__init__(rate_limit=200, rate_period=60.0)
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY_ID", "")
        self._api_secret = api_secret or os.environ.get("ALPACA_API_SECRET", "")
        self._session = requests.Session()
        self._use_mock = not (self._api_key and self._api_secret)

    @property
    def name(self) -> str:
        return "alpaca_news"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.NEWS]

    def connect(self) -> None:
        if self._api_key and self._api_secret:
            self._session.headers.update({
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._api_secret,
            })
        else:
            logger.warning(
                "ALPACA_API_KEY_ID / ALPACA_API_SECRET not set — using mock data. "
                "Get free keys at https://alpaca.markets/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "news"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "news")
        if data_type != "news":
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. Supported: ['news']"
            )
        return self._fetch_news(ticker, params)

    # -- news -------------------------------------------------------------------

    def _fetch_news(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._use_mock:
            return self._mock_news(ticker)
        return self._live_news(ticker, params)

    def _live_news(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 20)
        query_params: dict[str, Any] = {
            "symbols": ticker,
            "limit": min(limit, 50),
            "sort": "desc",
        }
        start = params.get("start")
        if start:
            query_params["start"] = start
        end = params.get("end")
        if end:
            query_params["end"] = end

        data = self._get("/news", query_params)
        articles = []
        for item in data.get("news", []) if isinstance(data, dict) else []:
            articles.append({
                "title": item.get("headline", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "published_at": item.get("created_at", ""),
                "summary": item.get("summary", ""),
                "symbols": item.get("symbols", []),
            })
        return {
            "ticker": ticker,
            "articles": articles,
            "total": len(articles),
            "source": "alpaca_news",
        }

    @staticmethod
    def _mock_news(ticker: str) -> dict[str, Any]:
        now = datetime.now(tz=timezone.utc)

        _MOCK_ARTICLES = [
            {
                "title": f"{ticker} Reports Record Q1 Revenue Beating Analyst Estimates",
                "source": "Reuters",
                "url": f"https://reuters.com/technology/{ticker.lower()}-q1-earnings",
                "summary": (
                    f"{ticker} posted quarterly revenue above Wall Street expectations, "
                    "driven by strong demand in its services segment."
                ),
                "symbols": [ticker],
            },
            {
                "title": "Fed Signals Rate Hold Through Mid-2026 Amid Cooling Inflation",
                "source": "Bloomberg",
                "url": "https://bloomberg.com/news/fed-rate-hold-2026",
                "summary": (
                    "Federal Reserve officials indicated they expect to keep rates "
                    "steady as inflation data continues its downward trend."
                ),
                "symbols": [ticker, "SPY"],
            },
            {
                "title": f"Analysts Upgrade {ticker} on Strong AI Growth Outlook",
                "source": "CNBC",
                "url": f"https://cnbc.com/2026/03/{ticker.lower()}-upgrade",
                "summary": (
                    f"Multiple Wall Street firms raised price targets for {ticker}, "
                    "citing accelerating AI-related revenue growth."
                ),
                "symbols": [ticker],
            },
            {
                "title": f"{ticker} Expands Share Buyback Program by $50 Billion",
                "source": "Wall Street Journal",
                "url": f"https://wsj.com/markets/{ticker.lower()}-buyback",
                "summary": (
                    f"{ticker} announced a significant increase in its share "
                    "repurchase authorization, signalling confidence in future earnings."
                ),
                "symbols": [ticker],
            },
            {
                "title": "SEC Proposes New Climate Disclosure Rules for Public Companies",
                "source": "Financial Times",
                "url": "https://ft.com/sec-climate-disclosure-2026",
                "summary": (
                    "The SEC unveiled updated climate-risk disclosure requirements "
                    "that could affect reporting for major tech and energy firms."
                ),
                "symbols": [ticker, "XLE"],
            },
            {
                "title": f"{ticker} Partners With Leading Chipmaker on Next-Gen Hardware",
                "source": "TechCrunch",
                "url": f"https://techcrunch.com/{ticker.lower()}-chip-partnership",
                "summary": (
                    f"{ticker} announced a strategic partnership to develop custom "
                    "silicon aimed at improving AI inference performance."
                ),
                "symbols": [ticker, "NVDA"],
            },
            {
                "title": "Treasury Yields Dip as Jobs Data Comes in Below Forecast",
                "source": "MarketWatch",
                "url": "https://marketwatch.com/story/treasury-yields-jobs-2026",
                "summary": (
                    "The 10-year Treasury yield fell after the March jobs report "
                    "showed fewer-than-expected nonfarm payroll additions."
                ),
                "symbols": [ticker, "TLT"],
            },
            {
                "title": f"Hedge Funds Increase {ticker} Positions in Latest 13F Filings",
                "source": "Barron's",
                "url": f"https://barrons.com/articles/{ticker.lower()}-13f-filings",
                "summary": (
                    f"Institutional investors boosted their {ticker} holdings last "
                    "quarter, according to newly released regulatory filings."
                ),
                "symbols": [ticker],
            },
            {
                "title": f"{ticker} Faces Antitrust Scrutiny in European Markets",
                "source": "The Guardian",
                "url": f"https://theguardian.com/business/{ticker.lower()}-eu-antitrust",
                "summary": (
                    f"European regulators opened a preliminary investigation into "
                    f"{ticker}'s market practices in the digital services sector."
                ),
                "symbols": [ticker],
            },
            {
                "title": "Oil Prices Surge on Middle East Supply Concerns",
                "source": "Associated Press",
                "url": "https://apnews.com/oil-prices-middle-east-2026",
                "summary": (
                    "Crude oil climbed above $85 a barrel as geopolitical tensions "
                    "raised concerns about supply disruptions."
                ),
                "symbols": [ticker, "USO", "XLE"],
            },
        ]

        articles = []
        for idx, template in enumerate(_MOCK_ARTICLES):
            published = (now - timedelta(hours=idx * 3 + 1)).isoformat()
            articles.append({**template, "published_at": published})

        return {
            "ticker": ticker,
            "articles": articles,
            "total": len(articles),
            "source": "alpaca_news_mock",
        }

    # -- HTTP helper ------------------------------------------------------------

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        url = f"{_BASE_URL}{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                raise ConnectorError("Alpaca News API rate limit hit") from exc
            raise ConnectorError(f"Alpaca News API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"Alpaca News connection error: {exc}") from exc
