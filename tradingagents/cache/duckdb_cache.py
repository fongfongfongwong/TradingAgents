"""DuckDB-based in-memory cache with TTL support."""

import json
import threading
import time

import duckdb


class DuckDBCache:
    """Thread-safe in-memory cache backed by DuckDB.

    Uses an in-memory DuckDB database to store cache entries with
    automatic TTL-based expiration. Timestamps are stored as epoch
    floats for reliable cross-platform TTL arithmetic.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0
        self._conn = duckdb.connect(":memory:")
        self._conn.execute("""
            CREATE TABLE cache_entries (
                key VARCHAR PRIMARY KEY,
                data JSON,
                created_at DOUBLE,
                ttl_seconds INTEGER
            )
        """)
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 60  # seconds between auto-cleanup runs

    def get(self, key: str, max_age_seconds: int | None = None) -> dict | None:
        """Retrieve a cached value by key.

        Args:
            key: The cache key to look up.
            max_age_seconds: If provided, overrides the stored TTL for this
                lookup. The entry is considered expired if older than this.

        Returns:
            The cached dict, or None if missing/expired.
        """
        with self._lock:
            self._maybe_cleanup()
            now = time.time()
            result = self._conn.execute(
                "SELECT data, created_at, ttl_seconds FROM cache_entries WHERE key = ?",
                [key],
            ).fetchone()

            if result is None:
                self._miss_count += 1
                return None

            data_json, created_at, ttl_seconds = result

            # Determine effective TTL
            effective_ttl = max_age_seconds if max_age_seconds is not None else ttl_seconds

            if effective_ttl is not None:
                age = now - created_at
                if age > effective_ttl:
                    self._miss_count += 1
                    self._conn.execute(
                        "DELETE FROM cache_entries WHERE key = ?", [key]
                    )
                    return None

            self._hit_count += 1
            if isinstance(data_json, str):
                return json.loads(data_json)
            return data_json

    def set(self, key: str, data: dict, ttl_seconds: int = 300) -> None:
        """Store or update a cache entry.

        Args:
            key: The cache key.
            data: The dict to cache (stored as JSON).
            ttl_seconds: Time-to-live in seconds (default 300).
        """
        with self._lock:
            self._maybe_cleanup()
            now = time.time()
            data_json = json.dumps(data)
            self._conn.execute(
                """
                INSERT INTO cache_entries (key, data, created_at, ttl_seconds)
                VALUES (?, ?::JSON, ?, ?)
                ON CONFLICT (key) DO UPDATE SET
                    data = EXCLUDED.data,
                    created_at = EXCLUDED.created_at,
                    ttl_seconds = EXCLUDED.ttl_seconds
                """,
                [key, data_json, now, ttl_seconds],
            )

    def invalidate(self, key: str) -> None:
        """Delete a specific cache entry."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM cache_entries WHERE key = ?", [key]
            )

    def invalidate_by_prefix(self, prefix: str) -> None:
        """Delete all cache entries whose key starts with the given prefix."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM cache_entries WHERE key LIKE ?",
                [prefix + "%"],
            )

    def clear(self) -> None:
        """Delete all cache entries and reset stats."""
        with self._lock:
            self._conn.execute("DELETE FROM cache_entries")
            self._hit_count = 0
            self._miss_count = 0

    def stats(self) -> dict:
        """Return cache statistics.

        Returns:
            Dict with total_entries, hit_count, miss_count, hit_rate.
        """
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM cache_entries"
            ).fetchone()[0]
            total_requests = self._hit_count + self._miss_count
            hit_rate = (
                self._hit_count / total_requests if total_requests > 0 else 0.0
            )
            return {
                "total_entries": total,
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "hit_rate": hit_rate,
            }

    def _cleanup_expired(self) -> None:
        """Delete all expired entries. Caller must hold self._lock."""
        now = time.time()
        self._conn.execute(
            "DELETE FROM cache_entries WHERE (created_at + ttl_seconds) < ?",
            [now],
        )

    def _maybe_cleanup(self) -> None:
        """Run cleanup if enough time has passed. Caller must hold self._lock."""
        now = time.monotonic()
        if now - self._last_cleanup >= self._cleanup_interval:
            self._cleanup_expired()
            self._last_cleanup = now

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        with self._lock:
            self._conn.close()
