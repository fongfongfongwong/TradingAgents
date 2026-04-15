"""SEC-API.io data source connector.

Provides structured extraction of SEC EDGAR filings including recent filings,
filing content extraction, and insider transaction filings (Form 4).

Requires SEC_API_KEY environment variable for live data.
Falls back to realistic mock data when the key is absent.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://efts.sec.gov/LATEST"
_SEC_API_BASE = "https://api.sec-api.io"


class SECAPIConnector(BaseConnector):
    """Connector for SEC-API.io structured filing extraction.

    Tier 2 — requires a paid API key for full access.
    """

    TIER = 2
    CATEGORIES = ["REGULATORY", "FUNDAMENTALS"]

    def __init__(self, api_key: str | None = None):
        super().__init__(rate_limit=10, rate_period=60.0)
        self._api_key = api_key or os.environ.get("SEC_API_KEY", "")
        self._session = requests.Session()

    # -- abstract properties ---------------------------------------------------

    @property
    def name(self) -> str:
        return "sec_api"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [
            ConnectorCategory.REGULATORY,
            ConnectorCategory.FUNDAMENTALS,
        ]

    # -- lifecycle -------------------------------------------------------------

    def connect(self) -> None:
        if self._api_key:
            self._session.headers.update({
                "Authorization": f"Bearer {self._api_key}",
            })
            logger.info("SEC-API connector using live API key")
        else:
            logger.warning(
                "SEC_API_KEY not set — falling back to mock data. "
                "Get a key at https://sec-api.io/"
            )
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "recent_filings"

    # -- fetch dispatch --------------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "recent_filings")
        dispatch = {
            "recent_filings": self._fetch_recent_filings,
            "filing_extract": self._fetch_filing_extract,
            "insider_filings": self._fetch_insider_filings,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- recent filings --------------------------------------------------------

    def _fetch_recent_filings(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            try:
                resp = self._session.get(
                    f"{_SEC_API_BASE}/filing-search",
                    params={
                        "query": f'ticker:"{ticker}"',
                        "from": "0",
                        "size": "5",
                        "sort": '[{"filedAt":{"order":"desc"}}]',
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                filings = []
                for hit in data.get("filings", []):
                    filings.append({
                        "filing_type": hit.get("formType", ""),
                        "filed_date": hit.get("filedAt", ""),
                        "company": hit.get("companyName", ""),
                        "description": hit.get("description", ""),
                        "accession_no": hit.get("accessionNo", ""),
                    })
                return {
                    "ticker": ticker,
                    "filings": filings,
                    "total": len(filings),
                    "source": "sec_api",
                }
            except requests.exceptions.RequestException:
                logger.warning("SEC-API live fetch failed — returning mock data")
        return self._mock_recent_filings(ticker)

    @staticmethod
    def _mock_recent_filings(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "filings": [
                {
                    "filing_type": "10-K",
                    "filed_date": "2025-11-01",
                    "company": f"{ticker} Inc.",
                    "description": "Annual report for fiscal year ending September 2025",
                    "accession_no": "0000320193-25-000106",
                },
                {
                    "filing_type": "10-Q",
                    "filed_date": "2025-08-02",
                    "company": f"{ticker} Inc.",
                    "description": "Quarterly report for the period ending June 2025",
                    "accession_no": "0000320193-25-000089",
                },
                {
                    "filing_type": "8-K",
                    "filed_date": "2025-07-31",
                    "company": f"{ticker} Inc.",
                    "description": "Current report — Q3 earnings release",
                    "accession_no": "0000320193-25-000087",
                },
                {
                    "filing_type": "DEF 14A",
                    "filed_date": "2025-01-10",
                    "company": f"{ticker} Inc.",
                    "description": "Definitive proxy statement for annual meeting",
                    "accession_no": "0000320193-25-000012",
                },
                {
                    "filing_type": "8-K",
                    "filed_date": "2025-04-30",
                    "company": f"{ticker} Inc.",
                    "description": "Current report — Q2 earnings release",
                    "accession_no": "0000320193-25-000054",
                },
            ],
            "total": 5,
            "source": "sec_api_mock",
        }

    # -- filing extract --------------------------------------------------------

    def _fetch_filing_extract(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            try:
                # Use the XBRL-to-JSON API for structured extraction
                resp = self._session.get(
                    f"{_SEC_API_BASE}/xbrl-to-json",
                    params={
                        "accession-no": params.get("accession_no", ""),
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                facts = data.get("StatementsOfIncome", {})
                bs = data.get("BalanceSheets", {})
                return {
                    "ticker": ticker,
                    "filing_type": params.get("filing_type", "10-K"),
                    "fiscal_year": params.get("fiscal_year"),
                    "revenue": facts.get("Revenues", {}).get("value"),
                    "net_income": facts.get("NetIncomeLoss", {}).get("value"),
                    "total_assets": bs.get("Assets", {}).get("value"),
                    "risk_factors_summary": None,
                    "source": "sec_api",
                }
            except requests.exceptions.RequestException:
                logger.warning("SEC-API extract failed — returning mock data")
        return self._mock_filing_extract(ticker)

    @staticmethod
    def _mock_filing_extract(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "filing_type": "10-K",
            "fiscal_year": 2025,
            "revenue": 391_040_000_000,
            "net_income": 97_150_000_000,
            "total_assets": 352_580_000_000,
            "risk_factors_summary": (
                "Key risks include macroeconomic conditions, competitive pressures "
                "in the smartphone and services markets, supply chain concentration "
                "in Asia-Pacific, regulatory scrutiny across multiple jurisdictions, "
                "and foreign exchange volatility impacting international revenue."
            ),
            "source": "sec_api_mock",
        }

    # -- insider filings (Form 4) ----------------------------------------------

    def _fetch_insider_filings(self, ticker: str, params: dict) -> dict[str, Any]:
        if self._api_key:
            try:
                resp = self._session.get(
                    f"{_SEC_API_BASE}/filing-search",
                    params={
                        "query": f'ticker:"{ticker}" AND formType:"4"',
                        "from": "0",
                        "size": "5",
                        "sort": '[{"filedAt":{"order":"desc"}}]',
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                insiders = []
                for hit in data.get("filings", []):
                    entities = hit.get("entities", [{}])
                    insiders.append({
                        "insider": entities[0].get("name", "") if entities else "",
                        "title": entities[0].get("title", "") if entities else "",
                        "form_type": hit.get("formType", "Form 4"),
                        "transaction": "Sale" if "Sale" in hit.get("description", "") else "Purchase",
                        "shares": None,
                        "price": None,
                        "date": hit.get("filedAt", ""),
                    })
                return {
                    "ticker": ticker,
                    "insiders": insiders,
                    "total": len(insiders),
                    "source": "sec_api",
                }
            except requests.exceptions.RequestException:
                logger.warning("SEC-API insider fetch failed — returning mock data")
        return self._mock_insider_filings(ticker)

    @staticmethod
    def _mock_insider_filings(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "insiders": [
                {
                    "insider": "Timothy D. Cook",
                    "title": "Chief Executive Officer",
                    "form_type": "Form 4",
                    "transaction": "Sale",
                    "shares": 125_000,
                    "price": 228.50,
                    "date": "2025-10-15",
                },
                {
                    "insider": "Luca Maestri",
                    "title": "SVP & Chief Financial Officer",
                    "form_type": "Form 4",
                    "transaction": "Sale",
                    "shares": 60_000,
                    "price": 231.20,
                    "date": "2025-09-28",
                },
                {
                    "insider": "Jeff Williams",
                    "title": "Chief Operating Officer",
                    "form_type": "Form 4",
                    "transaction": "Sale",
                    "shares": 40_000,
                    "price": 225.80,
                    "date": "2025-08-12",
                },
            ],
            "total": 3,
            "source": "sec_api_mock",
        }
