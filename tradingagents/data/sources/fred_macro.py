"""FRED macro data source.

Fetches key macro series (DFF fed funds, DGS2, DGS10) from the FRED API and
computes derived metrics such as the 2y-10y yield curve in basis points.

Reads ``FRED_API_KEY`` from the environment. If no key is configured, the
fetch returns ``FredMacroResult(fetched_ok=False)`` without raising.

Results for individual ``(series, as_of_date)`` observations are cached in
process memory with a 1-hour TTL to avoid redundant calls when the
materializer is invoked repeatedly for nearby dates.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Final

import requests

logger = logging.getLogger(__name__)

_FRED_BASE_URL: Final[str] = "https://api.stlouisfed.org/fred"
_HTTP_TIMEOUT_SECONDS: Final[float] = 10.0
_CACHE_TTL_SECONDS: Final[float] = 3600.0

# Module-level session reused across calls. ``requests.Session`` is thread-safe
# enough for our read-only GET usage.
_session: Final[requests.Session] = requests.Session()

# Observation cache: {(series_id, as_of_date): (value_or_none, stored_at_epoch)}
_obs_cache: dict[tuple[str, str], tuple[float | None, float]] = {}
_obs_cache_lock = threading.Lock()


@dataclass(frozen=True)
class FredMacroResult:
    """Immutable result of a FRED macro fetch.

    Attributes:
        fed_funds_rate: Effective federal funds rate in percent (e.g. 5.25).
        yield_curve_2y10y_bps: (DGS10 - DGS2) in basis points. Can be negative.
        dgs2: 2-year treasury constant maturity yield in percent.
        dgs10: 10-year treasury constant maturity yield in percent.
        fetched_ok: True when at least one series was successfully retrieved
            and no top-level error occurred.
        error: Human readable error message when ``fetched_ok`` is False.
    """

    fed_funds_rate: float | None
    yield_curve_2y10y_bps: float | None
    dgs2: float | None
    dgs10: float | None
    fetched_ok: bool
    error: str | None


class _FredFetchError(Exception):
    """Internal error raised when a single FRED call fails."""


def _cache_get(series_id: str, as_of_date: str) -> tuple[bool, float | None]:
    """Return ``(hit, value)`` from the observation cache."""
    key = (series_id, as_of_date)
    now = time.time()
    with _obs_cache_lock:
        entry = _obs_cache.get(key)
        if entry is None:
            return (False, None)
        value, stored_at = entry
        if now - stored_at > _CACHE_TTL_SECONDS:
            _obs_cache.pop(key, None)
            return (False, None)
        return (True, value)


def _cache_put(series_id: str, as_of_date: str, value: float | None) -> None:
    key = (series_id, as_of_date)
    with _obs_cache_lock:
        _obs_cache[key] = (value, time.time())


def _fetch_latest_observation(
    series_id: str,
    as_of_date: str,
    api_key: str,
) -> float | None:
    """Fetch the most recent observation on or before ``as_of_date``.

    Returns the numeric value or ``None`` if FRED reports a missing value
    (marked as ``"."``). Raises ``_FredFetchError`` on HTTP/parse failures.
    """
    hit, cached = _cache_get(series_id, as_of_date)
    if hit:
        return cached

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_end": as_of_date,
        "sort_order": "desc",
        "limit": 1,
    }
    url = f"{_FRED_BASE_URL}/series/observations"

    try:
        resp = _session.get(url, params=params, timeout=_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
    except requests.exceptions.RequestException as exc:
        raise _FredFetchError(f"FRED request failed for {series_id}: {exc}") from exc
    except ValueError as exc:  # JSON decode error
        raise _FredFetchError(
            f"FRED returned invalid JSON for {series_id}: {exc}"
        ) from exc

    observations = payload.get("observations") or []
    if not observations:
        _cache_put(series_id, as_of_date, None)
        return None

    raw_value = observations[0].get("value")
    if raw_value is None or raw_value == ".":
        _cache_put(series_id, as_of_date, None)
        return None

    try:
        parsed = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise _FredFetchError(
            f"FRED returned non-numeric value for {series_id}: {raw_value!r}"
        ) from exc

    _cache_put(series_id, as_of_date, parsed)
    return parsed


def fetch_fred_macro(as_of_date: str) -> FredMacroResult:
    """Fetch fed funds, 2y and 10y treasury yields from FRED for ``as_of_date``.

    ``as_of_date`` must be formatted as ``YYYY-MM-DD``. The most recent
    observation on or before that date is used for each series.

    Computes ``yield_curve_2y10y_bps = (DGS10 - DGS2) * 100`` in basis points.

    If ``FRED_API_KEY`` is not set in the environment, returns a result with
    ``fetched_ok=False`` and a descriptive error. Any unexpected exception is
    caught and converted into a clean ``FredMacroResult`` with
    ``fetched_ok=False``.
    """
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        return FredMacroResult(
            fed_funds_rate=None,
            yield_curve_2y10y_bps=None,
            dgs2=None,
            dgs10=None,
            fetched_ok=False,
            error="FRED_API_KEY not set",
        )

    try:
        dff = _fetch_latest_observation("DFF", as_of_date, api_key)
        dgs2 = _fetch_latest_observation("DGS2", as_of_date, api_key)
        dgs10 = _fetch_latest_observation("DGS10", as_of_date, api_key)
    except _FredFetchError as exc:
        logger.warning("FRED fetch failed: %s", exc)
        return FredMacroResult(
            fed_funds_rate=None,
            yield_curve_2y10y_bps=None,
            dgs2=None,
            dgs10=None,
            fetched_ok=False,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — top-level safety net
        logger.exception("Unexpected FRED error")
        return FredMacroResult(
            fed_funds_rate=None,
            yield_curve_2y10y_bps=None,
            dgs2=None,
            dgs10=None,
            fetched_ok=False,
            error=f"unexpected error: {exc}",
        )

    yield_curve_bps: float | None
    if dgs2 is not None and dgs10 is not None:
        yield_curve_bps = round((dgs10 - dgs2) * 100.0, 2)
    else:
        yield_curve_bps = None

    return FredMacroResult(
        fed_funds_rate=dff,
        yield_curve_2y10y_bps=yield_curve_bps,
        dgs2=dgs2,
        dgs10=dgs10,
        fetched_ok=True,
        error=None,
    )
