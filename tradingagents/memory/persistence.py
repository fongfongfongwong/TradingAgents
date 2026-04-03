"""SQLite-based persistence layer for TradingAgents memory.

Provides zero-config persistent storage using Python's built-in sqlite3 module.
No external dependencies required.
"""

import sqlite3
import threading
from typing import Optional


class SQLiteMemoryStore:
    """Thread-safe SQLite backend for persisting agent memories.

    Stores (situation, recommendation) pairs keyed by a memory name.
    Supports both in-memory and file-based databases.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file, or ":memory:" for in-memory only.
    table_prefix : str
        Optional prefix for the table name, useful for namespacing.
    """

    def __init__(self, db_path: str = ":memory:", table_prefix: str = "") -> None:
        self._db_path = db_path
        self._prefix = table_prefix
        self._table = f"{table_prefix}memories"
        self._lock = threading.Lock()

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    # ------------------------------------------------------------------
    # Schema setup
    # ------------------------------------------------------------------

    def _create_table(self) -> None:
        with self._lock:
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self._table}_name ON {self._table}(name)"
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, name: str, situations_and_advice: list[tuple[str, str]]) -> None:
        """Insert a batch of (situation, recommendation) pairs for *name*."""
        rows = [(name, sit, rec) for sit, rec in situations_and_advice]
        with self._lock:
            self._conn.executemany(
                f"INSERT INTO {self._table} (name, situation, recommendation) VALUES (?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def load(self, name: str) -> list[tuple[str, str]]:
        """Return all (situation, recommendation) pairs for *name*, ordered by created_at."""
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT situation, recommendation FROM {self._table} WHERE name = ? ORDER BY created_at, id",
                (name,),
            )
            return cursor.fetchall()

    def delete(self, name: str) -> None:
        """Delete all memories for *name*."""
        with self._lock:
            self._conn.execute(
                f"DELETE FROM {self._table} WHERE name = ?", (name,)
            )
            self._conn.commit()

    def list_names(self) -> list[str]:
        """Return all distinct memory names."""
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT DISTINCT name FROM {self._table} ORDER BY name"
            )
            return [row[0] for row in cursor.fetchall()]

    def count(self, name: str) -> int:
        """Count memories for *name*."""
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT COUNT(*) FROM {self._table} WHERE name = ?", (name,)
            )
            return cursor.fetchone()[0]

    def export_all(self) -> dict[str, list[tuple[str, str]]]:
        """Export every memory as ``{name: [(situation, recommendation), ...]}``."""
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT name, situation, recommendation FROM {self._table} ORDER BY name, created_at, id"
            )
            result: dict[str, list[tuple[str, str]]] = {}
            for name, situation, recommendation in cursor.fetchall():
                result.setdefault(name, []).append((situation, recommendation))
            return result

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "SQLiteMemoryStore":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
