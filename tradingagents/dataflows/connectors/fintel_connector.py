"""Fintel data source connector.

Provides institutional holdings, short interest, and insider trading data.
Requires FINTEL_API_KEY environment variable for live API access; falls
back to realistic mock data when unavailable.
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

_BASE_URL = "https://api.fintel.io/web/v0"


class FintelConnector(BaseConnector):
    """Connector for Fintel institutional and short-interest data.

    Tier 2: paid API for institutional holdings, short interest, and insider
    trades. Falls back to realistic mock data when API key is absent.
    """

    TIER = 2
    CATEGORIES = ["FUNDAMENTALS", "ALTERNATIVE"]

    _DATA_TYPES = ("institutional_holders", "short_interest", "insider_trades")

    def __init__(self, api_key: str | None = None) -> None:
        super().__init__(rate_limit=30, rate_period=60.0)
        self._api_key = api_key or os.environ.get("FINTEL_API_KEY", "")
        self._session = requests.Session()
        self._use_mock = not bool(self._api_key)

    @property
    def name(self) -> str:
        return "fintel"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.FUNDAMENTALS, ConnectorCategory.ALTERNATIVE]

    def connect(self) -> None:
        if self._api_key:
            self._session.headers.update({"X-API-KEY": self._api_key})
        else:
            logger.warning(
                "FINTEL_API_KEY not set — using mock data. "
                "Get a key at https://fintel.io/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "institutional_holders"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "institutional_holders")
        dispatch = {
            "institutional_holders": self._fetch_institutional_holders,
            "short_interest": self._fetch_short_interest,
            "insider_trades": self._fetch_insider_trades,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- institutional holders --------------------------------------------------

    def _fetch_institutional_holders(
        self, ticker: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self._use_mock:
            return self._mock_institutional_holders(ticker)
        return self._live_institutional_holders(ticker)

    def _live_institutional_holders(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/so/i/{ticker.lower()}")
        holders = []
        for item in data if isinstance(data, list) else []:
            holders.append({
                "name": item.get("name", ""),
                "shares": item.get("shares", 0),
                "change_pct": item.get("changePct", 0.0),
                "value": item.get("value", 0),
                "filing_date": item.get("filingDate", ""),
            })
        return {
            "ticker": ticker,
            "holders": holders[:20],
            "total": len(holders),
            "source": "fintel",
        }

    @staticmethod
    def _mock_institutional_holders(ticker: str) -> dict[str, Any]:
        today = datetime.now()
        random.seed(hash(ticker) % 2**32)
        holders = [
            {
                "name": "Vanguard Group Inc",
                "shares": 198_432_100,
                "change_pct": round(random.uniform(-2.0, 3.5), 2),
                "value": 38_750_000_000,
                "filing_date": (today - timedelta(days=45)).strftime("%Y-%m-%d"),
            },
            {
                "name": "BlackRock Inc",
                "shares": 163_218_500,
                "change_pct": round(random.uniform(-1.5, 2.8), 2),
                "value": 31_890_000_000,
                "filing_date": (today - timedelta(days=45)).strftime("%Y-%m-%d"),
            },
            {
                "name": "State Street Corporation",
                "shares": 94_715_300,
                "change_pct": round(random.uniform(-3.0, 1.5), 2),
                "value": 18_510_000_000,
                "filing_date": (today - timedelta(days=50)).strftime("%Y-%m-%d"),
            },
            {
                "name": "FMR LLC (Fidelity)",
                "shares": 72_841_200,
                "change_pct": round(random.uniform(-1.0, 4.0), 2),
                "value": 14_230_000_000,
                "filing_date": (today - timedelta(days=48)).strftime("%Y-%m-%d"),
            },
            {
                "name": "Capital Research Global Investors",
                "shares": 58_320_800,
                "change_pct": round(random.uniform(-5.0, 2.0), 2),
                "value": 11_400_000_000,
                "filing_date": (today - timedelta(days=52)).strftime("%Y-%m-%d"),
            },
            {
                "name": "T. Rowe Price Associates",
                "shares": 45_912_600,
                "change_pct": round(random.uniform(-2.5, 3.0), 2),
                "value": 8_970_000_000,
                "filing_date": (today - timedelta(days=47)).strftime("%Y-%m-%d"),
            },
            {
                "name": "Geode Capital Management",
                "shares": 38_104_500,
                "change_pct": round(random.uniform(-1.8, 2.2), 2),
                "value": 7_450_000_000,
                "filing_date": (today - timedelta(days=46)).strftime("%Y-%m-%d"),
            },
            {
                "name": "Northern Trust Corporation",
                "shares": 29_875_300,
                "change_pct": round(random.uniform(-2.0, 1.5), 2),
                "value": 5_840_000_000,
                "filing_date": (today - timedelta(days=51)).strftime("%Y-%m-%d"),
            },
            {
                "name": "JP Morgan Chase & Co",
                "shares": 24_618_900,
                "change_pct": round(random.uniform(-3.5, 5.0), 2),
                "value": 4_810_000_000,
                "filing_date": (today - timedelta(days=49)).strftime("%Y-%m-%d"),
            },
            {
                "name": "Bank of America Corporation",
                "shares": 19_327_400,
                "change_pct": round(random.uniform(-4.0, 3.0), 2),
                "value": 3_780_000_000,
                "filing_date": (today - timedelta(days=53)).strftime("%Y-%m-%d"),
            },
        ]
        return {
            "ticker": ticker,
            "holders": holders,
            "total": len(holders),
            "source": "fintel_mock",
        }

    # -- short interest ---------------------------------------------------------

    def _fetch_short_interest(
        self, ticker: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self._use_mock:
            return self._mock_short_interest(ticker)
        return self._live_short_interest(ticker)

    def _live_short_interest(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/ss/us/{ticker.lower()}")
        si = data if isinstance(data, dict) else {}
        return {
            "ticker": ticker,
            "short_interest_pct": si.get("shortInterestPct", 0.0),
            "short_ratio": si.get("shortRatio", 0.0),
            "shares_short": si.get("sharesShort", 0),
            "days_to_cover": si.get("daysToCover", 0.0),
            "source": "fintel",
        }

    @staticmethod
    def _mock_short_interest(ticker: str) -> dict[str, Any]:
        random.seed(hash(ticker + "_si") % 2**32)
        shares_short = random.randint(5_000_000, 45_000_000)
        return {
            "ticker": ticker,
            "short_interest_pct": round(random.uniform(1.0, 12.5), 2),
            "short_ratio": round(random.uniform(1.0, 6.5), 2),
            "shares_short": shares_short,
            "days_to_cover": round(random.uniform(1.2, 5.8), 1),
            "source": "fintel_mock",
        }

    # -- insider trades ---------------------------------------------------------

    def _fetch_insider_trades(
        self, ticker: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if self._use_mock:
            return self._mock_insider_trades(ticker)
        return self._live_insider_trades(ticker)

    def _live_insider_trades(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/n/it/us/{ticker.lower()}")
        trades = []
        for item in data if isinstance(data, list) else []:
            trades.append({
                "insider_name": item.get("name", ""),
                "title": item.get("title", ""),
                "action": item.get("transactionType", ""),
                "shares": item.get("shares", 0),
                "price": item.get("price", 0.0),
                "date": item.get("filingDate", ""),
            })
        return {
            "ticker": ticker,
            "trades": trades[:20],
            "total": len(trades),
            "source": "fintel",
        }

    @staticmethod
    def _mock_insider_trades(ticker: str) -> dict[str, Any]:
        today = datetime.now()
        random.seed(hash(ticker + "_it") % 2**32)
        base_price = round(random.uniform(80.0, 350.0), 2)
        trades = [
            {
                "insider_name": "Tim Cook",
                "title": "Chief Executive Officer",
                "action": "Sale",
                "shares": 75_000,
                "price": round(base_price * 1.02, 2),
                "date": (today - timedelta(days=8)).strftime("%Y-%m-%d"),
            },
            {
                "insider_name": "Luca Maestri",
                "title": "SVP, Chief Financial Officer",
                "action": "Sale",
                "shares": 40_000,
                "price": round(base_price * 0.98, 2),
                "date": (today - timedelta(days=15)).strftime("%Y-%m-%d"),
            },
            {
                "insider_name": "Jeff Williams",
                "title": "Chief Operating Officer",
                "action": "Purchase",
                "shares": 20_000,
                "price": round(base_price * 0.95, 2),
                "date": (today - timedelta(days=22)).strftime("%Y-%m-%d"),
            },
            {
                "insider_name": "Katherine Adams",
                "title": "SVP, General Counsel",
                "action": "Sale",
                "shares": 15_000,
                "price": round(base_price * 1.01, 2),
                "date": (today - timedelta(days=30)).strftime("%Y-%m-%d"),
            },
            {
                "insider_name": "Deirdre O'Brien",
                "title": "SVP, Retail + People",
                "action": "Sale",
                "shares": 10_500,
                "price": round(base_price * 0.99, 2),
                "date": (today - timedelta(days=38)).strftime("%Y-%m-%d"),
            },
        ]
        return {
            "ticker": ticker,
            "trades": trades,
            "total": len(trades),
            "source": "fintel_mock",
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
                raise ConnectorError("Fintel API rate limit hit") from exc
            raise ConnectorError(f"Fintel API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"Fintel connection error: {exc}") from exc
