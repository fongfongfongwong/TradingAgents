"""AAII Investor Sentiment Survey connector.

AAII publishes weekly bull/bear/neutral sentiment survey data. Since there is
no public API, this connector fetches data from the publicly available
AAII sentiment page or returns cached/fallback data when scraping is not
possible.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_AAII_URL = "https://www.aaii.com/sentimentsurvey/sent_results"


class AAIIConnector(BaseConnector):
    """Connector for AAII weekly sentiment survey data.

    Tier 1 (free): scrapes public AAII sentiment page.
    Falls back to cached data if scraping fails.
    """

    def __init__(self) -> None:
        super().__init__(rate_limit=10, rate_period=60.0)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; TradingAgents/1.0)",
        })

    @property
    def name(self) -> str:
        return "aaii"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.DIVERGENCE]

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "sentiment")
        if data_type != "sentiment":
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. Supported: ['sentiment']"
            )
        return self._fetch_sentiment(params)

    def _fetch_sentiment(self, params: dict) -> dict[str, Any]:
        """Fetch AAII sentiment survey data.

        Attempts to scrape the public AAII page. If that fails, returns
        a fallback response indicating data must be manually updated.
        """
        try:
            resp = self._session.get(_AAII_URL, timeout=15)
            resp.raise_for_status()
            return self._parse_sentiment_page(resp.text)
        except requests.exceptions.RequestException as exc:
            logger.warning("AAII scrape failed, returning fallback: %s", exc)
            return self._fallback_sentiment()

    def _parse_sentiment_page(self, html: str) -> dict[str, Any]:
        """Extract sentiment percentages from AAII HTML page."""
        import re

        bullish = self._extract_pct(html, r"Bullish[:\s]*?([\d.]+)%")
        bearish = self._extract_pct(html, r"Bearish[:\s]*?([\d.]+)%")
        neutral = self._extract_pct(html, r"Neutral[:\s]*?([\d.]+)%")

        if bullish is None and bearish is None and neutral is None:
            return self._fallback_sentiment()

        bull_bear_spread = None
        if bullish is not None and bearish is not None:
            bull_bear_spread = round(bullish - bearish, 1)

        return {
            "bullish_pct": bullish,
            "bearish_pct": bearish,
            "neutral_pct": neutral,
            "bull_bear_spread": bull_bear_spread,
            "source": "aaii",
        }

    @staticmethod
    def _extract_pct(html: str, pattern: str) -> float | None:
        """Extract a percentage value from HTML using regex."""
        import re
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    @staticmethod
    def _fallback_sentiment() -> dict[str, Any]:
        """Return fallback response when live data is unavailable."""
        return {
            "bullish_pct": None,
            "bearish_pct": None,
            "neutral_pct": None,
            "bull_bear_spread": None,
            "source": "aaii",
            "note": (
                "Live AAII data unavailable. Visit https://www.aaii.com/sentimentsurvey "
                "to get the latest weekly survey results."
            ),
        }
