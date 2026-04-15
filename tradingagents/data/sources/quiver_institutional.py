"""QuiverQuant institutional-signals source.

Queries four Quiver Beta endpoints for a single ticker and aggregates the
result into a frozen :class:`QuiverInstitutionalResult`:

* Congressional trades (last 30 days) — net buys minus sells and the
  top buyer / seller names.
* Federal government contracts (last 90 days) — count and USD total.
* Lobbying spend (most recent filed quarter) — USD aggregated across all
  registrants for the ticker.
* SEC Form 4 insider transactions (last 90 days) — net BUY minus SELL
  transactions and the top insider buyer names.

Design constraints
------------------
* Every sub-query is wrapped in try/except. Partial success still returns
  ``fetched_ok=True`` with defaulted values for the failed sub-query.
* Total failure (missing API key or all four endpoints erroring) returns
  ``fetched_ok=False`` with all numeric zeros / empty lists.
* A module-level thread-safe cache keyed by ``(ticker, UTC-date)`` holds
  results for 60 minutes to amortise Quiver's $75/mo rate budget.
* HTTP 429 is retried once after a 2-second sleep; any other request
  failure short-circuits to the default for that sub-query.
* 15-second timeout per request. Bearer-token auth via
  ``QUIVER_API_KEY``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.quiverquant.com/beta"
_TIMEOUT_SECONDS = 15
_CACHE_TTL_SECONDS = 60 * 60  # 60 minutes
_RATE_LIMIT_RETRY_DELAY = 2.0

# Module-level requests.Session re-used across calls. Thread-safe for GETs.
_SESSION = requests.Session()

# Thread-safe cache: { (ticker_upper, yyyy_mm_dd): (timestamp, result) }
_CACHE: dict[tuple[str, str], tuple[float, "QuiverInstitutionalResult"]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class QuiverInstitutionalResult:
    """Immutable aggregate of the four Quiver institutional endpoints."""

    congressional_net_buys_30d: int
    congressional_top_buyers: list[str]
    congressional_top_sellers: list[str]
    govt_contracts_count_90d: int
    govt_contracts_total_usd: float
    lobbying_usd_last_quarter: float
    insider_net_txns_90d: int
    insider_top_buyers: list[str]
    data_age_seconds: int
    fetched_ok: bool
    error: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_result(error: str | None) -> QuiverInstitutionalResult:
    return QuiverInstitutionalResult(
        congressional_net_buys_30d=0,
        congressional_top_buyers=[],
        congressional_top_sellers=[],
        govt_contracts_count_90d=0,
        govt_contracts_total_usd=0.0,
        lobbying_usd_last_quarter=0.0,
        insider_net_txns_90d=0,
        insider_top_buyers=[],
        data_age_seconds=86400,
        fetched_ok=False,
        error=error,
    )


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _get_json(endpoint: str, api_key: str) -> Any:
    """GET an endpoint and return parsed JSON.

    One retry on HTTP 429. Raises ``requests.HTTPError`` / ``ValueError``
    for the caller to convert into a clean sub-query failure.
    """
    url = f"{_BASE_URL}{endpoint}"
    headers = _auth_headers(api_key)

    resp = _SESSION.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
    if resp.status_code == 429:
        logger.warning("Quiver 429 on %s; retrying after %.1fs", endpoint, _RATE_LIMIT_RETRY_DELAY)
        time.sleep(_RATE_LIMIT_RETRY_DELAY)
        resp = _SESSION.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)

    resp.raise_for_status()
    return resp.json()


def _parse_date(value: Any) -> datetime | None:
    """Best-effort ISO-8601 / YYYY-MM-DD date parser.

    Returns a timezone-aware UTC datetime or ``None`` if the value cannot
    be understood.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value)
    # Try ISO-8601 first.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # Try plain YYYY-MM-DD.
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _coerce_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Quiver sometimes returns stringified numbers.
        return float(str(value).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return 0.0


def _is_buy(transaction: Any) -> bool:
    if not transaction:
        return False
    t = str(transaction).lower()
    return "purchase" in t or t == "buy"


def _is_sell(transaction: Any) -> bool:
    if not transaction:
        return False
    t = str(transaction).lower()
    return "sale" in t or t == "sell"


def _top_names(counter: Counter[str], n: int = 3) -> list[str]:
    return [name for name, _ in counter.most_common(n) if name]


# ---------------------------------------------------------------------------
# Individual sub-queries
# ---------------------------------------------------------------------------


def _fetch_congressional(
    ticker: str, api_key: str, now: datetime
) -> tuple[int, list[str], list[str], bool]:
    """Return (net_buys_30d, top_buyers, top_sellers, ok)."""
    try:
        data = _get_json(f"/historical/congresstrading/{ticker}", api_key)
    except Exception as exc:  # noqa: BLE001 - sub-query is allowed to fail
        logger.warning("Quiver congress endpoint failed for %s: %s", ticker, exc)
        return 0, [], [], False

    if not isinstance(data, list):
        return 0, [], [], True  # treat non-list (e.g. {}) as empty but ok

    cutoff = now - timedelta(days=30)
    buys = 0
    sells = 0
    buyer_counter: Counter[str] = Counter()
    seller_counter: Counter[str] = Counter()

    for item in data:
        if not isinstance(item, dict):
            continue
        report_date = _parse_date(item.get("ReportDate") or item.get("TransactionDate"))
        if report_date is None or report_date < cutoff:
            continue

        name = item.get("Representative") or item.get("Senator") or ""
        if isinstance(name, str):
            name = name.strip()
        else:
            name = ""

        transaction = item.get("Transaction", "")
        if _is_buy(transaction):
            buys += 1
            if name:
                buyer_counter[name] += 1
        elif _is_sell(transaction):
            sells += 1
            if name:
                seller_counter[name] += 1

    return buys - sells, _top_names(buyer_counter), _top_names(seller_counter), True


def _fetch_govt_contracts(
    ticker: str, api_key: str, now: datetime
) -> tuple[int, float, bool]:
    """Return (count_90d, total_usd, ok)."""
    try:
        data = _get_json(f"/historical/govcontractsall/{ticker}", api_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Quiver govt-contracts endpoint failed for %s: %s", ticker, exc)
        return 0, 0.0, False

    if not isinstance(data, list):
        return 0, 0.0, True

    cutoff = now - timedelta(days=90)
    count = 0
    total = 0.0

    for item in data:
        if not isinstance(item, dict):
            continue
        date_val = _parse_date(item.get("Date") or item.get("ActionDate"))
        if date_val is None or date_val < cutoff:
            continue
        amount = _coerce_float(item.get("Amount") or item.get("Dollars"))
        count += 1
        total += amount

    return count, total, True


def _fetch_lobbying(ticker: str, api_key: str) -> tuple[float, bool]:
    """Return (lobbying_usd_last_quarter, ok).

    Quiver's ``/historical/lobbying/{ticker}`` returns one row per
    registrant-filing. Rows carry a ``Date`` (filing date) and an
    ``Amount``. When ``Year`` and ``Quarter`` are available they are
    preferred (exact quarter grouping); otherwise we fall back to the
    most-recent ``Date`` value in the feed and sum every row that matches
    that date, which is a robust proxy for "most recent quarterly filing".
    """
    try:
        data = _get_json(f"/historical/lobbying/{ticker}", api_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Quiver lobbying endpoint failed for %s: %s", ticker, exc)
        return 0.0, False

    if not isinstance(data, list) or not data:
        return 0.0, True

    valid = [i for i in data if isinstance(i, dict)]
    if not valid:
        return 0.0, True

    # --- Preferred path: (Year, Quarter) present on rows. ---
    def _yq_key(item: dict[str, Any]) -> tuple[int, int]:
        try:
            year = int(item.get("Year", 0) or 0)
        except (ValueError, TypeError):
            year = 0
        try:
            quarter = int(item.get("Quarter", 0) or 0)
        except (ValueError, TypeError):
            quarter = 0
        return year, quarter

    max_yq = max((_yq_key(i) for i in valid), default=(0, 0))
    if max_yq != (0, 0):
        total = sum(
            _coerce_float(item.get("Amount"))
            for item in valid
            if _yq_key(item) == max_yq
        )
        return total, True

    # --- Fallback: group by raw Date string (Quiver's filing-date grouping). ---
    def _date_key(item: dict[str, Any]) -> str:
        return str(item.get("Date") or "")

    max_date = max((_date_key(i) for i in valid if _date_key(i)), default="")
    if not max_date:
        return 0.0, True

    total = sum(
        _coerce_float(item.get("Amount"))
        for item in valid
        if _date_key(item) == max_date
    )
    return total, True


def _fetch_insiders(
    ticker: str, api_key: str, now: datetime
) -> tuple[int, list[str], bool]:
    """Return (net_txns_90d, top_buyers, ok).

    The Quiver Beta ``/live/insiders`` feed is market-wide (no per-ticker
    endpoint exists as of 2026-Q1), so we fetch the full recent feed and
    filter client-side by ``Ticker``. Field names use ``AcquiredDisposedCode``
    (``A`` = acquired / buy, ``D`` = disposed / sell) and ``Name``.
    """
    try:
        data = _get_json("/live/insiders", api_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Quiver insiders endpoint failed for %s: %s", ticker, exc)
        return 0, [], False

    if not isinstance(data, list):
        return 0, [], True

    cutoff = now - timedelta(days=90)
    buys = 0
    sells = 0
    buyer_counter: Counter[str] = Counter()

    for item in data:
        if not isinstance(item, dict):
            continue
        if str(item.get("Ticker", "")).upper() != ticker.upper():
            continue
        date_val = _parse_date(
            item.get("Date") or item.get("fileDate") or item.get("FilingDate")
        )
        if date_val is None or date_val < cutoff:
            continue
        acq_disp = (
            item.get("AcquiredDisposedCode")
            or item.get("acqDisp")
            or item.get("AcquiredDisposed")
            or ""
        )
        acq_disp = str(acq_disp).strip().upper()
        name = item.get("Name") or ""
        if isinstance(name, str):
            name = name.strip()
        else:
            name = ""

        if acq_disp == "A":
            buys += 1
            if name:
                buyer_counter[name] += 1
        elif acq_disp == "D":
            sells += 1

    return buys - sells, _top_names(buyer_counter), True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_quiver_institutional(ticker: str) -> QuiverInstitutionalResult:
    """Query Quiver's four institutional endpoints and aggregate.

    See the module docstring for endpoint list and failure semantics.
    """
    ticker_upper = (ticker or "").strip().upper()
    if not ticker_upper:
        return _empty_result("empty_ticker")

    api_key = os.environ.get("QUIVER_API_KEY", "").strip()
    if not api_key:
        return _empty_result("missing_api_key")

    # --- Cache lookup ---
    now = datetime.now(timezone.utc)
    cache_key = (ticker_upper, now.strftime("%Y-%m-%d"))
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            ts, result = cached
            if (time.time() - ts) < _CACHE_TTL_SECONDS:
                return result

    # --- Sub-queries (each independent; partial failures are tolerated) ---
    net_buys_30d, top_buyers, top_sellers, congress_ok = _fetch_congressional(
        ticker_upper, api_key, now
    )
    gov_count, gov_total, gov_ok = _fetch_govt_contracts(ticker_upper, api_key, now)
    lobbying_usd, lobbying_ok = _fetch_lobbying(ticker_upper, api_key)
    insider_net, insider_buyers, insider_ok = _fetch_insiders(
        ticker_upper, api_key, now
    )

    any_ok = congress_ok or gov_ok or lobbying_ok or insider_ok
    if not any_ok:
        result = _empty_result("all_endpoints_failed")
    else:
        failed = [
            label
            for label, ok in (
                ("congress", congress_ok),
                ("contracts", gov_ok),
                ("lobbying", lobbying_ok),
                ("insiders", insider_ok),
            )
            if not ok
        ]
        error_msg = ("partial:" + ",".join(failed)) if failed else None
        result = QuiverInstitutionalResult(
            congressional_net_buys_30d=net_buys_30d,
            congressional_top_buyers=top_buyers,
            congressional_top_sellers=top_sellers,
            govt_contracts_count_90d=gov_count,
            govt_contracts_total_usd=gov_total,
            lobbying_usd_last_quarter=lobbying_usd,
            insider_net_txns_90d=insider_net,
            insider_top_buyers=insider_buyers,
            data_age_seconds=0,
            fetched_ok=True,
            error=error_msg,
        )

    with _CACHE_LOCK:
        _CACHE[cache_key] = (time.time(), result)

    return result


def _clear_cache_for_testing() -> None:
    """Test helper: wipe the module cache. Not part of the public API."""
    with _CACHE_LOCK:
        _CACHE.clear()
