"""Price data routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api", tags=["price"])

_VALID_RANGES = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}


@router.get("/price/{ticker}")
async def get_price(
    ticker: str,
    range: str = Query("6m", alias="range"),
) -> list[dict[str, Any]]:
    """Return OHLCV price data for a ticker over the given range.

    Accepted range values: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max.
    The shorthand '6m' is normalised to '6mo'.
    """
    import yfinance as yf

    # Normalise common shorthands
    period = range.strip().lower()
    _SHORTHANDS = {"6m": "6mo", "3m": "3mo", "1m": "1mo"}
    period = _SHORTHANDS.get(period, period)

    if period not in _VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid range '{range}'. Must be one of: {sorted(_VALID_RANGES)}",
        )

    try:
        data = yf.download(ticker, period=period, progress=False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"yfinance error: {exc}") from exc

    if data is None or data.empty:
        raise HTTPException(status_code=404, detail=f"No price data for '{ticker}'")

    # yfinance returns MultiIndex columns like (Price, Ticker) — flatten to field names
    if hasattr(data.columns, "nlevels") and data.columns.nlevels > 1:
        data.columns = data.columns.droplevel(1)

    records: list[dict[str, Any]] = []
    for ts, row in data.iterrows():
        def safe(val: Any) -> float:
            try:
                v = float(val)
                return v if v == v else 0.0  # NaN check
            except (TypeError, ValueError):
                return 0.0

        records.append(
            {
                "time": ts.strftime("%Y-%m-%d"),
                "open": safe(row.get("Open", 0)),
                "high": safe(row.get("High", 0)),
                "low": safe(row.get("Low", 0)),
                "close": safe(row.get("Close", 0)),
                "volume": int(safe(row.get("Volume", 0))),
            }
        )

    return records
