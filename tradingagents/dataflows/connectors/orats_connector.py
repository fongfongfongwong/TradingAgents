"""ORATS data source connector.

ORATS (Options Research & Technology Services) provides implied volatility
analytics, IV surfaces, and IV forecasts. Requires ORATS_API_KEY environment
variable.

Falls back to realistic mock data when no API key is configured.
"""

from __future__ import annotations

import logging
import math
import os
import random
from datetime import datetime, timedelta
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.orats.io/datav2"


class ORATSConnector(BaseConnector):
    """Connector for ORATS implied volatility analytics.

    Supports IV rank, IV surface, and IV forecasts.
    Falls back to realistic mock data when ORATS_API_KEY is not set.
    """

    TIER = 2
    CATEGORIES = ["OPTIONS"]

    def __init__(self, api_key: str | None = None):
        super().__init__(rate_limit=30, rate_period=60.0)
        self._api_key = api_key or os.environ.get("ORATS_API_KEY", "")
        self._session = requests.Session()

    @property
    def name(self) -> str:
        return "orats"

    @property
    def tier(self) -> int:
        return 2

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.OPTIONS]

    def connect(self) -> None:
        if self._api_key:
            self._session.params = {"token": self._api_key}  # type: ignore[assignment]
        else:
            logger.warning(
                "ORATS_API_KEY not set — connector will serve mock data. "
                "Get a key at https://orats.com/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "iv_rank"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "iv_rank")
        dispatch = {
            "iv_rank": self._fetch_iv_rank,
            "iv_surface": self._fetch_iv_surface,
            "iv_forecast": self._fetch_iv_forecast,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- data methods ---------------------------------------------------------

    def _fetch_iv_rank(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            return self._mock_iv_rank(ticker)

        resp = self._get("/hist/summaries", {"ticker": ticker})
        data_list = resp.get("data", [])
        if not data_list:
            raise ConnectorError(f"No IV data returned for {ticker}")
        latest = data_list[-1]
        return {
            "ticker": ticker,
            "current_iv": latest.get("currentIv"),
            "iv_52w_high": latest.get("ivHigh"),
            "iv_52w_low": latest.get("ivLow"),
            "iv_rank": latest.get("ivRank"),
            "iv_percentile": latest.get("ivPct"),
            "hv_20d": latest.get("hv20d"),
            "hv_60d": latest.get("hv60d"),
            "iv_hv_spread": latest.get("ivHvSpread"),
            "date": latest.get("tradeDate"),
            "source": "orats",
        }

    def _fetch_iv_surface(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            return self._mock_iv_surface(ticker)

        resp = self._get("/strikes/ivs", {"ticker": ticker})
        data_list = resp.get("data", [])
        surface: list[dict[str, Any]] = []
        for row in data_list[:50]:
            surface.append({
                "expiration": row.get("expirDate"),
                "dte": row.get("dte"),
                "strike": row.get("strike"),
                "delta": row.get("delta"),
                "call_iv": row.get("callIv"),
                "put_iv": row.get("putIv"),
                "call_bid_iv": row.get("callBidIv"),
                "call_ask_iv": row.get("callAskIv"),
                "put_bid_iv": row.get("putBidIv"),
                "put_ask_iv": row.get("putAskIv"),
            })
        return {
            "ticker": ticker,
            "surface": surface,
            "count": len(surface),
            "source": "orats",
        }

    def _fetch_iv_forecast(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            return self._mock_iv_forecast(ticker)

        resp = self._get("/hist/summaries", {"ticker": ticker})
        data_list = resp.get("data", [])
        if not data_list:
            raise ConnectorError(f"No IV forecast data returned for {ticker}")
        latest = data_list[-1]
        return {
            "ticker": ticker,
            "forecast_7d": latest.get("forecastIv7d"),
            "forecast_30d": latest.get("forecastIv30d"),
            "forecast_90d": latest.get("forecastIv90d"),
            "current_iv": latest.get("currentIv"),
            "date": latest.get("tradeDate"),
            "source": "orats",
        }

    # -- mock data generators --------------------------------------------------

    def _mock_iv_rank(self, ticker: str) -> dict[str, Any]:
        """Generate realistic IV rank data for a ticker."""
        base_iv = _base_iv(ticker)
        iv_52w_high = round(base_iv * random.uniform(1.4, 2.2), 4)
        iv_52w_low = round(base_iv * random.uniform(0.4, 0.7), 4)
        current_iv = round(random.uniform(iv_52w_low, iv_52w_high), 4)
        iv_range = iv_52w_high - iv_52w_low
        iv_rank = round((current_iv - iv_52w_low) / iv_range * 100, 1) if iv_range > 0 else 50.0
        hv_20d = round(current_iv * random.uniform(0.7, 1.1), 4)
        hv_60d = round(current_iv * random.uniform(0.75, 1.05), 4)
        return {
            "ticker": ticker,
            "current_iv": current_iv,
            "iv_52w_high": iv_52w_high,
            "iv_52w_low": iv_52w_low,
            "iv_rank": iv_rank,
            "iv_percentile": round(min(max(iv_rank + random.gauss(0, 5), 0), 100), 1),
            "hv_20d": hv_20d,
            "hv_60d": hv_60d,
            "iv_hv_spread": round(current_iv - hv_20d, 4),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "orats_mock",
        }

    def _mock_iv_surface(self, ticker: str) -> dict[str, Any]:
        """Generate a 5x5 IV surface (5 expirations x 5 deltas)."""
        base_iv = _base_iv(ticker)
        now = datetime.now()
        expirations_days = [7, 30, 60, 90, 180]
        deltas = [0.10, 0.25, 0.50, 0.75, 0.90]
        surface: list[dict[str, Any]] = []
        for dte in expirations_days:
            expiry_date = (now + timedelta(days=dte)).strftime("%Y-%m-%d")
            term_factor = math.sqrt(dte / 30.0)
            for delta in deltas:
                # IV smile: higher IV for OTM options (low/high delta)
                moneyness_factor = 1.0 + 0.15 * (abs(delta - 0.50) / 0.40) ** 2
                # Term structure: slight contango
                term_adj = 1.0 + 0.05 * (term_factor - 1.0)
                iv = round(
                    base_iv * moneyness_factor * term_adj * random.uniform(0.95, 1.05),
                    4,
                )
                spread = round(iv * random.uniform(0.01, 0.04), 4)
                surface.append({
                    "expiration": expiry_date,
                    "dte": dte,
                    "delta": delta,
                    "call_iv": iv,
                    "put_iv": round(iv * random.uniform(0.98, 1.04), 4),
                    "call_bid_iv": round(iv - spread, 4),
                    "call_ask_iv": round(iv + spread, 4),
                    "put_bid_iv": round(iv * random.uniform(0.98, 1.04) - spread, 4),
                    "put_ask_iv": round(iv * random.uniform(0.98, 1.04) + spread, 4),
                })
        return {
            "ticker": ticker,
            "surface": surface,
            "count": len(surface),
            "expirations": expirations_days,
            "deltas": deltas,
            "source": "orats_mock",
        }

    def _mock_iv_forecast(self, ticker: str) -> dict[str, Any]:
        """Generate realistic IV forecasts for 7/30/90 day horizons."""
        base_iv = _base_iv(ticker)
        current_iv = round(base_iv * random.uniform(0.85, 1.15), 4)
        # Short-term forecast: mean-reverting towards base
        forecast_7d = round(
            current_iv * 0.85 + base_iv * 0.15 + random.gauss(0, base_iv * 0.02),
            4,
        )
        forecast_30d = round(
            current_iv * 0.60 + base_iv * 0.40 + random.gauss(0, base_iv * 0.03),
            4,
        )
        forecast_90d = round(
            current_iv * 0.30 + base_iv * 0.70 + random.gauss(0, base_iv * 0.04),
            4,
        )
        return {
            "ticker": ticker,
            "current_iv": current_iv,
            "forecast_7d": forecast_7d,
            "forecast_30d": forecast_30d,
            "forecast_90d": forecast_90d,
            "forecast_7d_change": round(forecast_7d - current_iv, 4),
            "forecast_30d_change": round(forecast_30d - current_iv, 4),
            "forecast_90d_change": round(forecast_90d - current_iv, 4),
            "mean_reversion_target": round(base_iv, 4),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "orats_mock",
        }

    # -- HTTP helper ----------------------------------------------------------

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        """Execute GET request with error handling."""
        url = f"{_BASE_URL}{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                raise ConnectorError("ORATS API rate limit hit") from exc
            raise ConnectorError(f"ORATS API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"ORATS connection error: {exc}") from exc


def _base_iv(ticker: str) -> float:
    """Return a realistic baseline implied volatility for a ticker."""
    ivs: dict[str, float] = {
        "AAPL": 0.25,
        "MSFT": 0.22,
        "GOOGL": 0.28,
        "AMZN": 0.30,
        "TSLA": 0.55,
        "NVDA": 0.45,
        "META": 0.35,
        "SPY": 0.15,
        "QQQ": 0.18,
        "IWM": 0.20,
    }
    return ivs.get(ticker.upper(), 0.30)
