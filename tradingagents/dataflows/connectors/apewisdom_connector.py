"""ApeWisdom data source connector for Reddit/social sentiment data.

ApeWisdom tracks trending stock mentions across Reddit and other social
platforms. Free API, no authentication required.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://apewisdom.io/api/v1.0/filter/all-stocks"


class ApeWisdomConnector(BaseConnector):
    """Connector for ApeWisdom social sentiment API.

    Free tier: no authentication, no documented rate limit.
    """

    def __init__(self) -> None:
        super().__init__(rate_limit=30, rate_period=60.0)
        self._session = requests.Session()

    @property
    def name(self) -> str:
        return "apewisdom"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.DIVERGENCE, ConnectorCategory.SENTIMENT]

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "mentions")
        if data_type == "trending":
            return self._fetch_trending(params)
        elif data_type == "mentions":
            return self._fetch_ticker_mentions(ticker, params)
        else:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: ['mentions', 'trending']"
            )

    def _fetch_trending(self, params: dict) -> dict[str, Any]:
        """Fetch top trending stocks across Reddit."""
        page = params.get("page", 1)
        url = f"{_BASE_URL}/"
        try:
            resp = self._session.get(url, params={"page": page}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"ApeWisdom API error: {exc}") from exc

        results = data.get("results", [])
        return {
            "trending": [
                {
                    "ticker": item.get("ticker", ""),
                    "name": item.get("name", ""),
                    "rank": item.get("rank", 0),
                    "mentions": item.get("mentions", 0),
                    "upvotes": item.get("upvotes", 0),
                    "rank_24h_ago": item.get("rank_24h_ago"),
                    "mentions_24h_ago": item.get("mentions_24h_ago"),
                }
                for item in results
            ],
            "total": len(results),
            "source": "apewisdom",
        }

    def _fetch_ticker_mentions(self, ticker: str, params: dict) -> dict[str, Any]:
        """Fetch mention data for a specific ticker."""
        url = f"{_BASE_URL}/ticker/{ticker}"
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"ApeWisdom API error: {exc}") from exc

        results = data.get("results", [])
        if not results:
            return {
                "ticker": ticker,
                "rank": None,
                "mentions": 0,
                "upvotes": 0,
                "rank_24h_ago": None,
                "mentions_24h_ago": 0,
                "source": "apewisdom",
            }

        item = results[0]
        return {
            "ticker": ticker,
            "name": item.get("name", ""),
            "rank": item.get("rank", 0),
            "mentions": item.get("mentions", 0),
            "upvotes": item.get("upvotes", 0),
            "rank_24h_ago": item.get("rank_24h_ago"),
            "mentions_24h_ago": item.get("mentions_24h_ago"),
            "source": "apewisdom",
        }
