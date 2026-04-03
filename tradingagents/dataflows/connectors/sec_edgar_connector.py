"""SEC EDGAR data source connector.

Uses the official SEC EDGAR REST APIs directly (no edgartools dependency).
Provides access to company filings, XBRL financials, and basic company info.

No API key required. SEC fair-access policy: max 10 requests/second with a
descriptive User-Agent header.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_XBRL_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_USER_AGENT = "TradingAgents research@example.com"


class SECEdgarConnector(BaseConnector):
    """Connector for the SEC EDGAR public REST APIs.

    Free, no API key.  Rate limit: 10 req/sec per SEC fair-access policy.
    """

    def __init__(self, user_agent: str | None = None):
        super().__init__(rate_limit=10, rate_period=1.0)
        self._user_agent = user_agent or _USER_AGENT
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self._user_agent,
            "Accept-Encoding": "gzip, deflate",
        })
        # Cache: ticker (upper) -> 10-digit CIK string
        self._ticker_to_cik: dict[str, str] = {}

    # -- abstract properties ---------------------------------------------------

    @property
    def name(self) -> str:
        return "sec_edgar"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.REGULATORY, ConnectorCategory.FUNDAMENTALS]

    # -- lifecycle -------------------------------------------------------------

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    # -- dispatch --------------------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "filings")
        dispatch = {
            "filings": self._fetch_filings,
            "financials": self._fetch_financials,
            "company_info": self._fetch_company_info,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- CIK resolution --------------------------------------------------------

    def _resolve_cik(self, ticker: str) -> str:
        """Resolve a ticker symbol to a 10-digit zero-padded CIK string.

        Uses the SEC company_tickers.json mapping and caches results.
        """
        upper = ticker.upper()
        if upper in self._ticker_to_cik:
            return self._ticker_to_cik[upper]

        data = self._get(_COMPANY_TICKERS_URL)
        if not isinstance(data, dict):
            raise ConnectorError("Unexpected format from company_tickers.json")

        for entry in data.values():
            t = str(entry.get("ticker", "")).upper()
            cik_raw = entry.get("cik_str", "")
            cik = str(cik_raw).zfill(10)
            self._ticker_to_cik[t] = cik

        if upper not in self._ticker_to_cik:
            raise ConnectorError(f"Ticker '{ticker}' not found in SEC EDGAR")

        return self._ticker_to_cik[upper]

    # -- data methods ----------------------------------------------------------

    def _fetch_filings(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch recent filings from the EDGAR submissions API."""
        cik = self._resolve_cik(ticker)
        url = _SUBMISSIONS_URL.format(cik=cik)
        data = self._get(url)

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        form_filter = params.get("form_type")
        limit = params.get("limit", 20)

        filings: list[dict[str, Any]] = []
        for i in range(min(len(forms), len(dates))):
            if form_filter and forms[i] != form_filter:
                continue
            accession = accessions[i] if i < len(accessions) else ""
            doc = primary_docs[i] if i < len(primary_docs) else ""
            filings.append({
                "form_type": forms[i],
                "filing_date": dates[i],
                "accession_number": accession,
                "primary_document": doc,
                "url": (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{int(cik)}/{accession.replace('-', '')}/{doc}"
                ) if accession and doc else None,
            })
            if len(filings) >= limit:
                break

        return {
            "ticker": ticker.upper(),
            "cik": cik,
            "filings": filings,
            "total": len(filings),
            "source": "sec_edgar",
        }

    def _fetch_financials(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch XBRL company facts (financial data)."""
        cik = self._resolve_cik(ticker)
        url = _XBRL_COMPANY_FACTS_URL.format(cik=cik)
        data = self._get(url)

        entity_name = data.get("entityName", "")
        facts_us_gaap = data.get("facts", {}).get("us-gaap", {})

        # Extract key financial metrics if available
        metrics_of_interest = params.get("metrics", [
            "Revenues",
            "NetIncomeLoss",
            "Assets",
            "Liabilities",
            "StockholdersEquity",
            "EarningsPerShareBasic",
            "OperatingIncomeLoss",
        ])

        financials: dict[str, Any] = {}
        for metric in metrics_of_interest:
            if metric in facts_us_gaap:
                units = facts_us_gaap[metric].get("units", {})
                # Typically "USD" or "USD/shares"
                for unit_key, entries in units.items():
                    recent = entries[-5:] if len(entries) > 5 else entries
                    financials[metric] = {
                        "unit": unit_key,
                        "recent_values": [
                            {
                                "end": e.get("end"),
                                "val": e.get("val"),
                                "form": e.get("form"),
                                "filed": e.get("filed"),
                            }
                            for e in recent
                        ],
                    }
                    break  # take first unit type

        return {
            "ticker": ticker.upper(),
            "cik": cik,
            "entity_name": entity_name,
            "financials": financials,
            "metrics_available": list(facts_us_gaap.keys())[:50],
            "source": "sec_edgar",
        }

    def _fetch_company_info(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch basic company information from EDGAR submissions."""
        cik = self._resolve_cik(ticker)
        url = _SUBMISSIONS_URL.format(cik=cik)
        data = self._get(url)

        return {
            "ticker": ticker.upper(),
            "cik": cik,
            "name": data.get("name", ""),
            "entity_type": data.get("entityType", ""),
            "sic": data.get("sic", ""),
            "sic_description": data.get("sicDescription", ""),
            "state_of_incorporation": data.get("stateOfIncorporation", ""),
            "fiscal_year_end": data.get("fiscalYearEnd", ""),
            "exchanges": data.get("exchanges", []),
            "ein": data.get("ein", ""),
            "website": data.get("website", ""),
            "phone": data.get("phone", ""),
            "addresses": data.get("addresses", {}),
            "source": "sec_edgar",
        }

    # -- HTTP helper -----------------------------------------------------------

    def _get(self, url: str, params: dict | None = None) -> Any:
        """Execute GET request with error handling."""
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 429:
                raise ConnectorError("SEC EDGAR rate limit hit") from exc
            if status == 404:
                raise ConnectorError(f"SEC EDGAR resource not found: {url}") from exc
            raise ConnectorError(f"SEC EDGAR API error (HTTP {status}): {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"SEC EDGAR connection error: {exc}") from exc
