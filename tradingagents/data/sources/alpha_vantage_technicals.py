"""Alpha Vantage server-side technical indicators source (optional augmentation).

Fetches RSI-14, MACD (12/26/9), BBANDS-20 and ATR-14 directly from
Alpha Vantage's dedicated indicator endpoints, so the caller does not
need to re-compute them from daily bars. Each indicator lives on its
own URL and returns a ``"Technical Analysis: {FUNC}"`` dict keyed by
date strings; we take the value(s) from the most recent date.

RATE LIMIT WARNING
==================

Alpha Vantage's free tier allows ~5 requests per minute. This module
issues **four** sequential requests per call (RSI, MACD, BBANDS, ATR),
so a single call can consume ~80% of the per-minute quota. This makes
it unsuitable for batch analyses and is why it is NOT wired into the
materializer by default. It is shipped as an *optional* augmentation
that a future ``data_vendor_technicals`` config flag could flip on for
a single-ticker workflow.

On any rate-limit response mid-batch we abort further requests and
return a partial result with ``fetched_ok=False`` so the caller can
fall back to computed values. Results are cached per
``(ticker_upper, today_utc_date)`` with a 1-hour TTL — the numbers
change slowly intraday and we want to respect the 5-req/min limit.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlphaVantageTechnicalsResult:
    """Immutable result of a batched Alpha Vantage technical indicator fetch.

    Each indicator field is ``None`` if its underlying request failed
    (rate limit, network error, empty payload). ``fetched_ok`` is
    ``True`` only when *all* four indicators were retrieved
    successfully; partial results surface the fields that *did*
    succeed so callers can still use them, but with ``fetched_ok=False``
    so the materializer knows to fall back to computed values.
    """

    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    bbands_upper: float | None
    bbands_middle: float | None
    bbands_lower: float | None
    atr_14: float | None
    fetched_ok: bool
    error: str | None


_EMPTY_RESULT = AlphaVantageTechnicalsResult(
    rsi_14=None,
    macd=None,
    macd_signal=None,
    macd_hist=None,
    bbands_upper=None,
    bbands_middle=None,
    bbands_lower=None,
    atr_14=None,
    fetched_ok=False,
    error=None,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_BASE_URL = "https://www.alphavantage.co/query"
_HTTP_TIMEOUT_SECONDS = 15.0
_CACHE_TTL_SECONDS = 60 * 60  # 1 hour

# Free-tier burst limit is roughly 1 request per second ("please consider
# spreading out your free API requests more sparingly"). We pause this
# many seconds between sequential indicator requests so that a single
# batch of 4 indicators (~5 seconds) stays well under the burst
# threshold. Tests monkeypatch this to 0 so the suite stays fast.
_INTER_REQUEST_SLEEP_SECONDS = 1.2


# ---------------------------------------------------------------------------
# In-process cache (thread-safe)
# ---------------------------------------------------------------------------


_cache_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, AlphaVantageTechnicalsResult]] = {}


def _cache_get(key: tuple[str, str]) -> AlphaVantageTechnicalsResult | None:
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


def _cache_put(
    key: tuple[str, str], result: AlphaVantageTechnicalsResult
) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), result)


def _clear_cache() -> None:
    """Test hook: wipe the in-process cache."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_rate_limit(payload: dict[str, Any]) -> str | None:
    """Return a rate-limit / error message if the payload signals one, else None."""
    err = payload.get("Error Message")
    if isinstance(err, str) and err:
        return f"alpha_vantage error: {err}"
    note = payload.get("Note")
    if isinstance(note, str) and note:
        return f"alpha_vantage rate limit: {note}"
    info = payload.get("Information")
    if isinstance(info, str) and info:
        # "Information" is overloaded: Alpha Vantage uses it for both
        # true rate-limit (quota exhausted) AND "this is a premium
        # endpoint" responses. The caller may want to treat them
        # differently — we leave that distinction to
        # :func:`_classify_endpoint_error`.
        return f"alpha_vantage rate limit: {info}"
    return None


def _is_premium_endpoint_error(message: str) -> bool:
    """Return ``True`` if the error is 'premium endpoint' (not a true rate limit).

    Premium-endpoint errors are per-function (e.g. MACD on the free
    tier) and do NOT indicate that the daily quota is exhausted — so
    the caller can continue trying other endpoints. True rate-limit
    errors ("spreading out your free API requests", "25 requests per
    day") mean the quota is gone and further calls are wasted.
    """
    lower = message.lower()
    return (
        "premium endpoint" in lower
        and "25 requests per day" not in lower
        and "spreading out" not in lower
    )


def _latest_entry(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Return the most-recent entry from a ``Technical Analysis: {FUNC}`` dict.

    Returns ``None`` if the key is missing or the dict is empty.
    """
    series = payload.get(key)
    if not isinstance(series, dict) or not series:
        return None
    try:
        latest_date = max(series.keys())
    except ValueError:
        return None
    entry = series.get(latest_date)
    if not isinstance(entry, dict):
        return None
    return entry


def _fetch_indicator(
    params: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
    """GET one indicator endpoint. Return ``(payload, error)``.

    ``payload`` is ``None`` on any failure and ``error`` is a
    descriptive string. On success ``error`` is ``None``.
    """
    try:
        response = requests.get(
            _BASE_URL, params=params, timeout=_HTTP_TIMEOUT_SECONDS
        )
    except requests.exceptions.RequestException as exc:
        return None, f"alpha_vantage network error: {exc}"
    if response.status_code != 200:
        return None, (
            f"alpha_vantage HTTP {response.status_code}: {response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        return None, f"alpha_vantage invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "alpha_vantage unexpected payload shape"
    rate_limit_error = _detect_rate_limit(payload)
    if rate_limit_error is not None:
        return None, rate_limit_error
    return payload, None


def _parse_float(entry: dict[str, Any], key: str) -> float | None:
    """Safely extract a float field from a technical-analysis entry."""
    raw = entry.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_INDICATOR_PARAMS: list[tuple[str, dict[str, str]]] = [
    (
        "RSI",
        {
            "function": "RSI",
            "interval": "daily",
            "time_period": "14",
            "series_type": "close",
        },
    ),
    (
        "MACD",
        {
            "function": "MACD",
            "interval": "daily",
            "series_type": "close",
        },
    ),
    (
        "BBANDS",
        {
            "function": "BBANDS",
            "interval": "daily",
            "time_period": "20",
            "series_type": "close",
        },
    ),
    (
        "ATR",
        {
            "function": "ATR",
            "interval": "daily",
            "time_period": "14",
        },
    ),
]


def _apply_indicator(
    name: str,
    payload: dict[str, Any],
    state: dict[str, float | None],
) -> None:
    """Extract the most-recent values for one indicator into ``state``."""
    entry = _latest_entry(payload, f"Technical Analysis: {name}")
    if entry is None:
        return
    if name == "RSI":
        state["rsi_14"] = _parse_float(entry, "RSI")
    elif name == "MACD":
        state["macd"] = _parse_float(entry, "MACD")
        state["macd_signal"] = _parse_float(entry, "MACD_Signal")
        state["macd_hist"] = _parse_float(entry, "MACD_Hist")
    elif name == "BBANDS":
        state["bbands_upper"] = _parse_float(entry, "Real Upper Band")
        state["bbands_middle"] = _parse_float(entry, "Real Middle Band")
        state["bbands_lower"] = _parse_float(entry, "Real Lower Band")
    elif name == "ATR":
        state["atr_14"] = _parse_float(entry, "ATR")


def fetch_alpha_vantage_technicals(
    ticker: str,
) -> AlphaVantageTechnicalsResult:
    """Fetch RSI-14 + MACD(12,26,9) + BBANDS-20 + ATR-14 from Alpha Vantage.

    Issues four sequential HTTP requests (one per indicator). On a
    per-endpoint *premium-endpoint* error (e.g. MACD is premium-only
    for free-tier keys), that specific indicator is skipped but the
    remaining indicators are still attempted. On a true *rate-limit*
    error (daily quota exhausted, 5/min burst exceeded) further
    requests are aborted because they are guaranteed to fail.

    The result has ``fetched_ok=True`` only when *all four* indicators
    were retrieved successfully; otherwise it surfaces whichever
    fields did succeed plus the first error encountered, and callers
    (e.g. the materializer) fall back to locally-computed values.

    Results are cached per ``(ticker_upper, today_utc_date)`` for 1
    hour to respect the free-tier 25-req/day quota.
    """
    today_str = datetime.now(timezone.utc).date().isoformat()
    cache_key = (ticker.upper(), today_str)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return replace(
            _EMPTY_RESULT, error="ALPHA_VANTAGE_API_KEY not set"
        )

    symbol = ticker.upper()
    state: dict[str, float | None] = {
        "rsi_14": None,
        "macd": None,
        "macd_signal": None,
        "macd_hist": None,
        "bbands_upper": None,
        "bbands_middle": None,
        "bbands_lower": None,
        "atr_14": None,
    }
    first_error: str | None = None
    hard_abort = False

    for idx, (name, base_params) in enumerate(_INDICATOR_PARAMS):
        if hard_abort:
            break
        if idx > 0 and _INTER_REQUEST_SLEEP_SECONDS > 0:
            # Respect the free-tier ~1 req/sec burst limit.
            time.sleep(_INTER_REQUEST_SLEEP_SECONDS)
        params = {"symbol": symbol, "apikey": api_key, **base_params}
        payload, err = _fetch_indicator(params)
        if err is not None or payload is None:
            err_msg = err or f"alpha_vantage {name}: unknown error"
            if first_error is None:
                first_error = err_msg
            if not _is_premium_endpoint_error(err_msg):
                # True rate limit or network error — no point trying
                # more endpoints.
                hard_abort = True
            continue
        _apply_indicator(name, payload, state)

    all_ok = first_error is None and all(
        state[k] is not None
        for k in (
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
            "bbands_upper",
            "bbands_middle",
            "bbands_lower",
            "atr_14",
        )
    )
    result = AlphaVantageTechnicalsResult(
        rsi_14=state["rsi_14"],
        macd=state["macd"],
        macd_signal=state["macd_signal"],
        macd_hist=state["macd_hist"],
        bbands_upper=state["bbands_upper"],
        bbands_middle=state["bbands_middle"],
        bbands_lower=state["bbands_lower"],
        atr_14=state["atr_14"],
        fetched_ok=all_ok,
        error=None if all_ok else first_error,
    )
    if all_ok:
        _cache_put(cache_key, result)
    return result
