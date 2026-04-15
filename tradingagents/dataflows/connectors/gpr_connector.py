"""Geopolitical Risk (GPR) Index and Economic Policy Uncertainty (EPU) connector.

Data sources:
  - GPR Index: Dario Caldara & Matteo Iacoviello (Federal Reserve Board)
    https://www.matteoiacoviello.com/gpr.htm
  - EPU Index: Baker, Bloom & Davis
    https://www.policyuncertainty.com/

Both indices are free (Tier 1).  The connector attempts to download the
latest CSV from the official sites; if the download fails it returns
realistic mock values.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

import requests

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

_GPR_CSV_URL = (
    "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.csv"
)
_EPU_CSV_URL = (
    "https://policyuncertainty.com/media/Global_Policy_Uncertainty_Data.xlsx"
)


class GPRConnector(BaseConnector):
    """Connector for Geopolitical Risk Index and Economic Policy Uncertainty.

    Tier 1 — free, no API key required.
    """

    TIER = 1
    CATEGORIES = ["MACRO", "GEOPOLITICAL"]

    def __init__(self) -> None:
        super().__init__(rate_limit=10, rate_period=60.0)
        self._session = requests.Session()
        self._force_mock = os.environ.get("GPR_MOCK", "").lower() in ("1", "true")

    # -- abstract properties ---------------------------------------------------

    @property
    def name(self) -> str:
        return "gpr"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.MACRO]

    # -- lifecycle -------------------------------------------------------------

    def connect(self) -> None:
        if self._force_mock:
            logger.info("GPR connector running in mock mode")
        else:
            logger.info("GPR connector ready (free, no key required)")
        super().connect()

    def disconnect(self) -> None:
        self._session.close()
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "gpr_index"

    # -- fetch dispatch --------------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "gpr_index")
        dispatch = {
            "gpr_index": self._fetch_gpr_index,
            "epu_index": self._fetch_epu_index,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- GPR Index -------------------------------------------------------------

    def _fetch_gpr_index(self, ticker: str, params: dict) -> dict[str, Any]:
        if not self._force_mock:
            try:
                resp = self._session.get(_GPR_CSV_URL, timeout=20)
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                rows = list(reader)
                if rows:
                    last = rows[-1]
                    # Column names vary; try common variants
                    value = (
                        last.get("GPRD")
                        or last.get("GPR")
                        or last.get("gpr")
                    )
                    date = (
                        last.get("date")
                        or last.get("Date")
                        or last.get("DATE")
                        or ""
                    )
                    if value is not None:
                        val = float(value)
                        return {
                            "value": round(val, 2),
                            "date": date,
                            "percentile_1y": None,
                            "trend": "elevated" if val > 100 else "normal",
                            "description": self._describe_gpr(val),
                            "source": "gpr_live",
                        }
            except Exception:
                logger.warning("GPR CSV download failed — returning mock data")
        return self._mock_gpr_index()

    @staticmethod
    def _describe_gpr(value: float) -> str:
        if value > 200:
            return "Severe geopolitical stress — crisis-level readings"
        if value > 150:
            return "Very elevated risk — significant geopolitical tensions"
        if value > 100:
            return "Above historical average due to trade tensions"
        if value > 75:
            return "Moderate risk — near long-term average"
        return "Below average — relatively calm geopolitical environment"

    @staticmethod
    def _mock_gpr_index() -> dict[str, Any]:
        return {
            "value": 124.5,
            "date": "2026-03-01",
            "percentile_1y": 72,
            "trend": "elevated",
            "description": "Above historical average due to trade tensions",
            "source": "gpr_mock",
        }

    # -- EPU Index -------------------------------------------------------------

    def _fetch_epu_index(self, ticker: str, params: dict) -> dict[str, Any]:
        # The official EPU data is in xlsx format which requires openpyxl.
        # For robustness we try a simple CSV mirror first, then fall back.
        if not self._force_mock:
            try:
                # Try the US EPU CSV (Baker, Bloom, Davis)
                us_url = "https://policyuncertainty.com/media/US_Policy_Uncertainty_Data.csv"
                resp = self._session.get(us_url, timeout=20)
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                rows = list(reader)
                if rows:
                    last = rows[-1]
                    us_val = last.get("Three_Component_Index") or last.get("News_Based_Policy_Uncert_Index")
                    if us_val is not None:
                        return {
                            "us": round(float(us_val), 1),
                            "global": None,
                            "china": None,
                            "europe": None,
                            "date": f"{last.get('Year', '')}-{last.get('Month', '').zfill(2)}-01",
                            "source": "epu_live",
                        }
            except Exception:
                logger.warning("EPU CSV download failed — returning mock data")
        return self._mock_epu_index()

    @staticmethod
    def _mock_epu_index() -> dict[str, Any]:
        return {
            "us": 156.3,
            "global": 189.2,
            "china": 245.1,
            "europe": 134.8,
            "date": "2026-03-01",
            "source": "epu_mock",
        }
