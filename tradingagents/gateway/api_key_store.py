"""SQLite-backed persistent API key store.

Stores API keys in ``~/.tradingagents/api_keys.db`` so they survive backend
restarts. Keys are loaded into ``os.environ`` on startup; writes go to both
the database and the live process environment simultaneously.

Schema::

    CREATE TABLE api_keys (
        key_id     TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

Thread-safe: all operations acquire a module-level lock and each call opens
its own SQLite connection (SQLite handles concurrent readers fine).

File permissions are forced to 0600 on every write.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".tradingagents" / "api_keys.db"
_LOCK = threading.Lock()


def _ensure_db() -> None:
    """Create the DB file and schema if missing. Forces 0600 perms."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id     TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    try:
        os.chmod(_DB_PATH, 0o600)
    except OSError:
        pass


def set_key(key_id: str, value: str) -> None:
    """Persist a key to the DB and set ``os.environ[key_id]``.

    Empty values are rejected — use :func:`delete_key` to clear.
    """
    if not key_id or not value:
        raise ValueError("key_id and value must be non-empty")
    with _LOCK:
        _ensure_db()
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute(
                "INSERT INTO api_keys (key_id, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key_id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key_id, value, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
        os.environ[key_id] = value


def get_key(key_id: str) -> str | None:
    """Read a key from the DB. Returns ``None`` if not set."""
    with _LOCK:
        if not _DB_PATH.exists():
            return None
        conn = sqlite3.connect(_DB_PATH)
        try:
            row = conn.execute(
                "SELECT value FROM api_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None


def delete_key(key_id: str) -> bool:
    """Remove a key from the DB and ``os.environ``. Returns True if removed."""
    with _LOCK:
        if not _DB_PATH.exists():
            return False
        conn = sqlite3.connect(_DB_PATH)
        try:
            cur = conn.execute("DELETE FROM api_keys WHERE key_id = ?", (key_id,))
            conn.commit()
            removed = cur.rowcount > 0
        finally:
            conn.close()
        if removed:
            os.environ.pop(key_id, None)
        return removed


def list_keys() -> dict[str, str]:
    """Return all persisted keys as ``{key_id: value}``."""
    with _LOCK:
        if not _DB_PATH.exists():
            return {}
        conn = sqlite3.connect(_DB_PATH)
        try:
            rows = conn.execute(
                "SELECT key_id, value FROM api_keys"
            ).fetchall()
        finally:
            conn.close()
        return {k: v for k, v in rows}


def load_all_into_env() -> int:
    """Load every persisted key into ``os.environ``.

    Call once at backend startup, after ``.env`` is read, so DB values take
    precedence over stale ``.env`` entries but the ``.env`` still seeds
    bootstrap keys like ``ANTHROPIC_API_KEY``.

    Returns the number of keys loaded.
    """
    keys = list_keys()
    for k, v in keys.items():
        os.environ[k] = v
    if keys:
        logger.info("Loaded %d API keys from %s", len(keys), _DB_PATH)
    return len(keys)
