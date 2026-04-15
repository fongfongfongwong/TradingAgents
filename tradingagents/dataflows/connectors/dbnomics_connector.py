"""DBnomics data source connector.

DBnomics aggregates macro-economic data from IMF, OECD, Eurostat, ECB, and
dozens of other national/international providers — all through a single free API.

No API key required (Tier 1 / free).
Falls back to realistic mock data when the network is unavailable.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.db.nomics.world/v22"


class DBnomicsConnector(BaseConnector):
    """Connector for DBnomics unified macro-economic API.

    Tier 1 — completely free, no API key needed.
    """

    TIER = 1
    CATEGORIES = ["MACRO"]

    def __init__(self) -> None:
        super().__init__(rate_limit=60, rate_period=60.0)
        self._session = requests.Session()
        # Allow an env var to force mock mode for testing
        self._force_mock = os.environ.get("DBNOMICS_MOCK", "").lower() in ("1", "true")

    # -- abstract properties ---------------------------------------------------

    @property
    def name(self) -> str:
        return "dbnomics"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.MACRO]

    # -- lifecycle -------------------------------------------------------------

    def connect(self) -> None:
        if self._force_mock:
            logger.info("DBnomics connector running in mock mode")
        else:
            logger.info("DBnomics connector using live API (no key required)")
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "ecb_rates"

    # -- fetch dispatch --------------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "ecb_rates")
        dispatch = {
            "ecb_rates": self._fetch_ecb_rates,
            "global_gdp": self._fetch_global_gdp,
            "oecd_cli": self._fetch_oecd_cli,
            "eurostat_cpi": self._fetch_eurostat_cpi,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- ECB interest rates ----------------------------------------------------

    def _fetch_ecb_rates(self, ticker: str, params: dict) -> dict[str, Any]:
        if not self._force_mock:
            try:
                deposit = self._get_series_latest("ECB", "FM", "FM.D.U2.EUR.4F.KR.DFR.LEV")
                main_refi = self._get_series_latest("ECB", "FM", "FM.D.U2.EUR.4F.KR.MRR_FR.LEV")
                marginal = self._get_series_latest("ECB", "FM", "FM.D.U2.EUR.4F.KR.MLFR.LEV")
                return {
                    "deposit_facility": deposit,
                    "main_refinancing": main_refi,
                    "marginal_lending": marginal,
                    "as_of": "live",
                    "source": "dbnomics",
                }
            except ConnectorError:
                logger.warning("DBnomics live fetch failed — returning mock data")
        return self._mock_ecb_rates()

    @staticmethod
    def _mock_ecb_rates() -> dict[str, Any]:
        return {
            "deposit_facility": 3.75,
            "main_refinancing": 4.25,
            "marginal_lending": 4.50,
            "as_of": "2026-03-15",
            "source": "dbnomics_mock",
        }

    # -- global GDP growth -----------------------------------------------------

    def _fetch_global_gdp(self, ticker: str, params: dict) -> dict[str, Any]:
        if not self._force_mock:
            try:
                # IMF World Economic Outlook GDP growth
                raw = self._get_dataset("IMF", "WEO:2024-10", "NGDP_RPCH")
                if raw:
                    countries = []
                    for series in raw[:10]:
                        countries.append({
                            "country": series.get("dimensions", {}).get("weo-country", ""),
                            "gdp_growth_pct": series.get("latest_value"),
                            "gdp_usd_trillions": None,
                        })
                    return {
                        "countries": countries,
                        "source": "dbnomics",
                    }
            except ConnectorError:
                logger.warning("DBnomics live GDP fetch failed — returning mock data")
        return self._mock_global_gdp()

    @staticmethod
    def _mock_global_gdp() -> dict[str, Any]:
        return {
            "countries": [
                {"country": "United States", "gdp_growth_pct": 2.1, "gdp_usd_trillions": 28.78},
                {"country": "China", "gdp_growth_pct": 4.7, "gdp_usd_trillions": 18.53},
                {"country": "Japan", "gdp_growth_pct": 1.0, "gdp_usd_trillions": 4.23},
                {"country": "Germany", "gdp_growth_pct": 0.2, "gdp_usd_trillions": 4.46},
                {"country": "India", "gdp_growth_pct": 6.5, "gdp_usd_trillions": 3.94},
                {"country": "United Kingdom", "gdp_growth_pct": 0.5, "gdp_usd_trillions": 3.33},
                {"country": "France", "gdp_growth_pct": 0.7, "gdp_usd_trillions": 3.05},
                {"country": "Brazil", "gdp_growth_pct": 2.9, "gdp_usd_trillions": 2.17},
                {"country": "Canada", "gdp_growth_pct": 1.2, "gdp_usd_trillions": 2.14},
                {"country": "South Korea", "gdp_growth_pct": 2.2, "gdp_usd_trillions": 1.71},
            ],
            "source": "dbnomics_mock",
        }

    # -- OECD Composite Leading Indicators -------------------------------------

    def _fetch_oecd_cli(self, ticker: str, params: dict) -> dict[str, Any]:
        if not self._force_mock:
            try:
                raw = self._get_dataset("OECD", "MEI_CLI", "LOLITOAA")
                if raw:
                    countries = []
                    for series in raw[:5]:
                        countries.append({
                            "country": series.get("dimensions", {}).get("LOCATION", ""),
                            "cli_value": series.get("latest_value"),
                        })
                    return {"countries": countries, "source": "dbnomics"}
            except ConnectorError:
                logger.warning("DBnomics live CLI fetch failed — returning mock data")
        return self._mock_oecd_cli()

    @staticmethod
    def _mock_oecd_cli() -> dict[str, Any]:
        return {
            "countries": [
                {"country": "United States", "cli_value": 100.8},
                {"country": "China", "cli_value": 101.2},
                {"country": "Germany", "cli_value": 99.1},
                {"country": "Japan", "cli_value": 100.3},
                {"country": "United Kingdom", "cli_value": 99.7},
            ],
            "source": "dbnomics_mock",
        }

    # -- Eurostat CPI ----------------------------------------------------------

    def _fetch_eurostat_cpi(self, ticker: str, params: dict) -> dict[str, Any]:
        if not self._force_mock:
            try:
                raw = self._get_dataset("Eurostat", "prc_hicp_manr", "CP00")
                if raw:
                    mapping: dict[str, float] = {}
                    for series in raw:
                        geo = series.get("dimensions", {}).get("geo", "")
                        val = series.get("latest_value")
                        if geo and val is not None:
                            mapping[geo.lower()] = val
                    return {
                        "euro_area": mapping.get("ea", mapping.get("ea20")),
                        "germany": mapping.get("de"),
                        "france": mapping.get("fr"),
                        "italy": mapping.get("it"),
                        "source": "dbnomics",
                    }
            except ConnectorError:
                logger.warning("DBnomics live CPI fetch failed — returning mock data")
        return self._mock_eurostat_cpi()

    @staticmethod
    def _mock_eurostat_cpi() -> dict[str, Any]:
        return {
            "euro_area": 2.4,
            "germany": 2.1,
            "france": 2.8,
            "italy": 1.9,
            "source": "dbnomics_mock",
        }

    # -- HTTP helpers ----------------------------------------------------------

    def _get_series_latest(
        self, provider: str, dataset: str, series_code: str
    ) -> float | None:
        """Fetch the most recent observation for a single series."""
        url = f"{_BASE_URL}/series/{provider}/{dataset}/{series_code}"
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            series = data.get("series", {})
            docs = series.get("docs", [])
            if docs:
                values = docs[0].get("value", [])
                # Walk from the end to find the last non-None value
                for val in reversed(values):
                    if val is not None:
                        return float(val)
            return None
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"DBnomics series fetch error: {exc}") from exc

    def _get_dataset(
        self, provider: str, dataset: str, indicator: str
    ) -> list[dict[str, Any]]:
        """Fetch multiple series from a dataset filtered by indicator."""
        url = f"{_BASE_URL}/series/{provider}/{dataset}"
        try:
            resp = self._session.get(
                url,
                params={"observations": 1, "limit": 20, "q": indicator},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            docs = data.get("series", {}).get("docs", [])
            results = []
            for doc in docs:
                values = doc.get("value", [])
                latest = None
                for val in reversed(values):
                    if val is not None:
                        latest = float(val)
                        break
                results.append({
                    "series_code": doc.get("series_code", ""),
                    "dimensions": doc.get("dimensions", {}),
                    "latest_value": latest,
                })
            return results
        except requests.exceptions.RequestException as exc:
            raise ConnectorError(f"DBnomics dataset fetch error: {exc}") from exc
