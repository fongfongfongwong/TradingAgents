"""LangChain-compatible tool for macroeconomic data retrieval.

Fetches key macro indicators from the FRED connector (Federal Reserve
Economic Data) and formats them into a markdown report for LLM agent
consumption.
"""

from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# FRED series we pull by default
_DEFAULT_SERIES = [
    "FEDFUNDS",   # Federal Funds Rate
    "UNRATE",     # Unemployment Rate
    "CPIAUCSL",   # CPI (inflation proxy)
    "T10Y2Y",     # 10Y-2Y yield curve spread
    "DGS10",      # 10-Year Treasury rate
    "DGS2",       # 2-Year Treasury rate
    "T10YIE",     # 10-Year breakeven inflation
]


def _fetch_fred_series(series_ids: list[str]) -> dict[str, dict | None]:
    """Best-effort fetch of multiple FRED series via the FREDConnector."""
    results: dict[str, dict | None] = {}
    try:
        from tradingagents.dataflows.connectors.fred_connector import FREDConnector

        conn = FREDConnector()
        for sid in series_ids:
            try:
                data = conn.fetch(sid, {"data_type": "series", "limit": 5})
                results[sid] = data
            except Exception:
                logger.warning("FRED fetch failed for %s", sid, exc_info=True)
                results[sid] = None
        conn.disconnect()
    except Exception:
        logger.warning("FREDConnector unavailable; returning empty data", exc_info=True)
        for sid in series_ids:
            results[sid] = None
    return results


def _format_macro_report(data: dict[str, dict | None]) -> str:
    """Format raw FRED data into a readable markdown report."""
    from tradingagents.dataflows.connectors.fred_connector import KEY_SERIES

    lines = [
        "# Macroeconomic Environment Report",
        "",
        "| Indicator | Latest Value | Description |",
        "|-----------|-------------|-------------|",
    ]

    for sid, payload in data.items():
        desc = KEY_SERIES.get(sid, sid)
        if payload is None:
            lines.append(f"| {sid} | N/A | {desc} |")
            continue
        # The connector returns observations; grab the most recent value
        if isinstance(payload, dict):
            value = payload.get("value") or payload.get("latest_value", "N/A")
        else:
            value = "N/A"
        lines.append(f"| {sid} | {value} | {desc} |")

    lines.extend([
        "",
        "### Notes",
        "- Data sourced from FRED (Federal Reserve Economic Data).",
        "- Values reflect the most recently published observation.",
    ])
    return "\n".join(lines)


@tool
def get_macro_data(
    trade_date: Annotated[str, "Trade date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve key macroeconomic indicators from FRED.

    Fetches the latest readings for: Fed Funds Rate, Unemployment,
    CPI (inflation), yield curve spread (10Y-2Y), Treasury rates,
    and breakeven inflation.

    Args:
        trade_date (str): Trade date in yyyy-mm-dd format (for context).

    Returns:
        str: A markdown-formatted macro environment report.
    """
    try:
        data = _fetch_fred_series(_DEFAULT_SERIES)
        return _format_macro_report(data)
    except Exception:
        logger.exception("Macro data retrieval failed")
        return (
            "Macroeconomic data unavailable. "
            "The FRED connector could not be reached. "
            "Please rely on other available data sources for your analysis."
        )
