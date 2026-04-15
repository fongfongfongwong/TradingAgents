"""CNN Fear & Greed Index connector.

Provides the CNN Fear & Greed Index which measures market sentiment on a
0-100 scale. No authentication required.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


def _classify_score(value: float) -> str:
    """Map a 0-100 Fear & Greed score to a human-readable rating."""
    if value <= 25:
        return "Extreme Fear"
    elif value <= 45:
        return "Fear"
    elif value <= 55:
        return "Neutral"
    elif value <= 75:
        return "Greed"
    else:
        return "Extreme Greed"


class FearGreedConnector(BaseConnector):
    """Connector for CNN Fear & Greed Index.

    Free tier: no authentication required, public JSON endpoint.
    """

    def __init__(self) -> None:
        super().__init__(rate_limit=30, rate_period=60.0)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; TradingAgents/1.0)",
        })

    @property
    def name(self) -> str:
        return "fear_greed"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.DIVERGENCE, ConnectorCategory.SENTIMENT]

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "current"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "current")
        if data_type != "current":
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. Supported: ['current']"
            )
        return self._fetch_current()

    def _fetch_current(self) -> dict[str, Any]:
        """Fetch current Fear & Greed Index value."""
        try:
            resp = self._session.get(_FG_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"CNN Fear & Greed API error: {exc}") from exc

        try:
            fg_data = data.get("fear_and_greed", {})
            score = fg_data.get("score")
            timestamp = fg_data.get("timestamp")

            if score is None:
                raise ConnectorError("Fear & Greed score not found in response")

            score_val = float(score)
            return {
                "value": score_val,
                "rating": _classify_score(score_val),
                "timestamp": timestamp,
                "previous_close": fg_data.get("previous_close"),
                "previous_1_week": fg_data.get("previous_1_week"),
                "previous_1_month": fg_data.get("previous_1_month"),
                "previous_1_year": fg_data.get("previous_1_year"),
                "source": "cnn_fear_greed",
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError(
                f"Failed to parse Fear & Greed response: {exc}"
            ) from exc
