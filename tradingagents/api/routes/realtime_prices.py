"""Real-time price snapshot endpoints.

Provides a lightweight endpoint for the signals table to fetch current prices
and daily change percentages.  Uses Databento live stream when available,
falling back to yfinance for a quick last-price lookup.

GET /api/v3/prices/snapshot?tickers=AAPL,MSFT,...
GET /api/v3/prices/stream/start?tickers=AAPL,MSFT,...  (start live stream)
GET /api/v3/prices/stream/stop                          (stop live stream)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/prices", tags=["realtime_prices"])

# In-memory yfinance fallback cache: {ticker: {data, ts}}
_yf_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_YF_CACHE_TTL: int = 5  # 5s (Databento tickers skip this path entirely)


def _yf_snapshot(ticker: str) -> dict[str, Any] | None:
    """Quick yfinance last-price lookup with 30s cache."""
    cached = _yf_cache.get(ticker)
    if cached and time.time() - cached[0] < _YF_CACHE_TTL:
        return cached[1]

    try:
        import yfinance as yf

        info = yf.Ticker(ticker).fast_info
        last = float(info.last_price)
        prev = float(info.previous_close) if hasattr(info, "previous_close") else last
        change_pct = ((last - prev) / prev * 100) if prev else 0.0

        snap = {
            "last": round(last, 2),
            "change_pct": round(change_pct, 3),
            "source": "yfinance",
        }
        _yf_cache[ticker] = (time.time(), snap)
        return snap
    except Exception as exc:
        logger.debug("yfinance snapshot failed for %s: %s", ticker, exc)
        return None


@router.get("/snapshot")
async def get_price_snapshots(
    tickers: str = Query(..., description="Comma-separated ticker list"),
) -> dict[str, dict[str, Any]]:
    """Return latest price snapshots for the requested tickers.

    Priority: Databento live cache > yfinance fast_info fallback.
    """
    import asyncio

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    result: dict[str, dict[str, Any]] = {}

    # 1) Try Databento live cache first
    try:
        from tradingagents.dataflows.connectors.databento_connector import (
            get_all_snapshots,
        )

        db_snaps = get_all_snapshots()
    except Exception:
        db_snaps = {}

    remaining: list[str] = []
    for t in ticker_list:
        if t in db_snaps:
            result[t] = db_snaps[t]
        else:
            remaining.append(t)

    # 2) Fallback to yfinance for tickers not in Databento cache
    if remaining:
        loop = asyncio.get_event_loop()
        futs = [loop.run_in_executor(None, _yf_snapshot, t) for t in remaining]
        snaps = await asyncio.gather(*futs, return_exceptions=True)
        for t, snap in zip(remaining, snaps):
            if isinstance(snap, dict) and snap is not None:
                result[t] = snap

    return result


@router.get("/stream/start")
async def start_stream(
    tickers: str = Query(..., description="Comma-separated ticker list"),
    schema: str = Query("ohlcv-1m", description="ohlcv-1s or ohlcv-1m"),
) -> dict[str, str]:
    """Start the Databento live streaming thread for the given tickers."""
    try:
        from tradingagents.dataflows.connectors.databento_connector import (
            start_live_stream,
        )

        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        start_live_stream(ticker_list, schema=schema)
        return {"status": "started", "tickers": ",".join(ticker_list), "schema": schema}
    except Exception as exc:
        logger.exception("Failed to start Databento stream")
        return {"status": "error", "detail": str(exc)}


@router.get("/stream/stop")
async def stop_stream() -> dict[str, str]:
    """Stop the Databento live streaming thread."""
    try:
        from tradingagents.dataflows.connectors.databento_connector import (
            stop_live_stream,
        )

        stop_live_stream()
        return {"status": "stopped"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
