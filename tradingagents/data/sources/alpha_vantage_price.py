"""Alpha Vantage price history source for the TickerBriefing materializer.

Fetches daily OHLCV history from Alpha Vantage's ``TIME_SERIES_DAILY``
endpoint and returns a pandas DataFrame with the SAME shape that
``yfinance.Ticker(t).history()`` returns (``Open/High/Low/Close/Volume``
columns with a tz-aware UTC ``DatetimeIndex``), so the downstream
materializer code is vendor agnostic.

NOTE ON FREE-TIER LIMITATIONS
==============================

Alpha Vantage's free tier is severely constrained for equity prices:

1. ``TIME_SERIES_DAILY_ADJUSTED`` (split-adjusted) is premium-only — so
   the ``Close`` column returned here is the *raw* close from
   ``TIME_SERIES_DAILY``, not split-adjusted. For tickers with recent
   splits this creates a discontinuity; for most use cases it is
   acceptable.
2. ``outputsize=full`` (20+ years of history) is also premium-only. The
   free tier only serves ``outputsize=compact`` which returns the most
   recent 100 data points (~5 calendar months for daily bars). Periods
   longer than ~4 months are therefore silently truncated to ~100
   trading days worth of data — still enough for the materializer's
   minimum-50-row threshold and for the 20/50 SMAs. The 200-day SMA
   and year-over-year stats will degrade gracefully.
3. The free tier has a hard 25-requests/day quota. Results are cached
   aggressively (15-minute TTL on success) to conserve the quota.

If the user upgrades to a premium key, ``outputsize=full`` and
``TIME_SERIES_DAILY_ADJUSTED`` both work transparently — flip the
``function`` / ``outputsize`` params in the request and the parser
already handles the extra adjusted-close and volume field shapes.

All functions are safe to call without an ``ALPHA_VANTAGE_API_KEY``:
in that case (or on any HTTP / parse / empty-data / rate-limit error)
an :class:`AlphaVantagePriceResult` with ``fetched_ok=False`` and an
informative ``error`` message is returned so the caller can fall back
to another data source.

Alpha Vantage's free tier imposes a hard limit of ~5 requests per
minute and ~500 per day. Rate-limit responses from the server come in
two shapes:

* ``{"Note": "Thank you for using Alpha Vantage! ..."}`` (legacy)
* ``{"Information": "... premium endpoint ..."}`` (newer)

Both are treated as failures (``fetched_ok=False``) so the materializer
can gracefully fall back to yfinance.

Results are cached in-process for 15 minutes keyed on
``(ticker_upper, period, today_utc_date)``.
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
class AlphaVantagePriceResult:
    """Immutable result of an Alpha Vantage daily-adjusted fetch.

    ``df`` has a tz-aware UTC ``DatetimeIndex`` and columns
    ``["Open", "High", "Low", "Close", "Volume"]`` — matching the shape
    of ``yfinance.Ticker(t).history()`` so downstream compute code can
    treat Alpha Vantage, Polygon and yfinance interchangeably.

    ``Close`` is Alpha Vantage's ``"4. close"`` field (raw close, not
    split-adjusted) because the free tier does not expose the adjusted
    endpoint. See the module docstring for details.
    """

    df: pd.DataFrame | None
    last_price: float | None
    data_age_seconds: int
    fetched_ok: bool
    error: str | None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_BASE_URL = "https://www.alphavantage.co/query"

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
_HTTP_TIMEOUT_SECONDS = 15.0


# ---------------------------------------------------------------------------
# In-process cache (thread-safe)
# ---------------------------------------------------------------------------


_cache_lock = threading.Lock()
_cache: dict[tuple[str, str, str], tuple[float, AlphaVantagePriceResult]] = {}


def _cache_get(key: tuple[str, str, str]) -> AlphaVantagePriceResult | None:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored_at, result = entry
        if now - stored_at > _CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        return result


def _cache_put(key: tuple[str, str, str], result: AlphaVantagePriceResult) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), result)


def _clear_cache() -> None:
    """Test hook: wipe the in-process cache."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _period_days(period: str) -> int:
    """Return the number of calendar days to retain for ``period``.

    Unknown periods default to 365 days (``"1y"``).
    """
    return _PERIOD_TO_DAYS.get(period, 365)


def _detect_rate_limit(payload: dict[str, Any]) -> str | None:
    """Return a rate-limit / error message if the payload signals one, else None.

    Alpha Vantage signals trouble via three top-level fields:

    * ``"Error Message"`` — upstream rejected the request (bad ticker,
      bad API call shape, etc.).
    * ``"Note"`` — legacy rate-limit response.
    * ``"Information"`` — newer rate-limit / premium-endpoint response.
    """
    err = payload.get("Error Message")
    if isinstance(err, str) and err:
        return f"alpha_vantage error: {err}"
    note = payload.get("Note")
    if isinstance(note, str) and note:
        return f"alpha_vantage rate limit: {note}"
    info = payload.get("Information")
    if isinstance(info, str) and info:
        return f"alpha_vantage rate limit: {info}"
    return None


def _parse_time_series(
    payload: dict[str, Any], period: str
) -> pd.DataFrame | None:
    """Parse a ``TIME_SERIES_DAILY`` payload into a yfinance-shaped DataFrame.

    Returns ``None`` if the payload has no usable rows.

    Uses the ``"4. close"`` field for the ``Close`` column (raw close —
    the free tier does not expose the adjusted endpoint). Falls back to
    ``"5. adjusted close"`` if present (premium tier) so a premium key
    transparently gets split-adjusted data. The ``Volume`` column comes
    from ``"5. volume"`` (free tier) or ``"6. volume"`` (premium).

    Output is sorted ascending by date and truncated to the last
    ``_period_days(period)`` calendar days relative to today's UTC date.
    """
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        return None

    rows: list[dict[str, float]] = []
    index: list[pd.Timestamp] = []
    for date_str, bar in series.items():
        if not isinstance(bar, dict):
            continue
        try:
            ts = pd.Timestamp(date_str).tz_localize("UTC")
        except (TypeError, ValueError):
            continue
        # Prefer adjusted close if present (premium), else raw close (free).
        close_raw = bar.get("5. adjusted close", bar.get("4. close", 0.0))
        # Volume field moves from "5. volume" (free) to "6. volume" (premium).
        volume_raw = bar.get("6. volume", bar.get("5. volume", 0.0))
        try:
            rows.append(
                {
                    "Open": float(bar.get("1. open", 0.0) or 0.0),
                    "High": float(bar.get("2. high", 0.0) or 0.0),
                    "Low": float(bar.get("3. low", 0.0) or 0.0),
                    "Close": float(close_raw or 0.0),
                    "Volume": float(volume_raw or 0.0),
                }
            )
        except (TypeError, ValueError):
            continue
        index.append(ts)

    if not rows:
        return None

    df = pd.DataFrame(
        rows,
        index=pd.DatetimeIndex(index, name="Date"),
        columns=["Open", "High", "Low", "Close", "Volume"],
    )
    df.sort_index(inplace=True)

    # Filter to the last N days per period mapping.
    cutoff = pd.Timestamp(
        datetime.now(timezone.utc) - timedelta(days=_period_days(period))
    )
    df = df[df.index >= cutoff]
    if df.empty:
        return None
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


def _fail(error: str) -> AlphaVantagePriceResult:
    return AlphaVantagePriceResult(
        df=None,
        last_price=None,
        data_age_seconds=0,
        fetched_ok=False,
        error=error,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_alpha_vantage_price_history(
    ticker: str,
    period: str = "1y",
) -> AlphaVantagePriceResult:
    """Fetch daily split-adjusted OHLCV from Alpha Vantage.

    Args:
        ticker: Equity symbol, e.g. ``"AAPL"``.
        period: One of ``"1mo" | "3mo" | "6mo" | "1y" | "2y" | "5y"``.
            Unknown values default to ``"1y"``.

    Returns:
        A frozen :class:`AlphaVantagePriceResult`. On any failure
        (missing API key, network error, non-200 response, Alpha Vantage
        error or rate-limit payload, empty time series) the result has
        ``fetched_ok=False`` and a descriptive ``error`` string — the
        caller is expected to fall back to another vendor.

    Successful results are cached in-process for 15 minutes, keyed on
    ``(ticker_upper, period, today_utc_date)``.
    """
    today_str = datetime.now(timezone.utc).date().isoformat()
    cache_key = (ticker.upper(), period, today_str)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return _fail("ALPHA_VANTAGE_API_KEY not set")

    # Use the free-tier TIME_SERIES_DAILY endpoint with outputsize=compact
    # (both the "ADJUSTED" variant and outputsize=full are premium on the
    # free tier — see the module docstring). compact returns the most
    # recent 100 bars, which is sufficient for the materializer's
    # minimum-50-row threshold. The parser also handles premium-shape
    # fields ("5. adjusted close", "6. volume") transparently so a
    # premium key would work without code changes (plus a manual flip of
    # function/outputsize below).
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": ticker.upper(),
        "outputsize": "compact",
        "apikey": api_key,
    }

    try:
        response = requests.get(
            _BASE_URL, params=params, timeout=_HTTP_TIMEOUT_SECONDS
        )
    except requests.exceptions.RequestException as exc:
        return _fail(f"alpha_vantage network error: {exc}")

    if response.status_code != 200:
        return _fail(
            f"alpha_vantage HTTP {response.status_code}: {response.text[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        return _fail(f"alpha_vantage invalid JSON: {exc}")

    if not isinstance(payload, dict):
        return _fail("alpha_vantage unexpected payload shape")

    rate_limit_error = _detect_rate_limit(payload)
    if rate_limit_error is not None:
        return _fail(rate_limit_error)

    df = _parse_time_series(payload, period)
    if df is None or df.empty:
        return _fail("alpha_vantage empty time series")

    last_close = float(df["Close"].iloc[-1])
    result = AlphaVantagePriceResult(
        df=df,
        last_price=round(last_close, 4),
        data_age_seconds=_data_age_seconds(df),
        fetched_ok=True,
        error=None,
    )
    _cache_put(cache_key, result)
    return result
