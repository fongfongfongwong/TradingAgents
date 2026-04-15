"""Unusual Whales data source connector.

Unusual Whales provides options flow, dark pool data, and congressional
trading activity. Requires UNUSUAL_WHALES_API_KEY environment variable.

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

_BASE_URL = "https://api.unusualwhales.com/api"

_POLITICIANS = [
    "Nancy Pelosi",
    "Dan Crenshaw",
    "Tommy Tuberville",
    "Josh Gottheimer",
    "Michael McCaul",
    "Ro Khanna",
    "Mark Green",
    "Virginia Foxx",
]

_DARK_POOL_EXCHANGES = [
    "UBSS",  # UBS ATS
    "CODA",  # Coda Markets
    "JNST",  # Jane Street
    "MSPL",  # MS Pool
    "CROS",  # CrossFinder
    "SGMT",  # Sigma-X
]


class UnusualWhalesConnector(BaseConnector):
    """Connector for Unusual Whales options flow and alternative data.

    Supports options flow, dark pool prints, and congressional trades.
    Falls back to realistic mock data when UNUSUAL_WHALES_API_KEY is not set.
    """

    TIER = 2
    CATEGORIES = ["OPTIONS", "ALTERNATIVE"]

    def __init__(self, api_key: str | None = None):
        super().__init__(rate_limit=30, rate_period=60.0)
        self._api_key = api_key or os.environ.get("UNUSUAL_WHALES_API_KEY", "")
        self._session = requests.Session()

    @property
    def name(self) -> str:
        return "unusual_whales"

    @property
    def tier(self) -> int:
        return 2

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [
            ConnectorCategory.OPTIONS,
            ConnectorCategory.ALTERNATIVE,
        ]

    def connect(self) -> None:
        if self._api_key:
            self._session.headers.update({
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
            })
        else:
            logger.warning(
                "UNUSUAL_WHALES_API_KEY not set — connector will serve mock data. "
                "Get a key at https://unusualwhales.com/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "options_flow"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "options_flow")
        dispatch = {
            "options_flow": self._fetch_options_flow,
            "dark_pool": self._fetch_dark_pool,
            "congressional": self._fetch_congressional,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- data methods ---------------------------------------------------------

    def _fetch_options_flow(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            return self._mock_options_flow(ticker)

        resp = self._get(f"/stock/{ticker}/options-flow", {})
        trades = []
        for item in resp.get("data", [])[:20]:
            trades.append({
                "ticker": ticker,
                "strike": item.get("strike_price"),
                "expiration": item.get("expires_at"),
                "type": item.get("put_call"),
                "premium": item.get("premium"),
                "volume": item.get("volume"),
                "open_interest": item.get("open_interest"),
                "side": item.get("side"),
                "timestamp": item.get("created_at"),
            })
        return {
            "ticker": ticker,
            "trades": trades,
            "total": len(trades),
            "source": "unusual_whales",
        }

    def _fetch_dark_pool(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            return self._mock_dark_pool(ticker)

        resp = self._get(f"/stock/{ticker}/dark-pool", {})
        prints = []
        for item in resp.get("data", [])[:20]:
            prints.append({
                "ticker": ticker,
                "price": item.get("price"),
                "volume": item.get("volume"),
                "notional": item.get("notional"),
                "exchange": item.get("exchange"),
                "timestamp": item.get("tracking_timestamp"),
            })
        return {
            "ticker": ticker,
            "prints": prints,
            "total": len(prints),
            "source": "unusual_whales",
        }

    def _fetch_congressional(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            return self._mock_congressional(ticker)

        resp = self._get("/congressional-trading", {"ticker": ticker})
        trades = []
        for item in resp.get("data", [])[:20]:
            trades.append({
                "politician": item.get("politician"),
                "action": item.get("transaction_type"),
                "ticker": ticker,
                "amount_range": item.get("amount"),
                "filed_date": item.get("filed_date"),
                "transaction_date": item.get("transaction_date"),
                "chamber": item.get("chamber"),
            })
        return {
            "ticker": ticker,
            "trades": trades,
            "total": len(trades),
            "source": "unusual_whales",
        }

    # -- mock data generators --------------------------------------------------

    def _mock_options_flow(self, ticker: str) -> dict[str, Any]:
        """Generate 5 realistic large block option trades."""
        now = datetime.now()
        base_price = _approximate_price(ticker)
        trades = []
        for _ in range(5):
            is_call = random.choice([True, False])
            strike_offset = random.choice([-10, -5, 0, 5, 10, 15, 20])
            strike = round(base_price + strike_offset, 0)
            days_to_exp = random.choice([7, 14, 30, 45, 60, 90])
            expiry = now + timedelta(days=days_to_exp)
            volume = random.randint(500, 8000)
            avg_premium_per = random.uniform(1.50, 25.00)
            total_premium = round(volume * avg_premium_per * 100, 2)
            trades.append({
                "ticker": ticker,
                "strike": strike,
                "expiration": expiry.strftime("%Y-%m-%d"),
                "type": "call" if is_call else "put",
                "premium": total_premium,
                "avg_price": round(avg_premium_per, 2),
                "volume": volume,
                "open_interest": random.randint(volume, volume * 15),
                "side": random.choice(["ask", "bid", "mid"]),
                "sentiment": "bullish" if is_call else "bearish",
                "timestamp": (now - timedelta(minutes=random.randint(1, 120))).isoformat(),
            })
        trades.sort(key=lambda t: t["premium"], reverse=True)
        return {
            "ticker": ticker,
            "trades": trades,
            "total": len(trades),
            "source": "unusual_whales_mock",
        }

    def _mock_dark_pool(self, ticker: str) -> dict[str, Any]:
        """Generate 3 realistic dark pool prints."""
        now = datetime.now()
        base_price = _approximate_price(ticker)
        prints = []
        for _ in range(3):
            price = round(base_price * random.uniform(0.998, 1.002), 2)
            volume = random.choice([
                random.randint(50_000, 150_000),
                random.randint(150_000, 500_000),
                random.randint(500_000, 2_000_000),
            ])
            notional = round(price * volume, 2)
            prints.append({
                "ticker": ticker,
                "price": price,
                "volume": volume,
                "notional": notional,
                "exchange": random.choice(_DARK_POOL_EXCHANGES),
                "side": random.choice(["buy", "sell", "unknown"]),
                "timestamp": (now - timedelta(minutes=random.randint(5, 300))).isoformat(),
            })
        prints.sort(key=lambda p: p["notional"], reverse=True)
        return {
            "ticker": ticker,
            "prints": prints,
            "total": len(prints),
            "total_dark_volume": sum(p["volume"] for p in prints),
            "total_dark_notional": round(sum(p["notional"] for p in prints), 2),
            "source": "unusual_whales_mock",
        }

    def _mock_congressional(self, ticker: str) -> dict[str, Any]:
        """Generate 3 realistic congressional trading disclosures."""
        now = datetime.now()
        amount_ranges = [
            "$1,001 - $15,000",
            "$15,001 - $50,000",
            "$50,001 - $100,000",
            "$100,001 - $250,000",
            "$250,001 - $500,000",
        ]
        trades = []
        used_politicians: list[str] = []
        for _ in range(3):
            available = [p for p in _POLITICIANS if p not in used_politicians]
            if not available:
                available = _POLITICIANS
            politician = random.choice(available)
            used_politicians.append(politician)
            days_ago = random.randint(1, 45)
            txn_date = now - timedelta(days=days_ago)
            filed_date = txn_date + timedelta(days=random.randint(15, 45))
            trades.append({
                "politician": politician,
                "action": random.choice(["Purchase", "Sale (Full)", "Sale (Partial)"]),
                "ticker": ticker,
                "amount_range": random.choice(amount_ranges),
                "transaction_date": txn_date.strftime("%Y-%m-%d"),
                "filed_date": filed_date.strftime("%Y-%m-%d"),
                "chamber": random.choice(["House", "Senate"]),
            })
        return {
            "ticker": ticker,
            "trades": trades,
            "total": len(trades),
            "source": "unusual_whales_mock",
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
                raise ConnectorError("Unusual Whales API rate limit hit") from exc
            raise ConnectorError(f"Unusual Whales API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"Unusual Whales connection error: {exc}") from exc


def _approximate_price(ticker: str) -> float:
    """Return an approximate base price for mock generation."""
    prices: dict[str, float] = {
        "AAPL": 250.0,
        "MSFT": 420.0,
        "GOOGL": 175.0,
        "AMZN": 190.0,
        "TSLA": 180.0,
        "NVDA": 900.0,
        "META": 500.0,
        "SPY": 520.0,
    }
    return prices.get(ticker.upper(), 150.0)
