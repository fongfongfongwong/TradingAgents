"""SQLite-backed persistent signals cache.

Stores ``FinalDecision`` JSON blobs keyed by ``(ticker, date, schema_version)``.
TTL: 24 hours. Safe for concurrent reads/writes via SQLite WAL mode.

Schema::

    CREATE TABLE signals (
        ticker          TEXT    NOT NULL,
        date            TEXT    NOT NULL,
        schema_version  INTEGER NOT NULL,
        decision_json   TEXT    NOT NULL,
        computed_at     TEXT    NOT NULL,
        PRIMARY KEY (ticker, date, schema_version)
    );

Each call opens its own connection — WAL mode + ``busy_timeout(5000)``
handles concurrent writers safely. On every write we force file
permissions to ``0600``. Corrupt JSON rows are deleted (not raised)
so a single bad row can never bring the cache down.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

_DB_PATH: Path = Path.home() / ".tradingagents" / "signals_cache.db"
_TTL_HOURS: int = 24
_SCHEMA_VERSION: int = 2
_BUSY_TIMEOUT_MS: int = 5000
_INIT_LOCK: threading.Lock = threading.Lock()
_INITIALISED: bool = False


# ---------------------------------------------------------------------------
# Path override (used by tests)
# ---------------------------------------------------------------------------


def _set_db_path(path: Path) -> None:
    """Point the cache at a different SQLite file (test helper)."""
    global _DB_PATH, _INITIALISED
    _DB_PATH = Path(path)
    _INITIALISED = False


def _chmod_safe(path: Path) -> None:
    """Force ``0600`` on the cache file; swallow non-POSIX errors."""
    try:
        os.chmod(path, 0o600)
    except OSError as exc:  # pragma: no cover - platform dependent
        logger.debug("chmod 0600 failed on %s: %s", path, exc)


def _connect() -> sqlite3.Connection:
    """Open a new SQLite connection with WAL + busy timeout tuned."""
    conn = sqlite3.connect(str(_DB_PATH), timeout=_BUSY_TIMEOUT_MS / 1000.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_db() -> None:
    """Create the DB file + schema on first use. Idempotent and thread-safe."""
    global _INITIALISED
    if _INITIALISED and _DB_PATH.exists():
        return
    with _INIT_LOCK:
        if _INITIALISED and _DB_PATH.exists():
            return
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(_DB_PATH.parent, 0o700)
        except OSError:  # pragma: no cover
            pass
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    ticker          TEXT    NOT NULL,
                    date            TEXT    NOT NULL,
                    schema_version  INTEGER NOT NULL,
                    decision_json   TEXT    NOT NULL,
                    computed_at     TEXT    NOT NULL,
                    PRIMARY KEY (ticker, date, schema_version)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
        _chmod_safe(_DB_PATH)
        _INITIALISED = True


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_expired(computed_at: str, now: datetime | None = None) -> bool:
    dt = _parse_ts(computed_at)
    if dt is None:
        return True
    now = now or _now_utc()
    return (now - dt) > timedelta(hours=_TTL_HOURS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get(ticker: str, date: str) -> dict[str, Any] | None:
    """Return the cached decision dict for ``(ticker, date)`` or ``None``.

    - Returns ``None`` if the entry is missing, expired, corrupt, or from
      a different schema version.
    - Expired and corrupt entries are deleted as a side effect (best effort).
    """
    _ensure_db()
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT decision_json, computed_at
              FROM signals
             WHERE ticker = ? AND date = ? AND schema_version = ?
            """,
            (ticker, date, _SCHEMA_VERSION),
        ).fetchone()
        if row is None:
            return None

        decision_json, computed_at = row

        if _is_expired(computed_at):
            conn.execute(
                "DELETE FROM signals WHERE ticker = ? AND date = ? AND schema_version = ?",
                (ticker, date, _SCHEMA_VERSION),
            )
            conn.commit()
            return None

        try:
            return json.loads(decision_json)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "Corrupt signals_cache row for %s/%s — deleting (%s)",
                ticker,
                date,
                exc,
            )
            conn.execute(
                "DELETE FROM signals WHERE ticker = ? AND date = ? AND schema_version = ?",
                (ticker, date, _SCHEMA_VERSION),
            )
            conn.commit()
            return None
    finally:
        conn.close()


def put(ticker: str, date: str, decision_dict: dict[str, Any]) -> None:
    """Upsert ``decision_dict`` into the cache for ``(ticker, date)``."""
    _ensure_db()
    try:
        payload = json.dumps(decision_dict, default=str, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        logger.error("signals_cache.put: decision not JSON-serialisable: %s", exc)
        return

    computed_at = _now_utc().isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO signals (ticker, date, schema_version, decision_json, computed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date, schema_version) DO UPDATE SET
                decision_json = excluded.decision_json,
                computed_at   = excluded.computed_at
            """,
            (ticker, date, _SCHEMA_VERSION, payload, computed_at),
        )
        conn.commit()
    finally:
        conn.close()
    _chmod_safe(_DB_PATH)


def purge_expired() -> int:
    """Delete all rows older than ``_TTL_HOURS``. Returns number deleted."""
    _ensure_db()
    cutoff = (_now_utc() - timedelta(hours=_TTL_HOURS)).isoformat()
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM signals WHERE computed_at < ?",
            (cutoff,),
        )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def clear_all() -> None:
    """Remove every row from the cache. Intended for tests/admin."""
    _ensure_db()
    conn = _connect()
    try:
        conn.execute("DELETE FROM signals")
        conn.commit()
    finally:
        conn.close()


def stats() -> dict[str, int]:
    """Return ``{"total": N, "fresh": N, "expired": N}`` counts."""
    _ensure_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT computed_at FROM signals WHERE schema_version = ?",
            (_SCHEMA_VERSION,),
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    now = _now_utc()
    expired = sum(1 for (ts,) in rows if _is_expired(ts, now=now))
    fresh = total - expired
    return {"total": total, "fresh": fresh, "expired": expired}


def purge_old_schema_versions() -> int:
    """Delete all entries with ``schema_version != _SCHEMA_VERSION``.

    Called automatically on first use after a schema bump (from the API
    lifespan hook). Returns the number of purged rows.
    """
    _ensure_db()
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM signals WHERE schema_version != ?",
            (_SCHEMA_VERSION,),
        )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def db_path() -> Path:
    """Return the current DB path (test helper)."""
    return _DB_PATH


__all__ = [
    "get",
    "put",
    "purge_expired",
    "purge_old_schema_versions",
    "clear_all",
    "stats",
    "db_path",
]
