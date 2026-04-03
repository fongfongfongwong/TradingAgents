"""Tests for DuckDB in-memory cache layer."""

import threading
import time

import pytest

from tradingagents.cache.duckdb_cache import DuckDBCache
from tradingagents.cache.decorators import cached, set_default_cache


# ---------------------------------------------------------------------------
# DuckDBCache core tests
# ---------------------------------------------------------------------------


class TestDuckDBCacheGetSet:
    """Basic get/set operations."""

    def test_set_and_get(self):
        cache = DuckDBCache()
        cache.set("key1", {"value": 42})
        result = cache.get("key1")
        assert result == {"value": 42}

    def test_get_missing_key_returns_none(self):
        cache = DuckDBCache()
        assert cache.get("nonexistent") is None

    def test_set_overwrites_existing(self):
        cache = DuckDBCache()
        cache.set("key1", {"v": 1})
        cache.set("key1", {"v": 2})
        assert cache.get("key1") == {"v": 2}

    def test_nested_dict_roundtrip(self):
        cache = DuckDBCache()
        data = {"a": [1, 2, 3], "b": {"nested": True}, "c": None}
        cache.set("complex", data)
        assert cache.get("complex") == data


class TestDuckDBCacheTTL:
    """TTL and expiry behaviour."""

    def test_entry_expires_after_ttl(self):
        cache = DuckDBCache()
        cache.set("short", {"v": 1}, ttl_seconds=1)
        time.sleep(1.1)
        assert cache.get("short") is None

    def test_max_age_override(self):
        cache = DuckDBCache()
        cache.set("item", {"v": 1}, ttl_seconds=300)
        # Still valid with default TTL
        assert cache.get("item") is not None
        # Force a very short max_age
        time.sleep(0.1)
        assert cache.get("item", max_age_seconds=0) is None


class TestDuckDBCacheInvalidation:
    """Invalidation methods."""

    def test_invalidate_single_key(self):
        cache = DuckDBCache()
        cache.set("k1", {"v": 1})
        cache.invalidate("k1")
        assert cache.get("k1") is None

    def test_invalidate_by_prefix(self):
        cache = DuckDBCache()
        cache.set("ticker:AAPL:price", {"p": 150})
        cache.set("ticker:AAPL:volume", {"vol": 1000})
        cache.set("ticker:GOOG:price", {"p": 2800})
        cache.invalidate_by_prefix("ticker:AAPL")
        assert cache.get("ticker:AAPL:price") is None
        assert cache.get("ticker:AAPL:volume") is None
        assert cache.get("ticker:GOOG:price") is not None

    def test_clear_removes_all(self):
        cache = DuckDBCache()
        for i in range(5):
            cache.set(f"k{i}", {"i": i})
        cache.clear()
        for i in range(5):
            assert cache.get(f"k{i}") is None


class TestDuckDBCacheStats:
    """Statistics tracking."""

    def test_stats_initial(self):
        cache = DuckDBCache()
        s = cache.stats()
        assert s["total_entries"] == 0
        assert s["hit_count"] == 0
        assert s["miss_count"] == 0
        assert s["hit_rate"] == 0.0

    def test_stats_after_hits_and_misses(self):
        cache = DuckDBCache()
        cache.set("a", {"v": 1})
        cache.get("a")       # hit
        cache.get("a")       # hit
        cache.get("missing") # miss
        s = cache.stats()
        assert s["hit_count"] == 2
        assert s["miss_count"] == 1
        assert s["hit_rate"] == pytest.approx(2 / 3)
        assert s["total_entries"] == 1


class TestDuckDBCacheCleanup:
    """Expired entry cleanup."""

    def test_cleanup_expired_removes_stale(self):
        cache = DuckDBCache()
        cache.set("old", {"v": 1}, ttl_seconds=1)
        cache.set("new", {"v": 2}, ttl_seconds=300)
        time.sleep(1.1)
        # Force cleanup
        with cache._lock:
            cache._cleanup_expired()
        # old should be gone, new should remain
        s = cache.stats()
        assert s["total_entries"] == 1


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestDuckDBCacheThreadSafety:
    """Concurrent access must not corrupt data."""

    def test_concurrent_writes(self):
        cache = DuckDBCache()
        errors = []

        def writer(start):
            try:
                for i in range(50):
                    cache.set(f"t{start}_{i}", {"n": start * 100 + i})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent writes: {errors}"
        s = cache.stats()
        assert s["total_entries"] == 200  # 4 threads * 50 keys

    def test_concurrent_read_write(self):
        cache = DuckDBCache()
        cache.set("shared", {"v": 0})
        errors = []

        def reader():
            try:
                for _ in range(100):
                    cache.get("shared")
            except Exception as exc:
                errors.append(exc)

        def writer():
            try:
                for i in range(100):
                    cache.set("shared", {"v": i})
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# Decorator tests
# ---------------------------------------------------------------------------


class TestCachedDecorator:
    """Tests for the @cached decorator."""

    def setup_method(self):
        self._cache = DuckDBCache()
        set_default_cache(self._cache)

    def test_decorator_caches_result(self):
        call_count = 0

        @cached(ttl=60)
        def expensive():
            nonlocal call_count
            call_count += 1
            return {"result": 42}

        r1 = expensive()
        r2 = expensive()
        assert r1 == {"result": 42}
        assert r2 == {"result": 42}
        assert call_count == 1  # second call served from cache

    def test_decorator_respects_ttl(self):
        call_count = 0

        @cached(ttl=1)
        def short_lived():
            nonlocal call_count
            call_count += 1
            return {"n": call_count}

        r1 = short_lived()
        assert r1 == {"n": 1}
        time.sleep(1.1)
        r2 = short_lived()
        assert r2 == {"n": 2}
        assert call_count == 2

    def test_decorator_custom_key_func(self):
        call_count = 0

        @cached(ttl=60, key_func=lambda ticker: f"price:{ticker}")
        def get_price(ticker):
            nonlocal call_count
            call_count += 1
            return {"ticker": ticker, "price": 100 + call_count}

        r1 = get_price("AAPL")
        r2 = get_price("AAPL")
        r3 = get_price("GOOG")
        assert r1 == r2
        assert r3 != r1
        assert call_count == 2  # AAPL cached, GOOG is new

    def test_decorator_non_dict_return_not_cached(self):
        """Non-dict returns should pass through without caching."""
        call_count = 0

        @cached(ttl=60)
        def returns_list():
            nonlocal call_count
            call_count += 1
            return [1, 2, 3]

        r1 = returns_list()
        r2 = returns_list()
        assert r1 == [1, 2, 3]
        assert r2 == [1, 2, 3]
        assert call_count == 2  # not cached because return is a list
