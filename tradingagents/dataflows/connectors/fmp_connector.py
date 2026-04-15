"""Financial Modeling Prep (FMP) data source connector.

Provides fundamentals (income statement, balance sheet, cash flow, ratios),
institutional holdings (13F), and ESG scores.

Requires FMP_API_KEY environment variable for live data.
Falls back to realistic mock data when the key is absent.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/api/v3"


class FMPConnector(BaseConnector):
    """Connector for Financial Modeling Prep API.

    Tier 2 — requires a paid key for full access (limited free tier available).
    """

    TIER = 2
    CATEGORIES = ["FUNDAMENTALS", "HOLDINGS"]

    def __init__(self, api_key: str | None = None):
        super().__init__(rate_limit=300, rate_period=60.0)
        self._api_key = api_key or os.environ.get("FMP_API_KEY", "")
        self._session = requests.Session()

    # -- abstract properties ---------------------------------------------------

    @property
    def name(self) -> str:
        return "fmp"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [
            ConnectorCategory.FUNDAMENTALS,
        ]

    # -- lifecycle -------------------------------------------------------------

    def connect(self) -> None:
        if self._api_key:
            self._session.params = {"apikey": self._api_key}  # type: ignore[assignment]
            logger.info("FMP connector using live API key")
        else:
            logger.warning(
                "FMP_API_KEY not set — falling back to mock data. "
                "Get a key at https://financialmodelingprep.com/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "ratios"

    # -- fetch dispatch --------------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "income_statement")
        dispatch = {
            "income_statement": self._fetch_income_statement,
            "balance_sheet": self._fetch_balance_sheet,
            "cashflow": self._fetch_cashflow,
            "ratios": self._fetch_ratios,
            "holders_13f": self._fetch_holders_13f,
            "esg_score": self._fetch_esg_score,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- income statement ------------------------------------------------------

    def _fetch_income_statement(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            raw = self._get(f"/income-statement/{ticker}", {"limit": 1})
            item = raw[0] if isinstance(raw, list) and raw else {}
            return {
                "ticker": ticker,
                "date": item.get("date"),
                "revenue": item.get("revenue"),
                "gross_profit": item.get("grossProfit"),
                "operating_income": item.get("operatingIncome"),
                "net_income": item.get("netIncome"),
                "eps": item.get("eps"),
                "source": "fmp",
            }
        return self._mock_income_statement(ticker)

    @staticmethod
    def _mock_income_statement(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "date": "2025-09-30",
            "revenue": 94_930_000_000,
            "gross_profit": 43_880_000_000,
            "operating_income": 29_640_000_000,
            "net_income": 24_160_000_000,
            "eps": 1.56,
            "source": "fmp_mock",
        }

    # -- balance sheet ---------------------------------------------------------

    def _fetch_balance_sheet(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            raw = self._get(f"/balance-sheet-statement/{ticker}", {"limit": 1})
            item = raw[0] if isinstance(raw, list) and raw else {}
            return {
                "ticker": ticker,
                "date": item.get("date"),
                "total_assets": item.get("totalAssets"),
                "total_liabilities": item.get("totalLiabilities"),
                "equity": item.get("totalStockholdersEquity"),
                "cash": item.get("cashAndCashEquivalents"),
                "debt": item.get("totalDebt"),
                "source": "fmp",
            }
        return self._mock_balance_sheet(ticker)

    @staticmethod
    def _mock_balance_sheet(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "date": "2025-09-30",
            "total_assets": 352_580_000_000,
            "total_liabilities": 274_190_000_000,
            "equity": 78_390_000_000,
            "cash": 30_740_000_000,
            "debt": 108_040_000_000,
            "source": "fmp_mock",
        }

    # -- cash flow -------------------------------------------------------------

    def _fetch_cashflow(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            raw = self._get(f"/cash-flow-statement/{ticker}", {"limit": 1})
            item = raw[0] if isinstance(raw, list) and raw else {}
            return {
                "ticker": ticker,
                "date": item.get("date"),
                "operating_cash_flow": item.get("operatingCashFlow"),
                "capital_expenditure": item.get("capitalExpenditure"),
                "free_cash_flow": item.get("freeCashFlow"),
                "dividends_paid": item.get("dividendsPaid"),
                "share_repurchases": item.get("commonStockRepurchased"),
                "source": "fmp",
            }
        return self._mock_cashflow(ticker)

    @staticmethod
    def _mock_cashflow(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "date": "2025-09-30",
            "operating_cash_flow": 28_440_000_000,
            "capital_expenditure": -2_780_000_000,
            "free_cash_flow": 25_660_000_000,
            "dividends_paid": -3_850_000_000,
            "share_repurchases": -19_240_000_000,
            "source": "fmp_mock",
        }

    # -- ratios ----------------------------------------------------------------

    def _fetch_ratios(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            raw = self._get(f"/ratios/{ticker}", {"limit": 1})
            item = raw[0] if isinstance(raw, list) and raw else {}
            return {
                "ticker": ticker,
                "pe_ratio": item.get("priceEarningsRatio"),
                "pb_ratio": item.get("priceBookValueRatio"),
                "ps_ratio": item.get("priceToSalesRatio"),
                "roe": item.get("returnOnEquity"),
                "roa": item.get("returnOnAssets"),
                "debt_to_equity": item.get("debtEquityRatio"),
                "current_ratio": item.get("currentRatio"),
                "quick_ratio": item.get("quickRatio"),
                "source": "fmp",
            }
        return self._mock_ratios(ticker)

    @staticmethod
    def _mock_ratios(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "pe_ratio": 28.5,
            "pb_ratio": 46.2,
            "ps_ratio": 7.8,
            "roe": 1.56,
            "roa": 0.27,
            "debt_to_equity": 1.87,
            "current_ratio": 1.07,
            "quick_ratio": 1.01,
            "source": "fmp_mock",
        }

    # -- 13F holders -----------------------------------------------------------

    def _fetch_holders_13f(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            raw = self._get(f"/institutional-holder/{ticker}", {})
            holders = []
            for item in (raw if isinstance(raw, list) else [])[:10]:
                holders.append({
                    "holder": item.get("holder", ""),
                    "shares": item.get("shares", 0),
                    "date_reported": item.get("dateReported", ""),
                    "change": item.get("change", 0),
                    "change_pct": item.get("changePercentage", 0),
                })
            return {
                "ticker": ticker,
                "holders": holders,
                "total": len(holders),
                "source": "fmp",
            }
        return self._mock_holders_13f(ticker)

    @staticmethod
    def _mock_holders_13f(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "holders": [
                {
                    "holder": "Vanguard Group Inc.",
                    "shares": 1_306_528_904,
                    "date_reported": "2025-12-31",
                    "change": 12_340_200,
                    "change_pct": 0.95,
                },
                {
                    "holder": "BlackRock Inc.",
                    "shares": 1_024_712_455,
                    "date_reported": "2025-12-31",
                    "change": -5_320_100,
                    "change_pct": -0.52,
                },
                {
                    "holder": "Berkshire Hathaway Inc.",
                    "shares": 905_560_000,
                    "date_reported": "2025-12-31",
                    "change": 0,
                    "change_pct": 0.0,
                },
                {
                    "holder": "State Street Corporation",
                    "shares": 582_410_322,
                    "date_reported": "2025-12-31",
                    "change": 3_810_500,
                    "change_pct": 0.66,
                },
                {
                    "holder": "FMR LLC (Fidelity)",
                    "shares": 350_881_700,
                    "date_reported": "2025-12-31",
                    "change": -8_140_300,
                    "change_pct": -2.27,
                },
            ],
            "total": 5,
            "source": "fmp_mock",
        }

    # -- ESG score -------------------------------------------------------------

    def _fetch_esg_score(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            raw = self._get(f"/esg-environmental-social-governance-data/{ticker}", {})
            item = raw[0] if isinstance(raw, list) and raw else {}
            return {
                "ticker": ticker,
                "environmental": item.get("environmentalScore"),
                "social": item.get("socialScore"),
                "governance": item.get("governanceScore"),
                "total": item.get("ESGScore"),
                "source": "fmp",
            }
        return self._mock_esg_score(ticker)

    @staticmethod
    def _mock_esg_score(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "environmental": 72,
            "social": 65,
            "governance": 80,
            "total": 72,
            "source": "fmp_mock",
        }

    # -- HTTP helper -----------------------------------------------------------

    def _get(self, endpoint: str, params: dict) -> Any:
        url = f"{_BASE_URL}{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                raise ConnectorError("FMP API rate limit hit") from exc
            raise ConnectorError(f"FMP API error: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"FMP connection error: {exc}") from exc
