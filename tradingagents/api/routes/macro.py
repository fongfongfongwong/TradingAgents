"""Macro economics routes."""

from __future__ import annotations

import os
import random
from datetime import datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["macro"])


def _mock_macro() -> dict[str, Any]:
    """Realistic mock macro economic data."""
    return {
        "us": {
            "fed_funds_rate": 4.75,
            "unemployment": 4.1,
            "cpi_yoy": 2.8,
            "gdp_growth": 2.1,
            "t10y2y_spread": 0.35,
            "dgs10": 4.25,
            "dgs2": 3.90,
            "breakeven_10y": 2.45,
        },
        "global": {
            "ecb_deposit_rate": 3.75,
            "ecb_main_rate": 4.25,
            "boj_rate": 0.25,
            "boe_rate": 4.50,
        },
        "geopolitical": {
            "gpr_index": 124.5,
            "gpr_percentile_1y": 72,
            "gpr_trend": "elevated",
            "epu_us": 156.3,
            "epu_global": 189.2,
            "epu_china": 245.1,
            "epu_europe": 134.8,
        },
        "cli": {
            "us": 100.8,
            "china": 99.2,
            "euro_area": 100.1,
            "japan": 99.8,
            "uk": 100.3,
        },
        "timestamp": datetime.now().isoformat(),
        "data_source": "mock",
    }


@router.get("/macro")
async def get_macro_overview() -> dict[str, Any]:
    """Comprehensive macro economic overview."""
    fred_key = os.environ.get("FRED_API_KEY", "")

    if fred_key:
        try:
            import requests as req

            def _fred(series: str) -> float | None:
                resp = req.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series,
                        "api_key": fred_key,
                        "sort_order": "desc",
                        "limit": 1,
                        "file_type": "json",
                    },
                    timeout=5,
                )
                if resp.ok:
                    obs = resp.json().get("observations", [])
                    if obs and obs[0]["value"] != ".":
                        return float(obs[0]["value"])
                return None

            return {
                "us": {
                    "fed_funds_rate": _fred("FEDFUNDS"),
                    "unemployment": _fred("UNRATE"),
                    "cpi_yoy": _fred("CPIAUCSL"),
                    "gdp_growth": _fred("A191RL1Q225SBEA"),
                    "t10y2y_spread": _fred("T10Y2Y"),
                    "dgs10": _fred("DGS10"),
                    "dgs2": _fred("DGS2"),
                    "breakeven_10y": _fred("T10YIE"),
                },
                "global": {
                    "ecb_deposit_rate": None,
                    "ecb_main_rate": None,
                    "boj_rate": None,
                    "boe_rate": None,
                },
                "geopolitical": {
                    "gpr_index": 124.5,
                    "gpr_percentile_1y": 72,
                    "gpr_trend": "elevated",
                    "epu_us": 156.3,
                    "epu_global": 189.2,
                    "epu_china": 245.1,
                    "epu_europe": 134.8,
                },
                "cli": {"us": None, "china": None, "euro_area": None, "japan": None, "uk": None},
                "timestamp": datetime.now().isoformat(),
                "data_source": "fred+mock",
            }
        except Exception:
            pass

    return _mock_macro()


@router.get("/macro/calendar")
async def get_economic_calendar() -> list[dict[str, Any]]:
    """Upcoming economic events."""
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if finnhub_key:
        try:
            import requests as req
            resp = req.get(
                "https://finnhub.io/api/v1/calendar/economic",
                headers={"X-Finnhub-Token": finnhub_key},
                timeout=5,
            )
            if resp.ok:
                data = resp.json()
                events = data.get("economicCalendar", [])[:20]
                return [
                    {
                        "event": e.get("event", ""),
                        "country": e.get("country", ""),
                        "date": e.get("time", ""),
                        "impact": e.get("impact", ""),
                        "actual": e.get("actual"),
                        "estimate": e.get("estimate"),
                        "previous": e.get("prev"),
                    }
                    for e in events
                ]
        except Exception:
            pass

    # Mock calendar
    return [
        {"event": "FOMC Rate Decision", "country": "US", "date": "2026-04-15", "impact": "high", "actual": None, "estimate": "4.75%", "previous": "4.75%"},
        {"event": "Non-Farm Payrolls", "country": "US", "date": "2026-04-04", "impact": "high", "actual": "228K", "estimate": "215K", "previous": "195K"},
        {"event": "CPI (YoY)", "country": "US", "date": "2026-04-10", "impact": "high", "actual": None, "estimate": "2.8%", "previous": "2.9%"},
        {"event": "ECB Rate Decision", "country": "EU", "date": "2026-04-17", "impact": "high", "actual": None, "estimate": "3.75%", "previous": "3.75%"},
        {"event": "Initial Jobless Claims", "country": "US", "date": "2026-04-03", "impact": "medium", "actual": "225K", "estimate": "220K", "previous": "218K"},
        {"event": "ISM Manufacturing PMI", "country": "US", "date": "2026-04-01", "impact": "medium", "actual": "50.3", "estimate": "50.0", "previous": "49.8"},
        {"event": "BOJ Rate Decision", "country": "JP", "date": "2026-04-25", "impact": "high", "actual": None, "estimate": "0.25%", "previous": "0.25%"},
        {"event": "GDP (QoQ)", "country": "US", "date": "2026-04-30", "impact": "high", "actual": None, "estimate": "2.1%", "previous": "2.3%"},
    ]
