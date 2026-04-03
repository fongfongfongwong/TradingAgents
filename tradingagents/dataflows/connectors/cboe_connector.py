"""CBOE data source connector for VIX and put/call ratio data.

CBOE provides free access to VIX historical data and options market statistics.
No authentication required.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
_PC_RATIO_URL = "https://www.cboe.com/us/options/market_statistics/daily/"


class CBOEConnector(BaseConnector):
    """Connector for CBOE VIX and put/call ratio data.

    Free tier: no authentication required, public CSV endpoints.
    """

    def __init__(self) -> None:
        super().__init__(rate_limit=30, rate_period=60.0)
        self._session = requests.Session()

    @property
    def name(self) -> str:
        return "cboe"

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
        data_type = params.get("data_type", "vix")
        dispatch = {
            "vix": self._fetch_vix,
            "put_call_ratio": self._fetch_put_call_ratio,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    def _fetch_vix(self, ticker: str, params: dict) -> dict[str, Any]:
        """Fetch latest VIX data from CBOE historical CSV."""
        try:
            resp = self._session.get(_VIX_URL, timeout=15)
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"CBOE VIX fetch error: {exc}") from exc

        try:
            reader = csv.DictReader(io.StringIO(resp.text))
            rows = list(reader)
            if not rows:
                raise ConnectorError("CBOE VIX CSV returned no data")
            latest = rows[-1]
            return {
                "ticker": "VIX",
                "date": latest.get("DATE", ""),
                "open": _safe_float(latest.get("OPEN")),
                "high": _safe_float(latest.get("HIGH")),
                "low": _safe_float(latest.get("LOW")),
                "close": _safe_float(latest.get("CLOSE")),
                "source": "cboe",
            }
        except (KeyError, ValueError) as exc:
            raise ConnectorError(f"CBOE VIX parse error: {exc}") from exc

    def _fetch_put_call_ratio(self, ticker: str, params: dict) -> dict[str, Any]:
        """Fetch put/call ratio data from CBOE market statistics."""
        try:
            resp = self._session.get(_PC_RATIO_URL, timeout=15)
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"CBOE put/call ratio fetch error: {exc}") from exc

        # CBOE market statistics page may return HTML or CSV depending on params.
        # Parse what we can; return structured result.
        try:
            # Attempt CSV parse first
            reader = csv.DictReader(io.StringIO(resp.text))
            rows = list(reader)
            if rows:
                latest = rows[-1]
                return {
                    "date": latest.get("TRADE_DATE", latest.get("DATE", "")),
                    "equity_pc_ratio": _safe_float(latest.get("EQUITY_PC_RATIO")),
                    "index_pc_ratio": _safe_float(latest.get("INDEX_PC_RATIO")),
                    "total_pc_ratio": _safe_float(latest.get("TOTAL_PC_RATIO")),
                    "source": "cboe",
                }
        except Exception:
            pass

        # Fallback: return structure with None values indicating data unavailable
        return {
            "date": None,
            "equity_pc_ratio": None,
            "index_pc_ratio": None,
            "total_pc_ratio": None,
            "source": "cboe",
            "note": "Put/call ratio data could not be parsed from CBOE response",
        }


def _safe_float(val: Any) -> float | None:
    """Convert value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
