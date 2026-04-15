"""Screener v3 routes -- high-volatility US equities + ETFs universe.

Exposes two endpoints:

* ``POST /api/v3/screener/run``  -- trigger a fresh screener run. Body is
  optional: ``{"date": "YYYY-MM-DD", "use_llm": true}``. Offloads the sync,
  network-heavy screener to :func:`asyncio.to_thread`.
* ``GET  /api/v3/screener/latest`` -- return the most recent cached screener
  result. Returns 404 when the cache is empty.

Both routes return ``ScreenerResult`` serialised as a plain dict with
datetimes rendered as ISO strings.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from tradingagents.screener.volatility_screener import (
    ScreenerResult,
    VolRank,
    _CACHE_DB_PATH,
    _deserialize,
    run_screener,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["screener"])


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _rank_to_dict(r: VolRank) -> dict[str, Any]:
    return asdict(r)


def _result_to_dict(result: ScreenerResult) -> dict[str, Any]:
    return {
        "computed_at": result.computed_at.isoformat(),
        "equities": [_rank_to_dict(r) for r in result.equities],
        "etfs": [_rank_to_dict(r) for r in result.etfs],
        "equities_shortlist": [_rank_to_dict(r) for r in result.equities_shortlist],
        "etfs_shortlist": [_rank_to_dict(r) for r in result.etfs_shortlist],
        "fetched_ok": result.fetched_ok,
        "error": result.error,
    }


def _latest_cached() -> ScreenerResult | None:
    """Return the newest cached ``ScreenerResult`` or ``None`` if empty."""
    if not _CACHE_DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(_CACHE_DB_PATH)
        try:
            row = conn.execute(
                "SELECT payload FROM screener_cache "
                "ORDER BY stored_at DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        logger.warning("screener cache read failed: %s", exc)
        return None
    if not row:
        return None
    try:
        return _deserialize(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("screener cache deserialize failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/screener/run")
async def run_screener_route(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Trigger a fresh screener run.

    Request body (all optional):

    * ``date``    -- ``"YYYY-MM-DD"``. Defaults to the most recent weekday.
    * ``use_llm`` -- ``bool``. Defaults to ``True``.

    Returns the :class:`ScreenerResult` serialised as JSON.
    """
    body = body or {}
    target_date: date | None = None
    if "date" in body and body["date"]:
        try:
            target_date = date.fromisoformat(str(body["date"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"bad date: {exc}") from exc

    use_llm = bool(body.get("use_llm", True))

    result = await asyncio.to_thread(
        run_screener,
        target_date,
        20,
        40,
        use_llm,
    )
    return _result_to_dict(result)


@router.get("/screener/latest")
async def get_latest_screener() -> dict[str, Any]:
    """Return the most recent cached screener result. 404 if nothing cached."""
    result = await asyncio.to_thread(_latest_cached)
    if result is None:
        raise HTTPException(status_code=404, detail="no cached screener result")
    return _result_to_dict(result)
