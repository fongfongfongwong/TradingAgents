"""Unit tests for signals_cache schema version bump + purge helper."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradingagents.gateway import signals_cache


@pytest.fixture(autouse=True)
def _tmp_cache_path(tmp_path: Path) -> None:
    """Redirect the cache to a tmp file for every test, then restore."""
    original = signals_cache.db_path()
    target = tmp_path / "signals_cache.db"
    signals_cache._set_db_path(target)
    yield
    signals_cache._set_db_path(original)


def _insert_raw(
    ticker: str,
    date: str,
    schema_version: int,
    decision_json: str,
) -> None:
    """Bypass signals_cache.put() and write directly to the DB."""
    signals_cache._ensure_db()
    conn = sqlite3.connect(str(signals_cache.db_path()))
    try:
        conn.execute(
            """
            INSERT INTO signals
                (ticker, date, schema_version, decision_json, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ticker,
                date,
                schema_version,
                decision_json,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _row_count() -> int:
    conn = sqlite3.connect(str(signals_cache.db_path()))
    try:
        return int(
            conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema version is bumped
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_version_is_bumped() -> None:
    """Guard against accidental revert of the schema bump."""
    assert signals_cache._SCHEMA_VERSION >= 2


# ---------------------------------------------------------------------------
# purge_old_schema_versions removes entries from prior schema versions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_purge_old_schema_versions_removes_stale_rows() -> None:
    # Insert a "v1" row directly (simulating a pre-bump entry)
    _insert_raw("AAPL", "2026-04-05", 1, '{"signal":"BUY"}')
    # And a current-version row
    signals_cache.put("MSFT", "2026-04-05", {"signal": "HOLD"})

    assert _row_count() == 2

    purged = signals_cache.purge_old_schema_versions()
    assert purged == 1
    assert _row_count() == 1

    # The old row should no longer be retrievable
    assert signals_cache.get("AAPL", "2026-04-05") is None
    # The current-version row must still work
    assert signals_cache.get("MSFT", "2026-04-05") == {"signal": "HOLD"}


@pytest.mark.unit
def test_purge_old_schema_versions_no_op_when_only_current() -> None:
    signals_cache.put("NVDA", "2026-04-05", {"signal": "BUY"})
    purged = signals_cache.purge_old_schema_versions()
    assert purged == 0
    assert signals_cache.get("NVDA", "2026-04-05") == {"signal": "BUY"}


# ---------------------------------------------------------------------------
# get() returns None for old-schema rows and stale rows get cleaned
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_ignores_old_schema_rows() -> None:
    _insert_raw("AAPL", "2026-04-05", 1, '{"signal":"BUY"}')
    assert signals_cache.get("AAPL", "2026-04-05") is None


@pytest.mark.unit
def test_get_with_monkeypatched_schema_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a schema bump at runtime: old row should be unreachable
    and purge should remove it."""
    # Put with current version
    signals_cache.put("TSLA", "2026-04-05", {"signal": "BUY"})
    current = signals_cache._SCHEMA_VERSION

    # Bump schema_version to a higher value
    monkeypatch.setattr(signals_cache, "_SCHEMA_VERSION", current + 1)

    assert signals_cache.get("TSLA", "2026-04-05") is None

    purged = signals_cache.purge_old_schema_versions()
    assert purged == 1
    assert _row_count() == 0


# ---------------------------------------------------------------------------
# Corrupt JSON safety net
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_deletes_corrupt_json_row() -> None:
    _insert_raw(
        "BAD",
        "2026-04-05",
        signals_cache._SCHEMA_VERSION,
        "not valid json",
    )
    assert _row_count() == 1
    assert signals_cache.get("BAD", "2026-04-05") is None
    # Row deleted as side effect
    assert _row_count() == 0


# ---------------------------------------------------------------------------
# Normal put/get roundtrip still works after bump
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_put_get_roundtrip_after_bump() -> None:
    payload = {
        "signal": "BUY",
        "conviction": 80,
        "options_direction": "CALL",
        "options_impact": 0.12,
        "realized_vol_20d_pct": 25.3,
        "atr_pct_of_price": 1.8,
        "used_mock": False,
        "prompt_versions": {"signals": "v3"},
    }
    signals_cache.put("AAPL", "2026-04-05", payload)
    assert signals_cache.get("AAPL", "2026-04-05") == payload
