"""FRED (Federal Reserve Economic Data) connector.

Provides access to macroeconomic time series from the St. Louis Fed FRED API.
Key series: GDP, UNRATE, CPIAUCSL, FEDFUNDS, T10Y2Y, T10YIE, VIXCLS, DGS10, DGS2.

Requires FRED_API_KEY environment variable.
Free tier: 120 requests/minute.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred"

# Well-known FRED series for quick reference
KEY_SERIES = {
    "GDP": "Gross Domestic Product",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "FEDFUNDS": "Federal Funds Effective Rate",
    "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury (yield curve)",
    "T10YIE": "10-Year Breakeven Inflation Rate",
    "VIXCLS": "CBOE Volatility Index (VIX)",
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "DGS2": "2-Year Treasury Constant Maturity Rate",
}


class FREDConnector(BaseConnector):
    """Connector for the FRED (Federal Reserve Economic Data) API.

    Free tier: 120 API calls/minute.
    Uses ``requests`` directly -- no ``fredapi`` dependency.
    """

    def __init__(self, api_key: str | None = None):
        super().__init__(rate_limit=120, rate_period=60.0)
        self._api_key = api_key or os.environ.get("FRED_API_KEY", "")
        self._session = requests.Session()

    # -- abstract properties ---------------------------------------------------

    @property
    def name(self) -> str:
        return "fred"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.MACRO]

    # -- lifecycle -------------------------------------------------------------

    def connect(self) -> None:
        if not self._api_key:
            raise ConnectorError(
                "FRED_API_KEY not set. Get a free key at https://fred.stlouisfed.org/docs/api/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    # -- dispatch --------------------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "series")
        dispatch = {
            "series": self._fetch_series,
            "search": self._fetch_search,
            "releases": self._fetch_releases,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- data methods ----------------------------------------------------------

    def _fetch_series(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch observations for a FRED series.

        ``ticker`` is the series_id (e.g. "GDP", "UNRATE", "FEDFUNDS").
        Optional params: observation_start, observation_end, sort_order, limit.
        """
        query: dict[str, Any] = {"series_id": ticker}
        for key in ("observation_start", "observation_end", "sort_order", "limit"):
            if key in params:
                query[key] = params[key]

        resp = self._get("/series/observations", query)

        observations = []
        for obs in resp.get("observations", []):
            observations.append({
                "date": obs.get("date"),
                "value": obs.get("value"),
            })

        return {
            "series_id": ticker,
            "observations": observations,
            "count": resp.get("count", len(observations)),
            "units": resp.get("units", ""),
            "frequency": resp.get("frequency", ""),
            "source": "fred",
        }

    def _fetch_search(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Search for FRED series.

        ``ticker`` is used as the search query text.
        Optional params: limit, order_by, sort_order.
        """
        query: dict[str, Any] = {"search_text": ticker}
        for key in ("limit", "order_by", "sort_order"):
            if key in params:
                query[key] = params[key]

        resp = self._get("/series/search", query)

        series_list = []
        for s in resp.get("seriess", []):
            series_list.append({
                "id": s.get("id"),
                "title": s.get("title"),
                "frequency": s.get("frequency"),
                "units": s.get("units"),
                "observation_start": s.get("observation_start"),
                "observation_end": s.get("observation_end"),
                "popularity": s.get("popularity"),
            })

        return {
            "query": ticker,
            "results": series_list,
            "total": resp.get("count", len(series_list)),
            "source": "fred",
        }

    def _fetch_releases(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch recent FRED data releases.

        ``ticker`` is ignored for a general releases listing.
        Optional params: limit, offset.
        """
        query: dict[str, Any] = {}
        for key in ("limit", "offset"):
            if key in params:
                query[key] = params[key]

        resp = self._get("/releases", query)

        releases = []
        for r in resp.get("releases", []):
            releases.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "press_release": r.get("press_release"),
                "link": r.get("link"),
            })

        return {
            "releases": releases,
            "total": len(releases),
            "source": "fred",
        }

    # -- HTTP helper -----------------------------------------------------------

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        """Execute GET request with error handling."""
        url = f"{_BASE_URL}{endpoint}"
        params["api_key"] = self._api_key
        params["file_type"] = "json"
        try:
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                raise ConnectorError("FRED API rate limit hit") from exc
            raise ConnectorError(f"FRED API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"FRED connection error: {exc}") from exc
