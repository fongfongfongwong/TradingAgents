"""Polygon.io data source connector.

Polygon provides OHLCV market data, options chains, and real-time quotes
with a tiered API. Requires POLYGON_API_KEY environment variable.

Falls back to realistic mock data when no API key is configured.
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

_BASE_URL = "https://api.polygon.io"

# Approximate base prices for common tickers (used in mock generation)
_TICKER_BASE_PRICES: dict[str, float] = {
    "AAPL": 250.0,
    "MSFT": 420.0,
    "GOOGL": 175.0,
    "AMZN": 190.0,
    "TSLA": 180.0,
    "NVDA": 900.0,
    "META": 500.0,
    "SPY": 520.0,
}

_DEFAULT_BASE_PRICE = 150.0


class PolygonConnector(BaseConnector):
    """Connector for Polygon.io financial data API.

    Supports OHLCV bars, options chains, and real-time quotes.
    Falls back to realistic mock data when POLYGON_API_KEY is not set.
    """

    TIER = 2
    CATEGORIES = ["MARKET_DATA", "OPTIONS"]

    def __init__(self, api_key: str | None = None):
        super().__init__(rate_limit=5, rate_period=60.0)
        self._api_key = api_key or os.environ.get("POLYGON_API_KEY", "")
        self._session = requests.Session()

    @property
    def name(self) -> str:
        return "polygon"

    @property
    def tier(self) -> int:
        return 2

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [
            ConnectorCategory.MARKET_DATA,
            ConnectorCategory.OPTIONS,
        ]

    def connect(self) -> None:
        if self._api_key:
            self._session.params = {"apiKey": self._api_key}  # type: ignore[assignment]
        else:
            logger.warning(
                "POLYGON_API_KEY not set — connector will serve mock data. "
                "Get a key at https://polygon.io/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "ohlcv"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "quote")
        dispatch = {
            "ohlcv": self._fetch_ohlcv,
            "options_chain": self._fetch_options_chain,
            "quote": self._fetch_quote,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- data methods ---------------------------------------------------------

    def _fetch_ohlcv(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        bars = params.get("bars", 30)
        timespan = params.get("timespan", "day")
        if not self._api_key:
            return self._mock_ohlcv(ticker, bars)

        end = datetime.now()
        start = end - timedelta(days=bars + 10)
        resp = self._get(
            f"/v2/aggs/ticker/{ticker}/range/1/{timespan}"
            f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}",
            {"adjusted": "true", "sort": "asc", "limit": bars},
        )
        results = resp.get("results", [])
        ohlcv_bars = [
            {
                "timestamp": r.get("t"),
                "open": r.get("o"),
                "high": r.get("h"),
                "low": r.get("l"),
                "close": r.get("c"),
                "volume": r.get("v"),
                "vwap": r.get("vw"),
                "transactions": r.get("n"),
            }
            for r in results
        ]
        return {
            "ticker": ticker,
            "bars": ohlcv_bars,
            "count": len(ohlcv_bars),
            "source": "polygon",
        }

    def _fetch_options_chain(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        expiration = params.get("expiration")
        if not self._api_key:
            return self._mock_options_chain(ticker)

        query: dict[str, Any] = {"underlying_ticker": ticker, "limit": 50}
        if expiration:
            query["expiration_date"] = expiration
        resp = self._get("/v3/reference/options/contracts", query)
        contracts = []
        for c in resp.get("results", []):
            contracts.append({
                "ticker": c.get("ticker", ""),
                "strike_price": c.get("strike_price"),
                "expiration_date": c.get("expiration_date"),
                "contract_type": c.get("contract_type"),
                "exercise_style": c.get("exercise_style"),
                "shares_per_contract": c.get("shares_per_contract", 100),
            })
        return {
            "ticker": ticker,
            "contracts": contracts,
            "count": len(contracts),
            "source": "polygon",
        }

    def _fetch_quote(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            return self._mock_quote(ticker)

        resp = self._get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}", {})
        snap = resp.get("ticker", {})
        day = snap.get("day", {})
        prev = snap.get("prevDay", {})
        return {
            "ticker": ticker,
            "last_price": day.get("c"),
            "open": day.get("o"),
            "high": day.get("h"),
            "low": day.get("l"),
            "volume": day.get("v"),
            "vwap": day.get("vw"),
            "prev_close": prev.get("c"),
            "change": round((day.get("c", 0) or 0) - (prev.get("c", 0) or 0), 2),
            "change_percent": snap.get("todaysChangePerc"),
            "timestamp": snap.get("updated"),
            "source": "polygon",
        }

    # -- mock data generators --------------------------------------------------

    def _base_price(self, ticker: str) -> float:
        return _TICKER_BASE_PRICES.get(ticker.upper(), _DEFAULT_BASE_PRICE)

    def _mock_ohlcv(self, ticker: str, bars: int = 30) -> dict[str, Any]:
        """Generate realistic OHLCV bars with a slight upward trend."""
        base = self._base_price(ticker)
        price = base * random.uniform(0.95, 1.05)
        now = datetime.now()
        ohlcv_bars = []
        for i in range(bars):
            dt = now - timedelta(days=bars - i)
            drift = random.gauss(0.001, 0.015)
            price = price * (1 + drift)
            high = price * random.uniform(1.005, 1.025)
            low = price * random.uniform(0.975, 0.995)
            open_p = random.uniform(low, high)
            close_p = random.uniform(low, high)
            volume = int(random.gauss(45_000_000, 12_000_000))
            volume = max(volume, 5_000_000)
            ohlcv_bars.append({
                "timestamp": int(dt.timestamp() * 1000),
                "open": round(open_p, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close_p, 2),
                "volume": volume,
                "vwap": round((high + low + close_p) / 3, 2),
                "transactions": random.randint(300_000, 900_000),
            })
        return {
            "ticker": ticker,
            "bars": ohlcv_bars,
            "count": len(ohlcv_bars),
            "source": "polygon_mock",
        }

    def _mock_options_chain(self, ticker: str) -> dict[str, Any]:
        """Generate a realistic options chain with 10 strikes."""
        base = self._base_price(ticker)
        now = datetime.now()
        expiry = now + timedelta(days=30)
        expiry_str = expiry.strftime("%Y-%m-%d")
        strikes = [round(base + (i - 5) * base * 0.02, 2) for i in range(10)]
        contracts = []
        for strike in strikes:
            for ctype in ("call", "put"):
                moneyness = (base - strike) / base
                if ctype == "call":
                    intrinsic = max(base - strike, 0)
                else:
                    intrinsic = max(strike - base, 0)
                time_value = base * 0.02 * random.uniform(0.5, 1.5)
                mid = intrinsic + time_value
                spread = mid * random.uniform(0.02, 0.08)
                bid = round(max(mid - spread / 2, 0.01), 2)
                ask = round(mid + spread / 2, 2)
                vol = random.randint(50, 5000) if abs(moneyness) < 0.06 else random.randint(5, 200)
                oi = vol * random.randint(3, 20)
                contracts.append({
                    "strike": strike,
                    "expiration": expiry_str,
                    "type": ctype,
                    "bid": bid,
                    "ask": ask,
                    "mid": round((bid + ask) / 2, 2),
                    "volume": vol,
                    "open_interest": oi,
                    "implied_volatility": round(random.uniform(0.20, 0.55), 4),
                    "delta": round(
                        random.uniform(0.3, 0.8) if ctype == "call" else random.uniform(-0.8, -0.3),
                        4,
                    ),
                })
        return {
            "ticker": ticker,
            "contracts": contracts,
            "count": len(contracts),
            "expiration": expiry_str,
            "source": "polygon_mock",
        }

    def _mock_quote(self, ticker: str) -> dict[str, Any]:
        """Generate a realistic intraday quote snapshot."""
        base = self._base_price(ticker)
        change_pct = random.gauss(0, 1.2)
        last = round(base * (1 + change_pct / 100), 2)
        prev_close = round(base, 2)
        change = round(last - prev_close, 2)
        high = round(max(last, prev_close) * random.uniform(1.002, 1.012), 2)
        low = round(min(last, prev_close) * random.uniform(0.988, 0.998), 2)
        volume = int(random.gauss(50_000_000, 15_000_000))
        volume = max(volume, 3_000_000)
        return {
            "ticker": ticker,
            "last_price": last,
            "open": round(prev_close * random.uniform(0.998, 1.002), 2),
            "high": high,
            "low": low,
            "volume": volume,
            "vwap": round((high + low + last) / 3, 2),
            "prev_close": prev_close,
            "change": change,
            "change_percent": round(change_pct, 4),
            "timestamp": int(datetime.now().timestamp() * 1000),
            "source": "polygon_mock",
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
                raise ConnectorError("Polygon API rate limit hit") from exc
            raise ConnectorError(f"Polygon API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"Polygon connection error: {exc}") from exc
