"""Polygon.io price history source for the TickerBriefing materializer.

Fetches daily (or intraday) OHLCV history from Polygon's Aggregates v2
endpoint and returns a pandas DataFrame with the SAME shape that
``yfinance.Ticker(t).history()`` returns, so the downstream materializer
code is vendor-agnostic.

All functions are safe to call without a ``POLYGON_API_KEY``: in that case
(or on any HTTP / parse / empty-data error) a ``PolygonPriceResult`` with
``fetched_ok=False`` and an informative ``error`` message is returned so
the caller can fall back to another data source.

Results are cached in-process for 15 minutes keyed on
``(ticker, period, timespan, today-date)``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolygonPriceResult:
    """Immutable result of a Polygon aggregates fetch.

    ``df`` has a tz-aware UTC ``DatetimeIndex`` and columns
    ``["Open", "High", "Low", "Close", "Volume"]`` — matching the shape of
    ``yfinance.Ticker(t).history()`` so downstream compute code can treat
    both vendors interchangeably.
    """

    df: pd.DataFrame | None
    last_price: float | None
    data_age_seconds: int
    fetched_ok: bool
    error: str | None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_BASE_URL = "https://api.polygon.io"

# period string -> number of calendar days to look back
_PERIOD_TO_DAYS: dict[str, int] = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}

_CACHE_TTL_SECONDS = 15 * 60  # 15 minutes

_HTTP_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------
# In-process cache (thread-safe)
# ---------------------------------------------------------------------------


_cache_lock = threading.Lock()
_cache: dict[tuple[str, str, str, str], tuple[float, PolygonPriceResult]] = {}


def _cache_get(key: tuple[str, str, str, str]) -> PolygonPriceResult | None:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored_at, result = entry
        if now - stored_at > _CACHE_TTL_SECONDS:
            # Stale — drop it so we re-fetch on next call.
            _cache.pop(key, None)
            return None
        return result


def _cache_put(key: tuple[str, str, str, str], result: PolygonPriceResult) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), result)


def _clear_cache() -> None:
    """Test hook: wipe the in-process cache."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _period_to_date_range(
    period: str, as_of_date: str | None = None
) -> tuple[str, str]:
    """Map a period alias (e.g. ``"1y"``) to ``(from_date, to_date)`` strings.

    Both dates are formatted ``YYYY-MM-DD``. When ``as_of_date`` is ``None``
    the range ends at today's UTC date (backward-compatible behaviour). When
    ``as_of_date`` is provided (``YYYY-MM-DD``) the range ends on that date —
    critical for historical backtests that must not leak future data.

    Unknown periods default to 1 year.
    """
    days = _PERIOD_TO_DAYS.get(period, 365)
    if as_of_date:
        try:
            end = datetime.strptime(as_of_date, "%Y-%m-%d").date()
        except ValueError:
            end = datetime.now(timezone.utc).date()
    else:
        end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _parse_aggregates_payload(payload: Any) -> pd.DataFrame | None:
    """Parse a Polygon aggregates response into a yfinance-shaped DataFrame.

    Returns ``None`` if the payload has no usable rows.
    """
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None

    rows: list[dict[str, float]] = []
    index: list[pd.Timestamp] = []
    for bar in results:
        if not isinstance(bar, dict):
            continue
        ts_ms = bar.get("t")
        if ts_ms is None:
            continue
        try:
            ts = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC")
        except (TypeError, ValueError, OverflowError):
            continue
        rows.append(
            {
                "Open": float(bar.get("o", 0.0) or 0.0),
                "High": float(bar.get("h", 0.0) or 0.0),
                "Low": float(bar.get("l", 0.0) or 0.0),
                "Close": float(bar.get("c", 0.0) or 0.0),
                "Volume": float(bar.get("v", 0.0) or 0.0),
            }
        )
        index.append(ts)

    if not rows:
        return None

    df = pd.DataFrame(
        rows,
        index=pd.DatetimeIndex(index, name="Date"),
        columns=["Open", "High", "Low", "Close", "Volume"],
    )
    df.sort_index(inplace=True)
    return df


def _data_age_seconds(df: pd.DataFrame) -> int:
    """Return how old the last bar is, in seconds, clamped at zero."""
    try:
        last_ts = df.index[-1]
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        delta = datetime.now(timezone.utc) - last_ts.to_pydatetime()
        return max(int(delta.total_seconds()), 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_polygon_price_history(
    ticker: str,
    period: str = "1y",
    timespan: str = "day",
    as_of_date: str | None = None,
) -> PolygonPriceResult:
    """Fetch OHLCV history from the Polygon Aggregates v2 endpoint.

    Args:
        ticker: Equity symbol, e.g. ``"AAPL"``.
        period: One of ``"1mo" | "3mo" | "6mo" | "1y" | "2y" | "5y"``.
            Unknown values default to ``"1y"``.
        timespan: Bar granularity — ``"day"``, ``"hour"``, or ``"minute"``.

    Returns:
        A frozen :class:`PolygonPriceResult`. On any failure (missing API
        key, network error, non-200 response, empty results) the result has
        ``fetched_ok=False`` and a descriptive ``error`` string — the caller
        is expected to fall back to another vendor.

    Successful results are cached in-process for 15 minutes, keyed on
    ``(ticker, period, timespan, today-date)``.
    """
    today_str = datetime.now(timezone.utc).date().isoformat()
    # Cache-key anchor: use as_of_date when provided so historical backtests
    # do not collide with the live "today" cache entry.
    anchor = as_of_date or today_str
    cache_key = (ticker.upper(), period, timespan, anchor)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        return PolygonPriceResult(
            df=None,
            last_price=None,
            data_age_seconds=0,
            fetched_ok=False,
            error="POLYGON_API_KEY not set",
        )

    from_date, to_date = _period_to_date_range(period, as_of_date)
    url = (
        f"{_BASE_URL}/v2/aggs/ticker/{ticker.upper()}"
        f"/range/1/{timespan}/{from_date}/{to_date}"
    )
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=_HTTP_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        return PolygonPriceResult(
            df=None,
            last_price=None,
            data_age_seconds=0,
            fetched_ok=False,
            error=f"polygon network error: {exc}",
        )

    if response.status_code != 200:
        return PolygonPriceResult(
            df=None,
            last_price=None,
            data_age_seconds=0,
            fetched_ok=False,
            error=f"polygon HTTP {response.status_code}: {response.text[:200]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        return PolygonPriceResult(
            df=None,
            last_price=None,
            data_age_seconds=0,
            fetched_ok=False,
            error=f"polygon invalid JSON: {exc}",
        )

    df = _parse_aggregates_payload(payload)
    if df is None or df.empty:
        return PolygonPriceResult(
            df=None,
            last_price=None,
            data_age_seconds=0,
            fetched_ok=False,
            error="polygon empty results",
        )

    last_close = float(df["Close"].iloc[-1])
    result = PolygonPriceResult(
        df=df,
        last_price=round(last_close, 4),
        data_age_seconds=_data_age_seconds(df),
        fetched_ok=True,
        error=None,
    )
    _cache_put(cache_key, result)
    return result
