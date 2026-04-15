"""Unit tests for the SQLite-backed signals cache."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
import threading
from datetime import datetime, timedelta, timezone
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


# ---------------------------------------------------------------------------
# Basic roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_put_then_get_roundtrip() -> None:
    payload = {"signal": "BUY", "conviction": 72, "models_used": ["claude-sonnet-4-5"]}
    signals_cache.put("AAPL", "2026-04-05", payload)
    got = signals_cache.get("AAPL", "2026-04-05")
    assert got == payload


@pytest.mark.unit
def test_get_missing_returns_none() -> None:
    assert signals_cache.get("ZZZZ", "2026-04-05") is None


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ttl_expiry_deletes_on_read() -> None:
    signals_cache.put("MSFT", "2026-04-05", {"signal": "HOLD"})
    # Backdate computed_at by > 24 hours
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    conn = sqlite3.connect(str(signals_cache.db_path()))
    try:
        conn.execute(
            "UPDATE signals SET computed_at = ? WHERE ticker = ?", (stale, "MSFT")
        )
        conn.commit()
    finally:
        conn.close()

    assert signals_cache.get("MSFT", "2026-04-05") is None

    # Row should have been purged on read
    conn = sqlite3.connect(str(signals_cache.db_path()))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE ticker = ?", ("MSFT",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# clear_all / stats
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clear_all_wipes_everything() -> None:
    signals_cache.put("A", "2026-04-05", {"signal": "BUY"})
    signals_cache.put("B", "2026-04-05", {"signal": "HOLD"})
    assert signals_cache.stats()["total"] == 2
    signals_cache.clear_all()
    assert signals_cache.stats()["total"] == 0
    assert signals_cache.get("A", "2026-04-05") is None


@pytest.mark.unit
def test_stats_counts_fresh_and_expired() -> None:
    signals_cache.put("FRESH", "2026-04-05", {"signal": "BUY"})
    signals_cache.put("OLD", "2026-04-05", {"signal": "HOLD"})

    stale = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn = sqlite3.connect(str(signals_cache.db_path()))
    try:
        conn.execute(
            "UPDATE signals SET computed_at = ? WHERE ticker = ?", (stale, "OLD")
        )
        conn.commit()
    finally:
        conn.close()

    s = signals_cache.stats()
    assert s["total"] == 2
    assert s["fresh"] == 1
    assert s["expired"] == 1


# ---------------------------------------------------------------------------
# Concurrent writes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_concurrent_writes_all_succeed() -> None:
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            signals_cache.put(
                f"T{i}", "2026-04-05", {"signal": "BUY", "i": i}
            )
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent writes raised: {errors}"
    assert signals_cache.stats()["total"] == 10
    for i in range(10):
        assert signals_cache.get(f"T{i}", "2026-04-05") == {"signal": "BUY", "i": i}


# ---------------------------------------------------------------------------
# Schema version isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_version_mismatch_ignored() -> None:
    signals_cache.put("AAPL", "2026-04-05", {"signal": "BUY"})
    # Manually insert a row with a different schema version
    conn = sqlite3.connect(str(signals_cache.db_path()))
    try:
        conn.execute(
            """
            INSERT INTO signals
                (ticker, date, schema_version, decision_json, computed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "AAPL",
                "2026-04-05",
                999,
                '{"signal":"SHORT"}',
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Only the v1-schema row should surface
    got = signals_cache.get("AAPL", "2026-04-05")
    assert got == {"signal": "BUY"}


# ---------------------------------------------------------------------------
# Corrupt JSON row is purged, not raised
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_corrupt_json_is_deleted_not_raised() -> None:
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
                "BAD",
                "2026-04-05",
                signals_cache._SCHEMA_VERSION,
                "{this-is-not-json",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert signals_cache.get("BAD", "2026-04-05") is None
    assert signals_cache.stats()["total"] == 0


# ---------------------------------------------------------------------------
# File permissions
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_file_perms_are_0600_after_write() -> None:
    signals_cache.put("AAPL", "2026-04-05", {"signal": "BUY"})
    mode = stat.S_IMODE(os.stat(signals_cache.db_path()).st_mode)
    assert mode == 0o600
