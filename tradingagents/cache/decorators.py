"""Caching decorator using DuckDBCache."""

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Module-level default cache instance (lazy-initialized)
_default_cache = None


def _get_default_cache():
    """Get or create the module-level default DuckDBCache instance."""
    global _default_cache
    if _default_cache is None:
        from .duckdb_cache import DuckDBCache
        _default_cache = DuckDBCache()
    return _default_cache


def set_default_cache(cache) -> None:
    """Override the module-level default cache (useful for testing)."""
    global _default_cache
    _default_cache = cache


def cached(ttl: int = 300, key_func: Callable[..., str] | None = None):
    """Decorator that caches function return values in DuckDBCache.

    Args:
        ttl: Time-to-live in seconds for cached entries (default 300).
        key_func: Optional callable that receives the same args/kwargs as the
            decorated function and returns a cache key string. If None, a key
            is auto-generated from module, function name, args, and kwargs.

    Returns:
        Decorator function.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                cache = _get_default_cache()
            except Exception:
                logger.debug(
                    "Cache unavailable, calling %s directly", func.__name__
                )
                return func(*args, **kwargs)

            # Build cache key
            if key_func is not None:
                key = key_func(*args, **kwargs)
            else:
                sorted_kw = sorted(kwargs.items())
                key = f"{func.__module__}.{func.__name__}:{args}:{sorted_kw}"

            # Try cache
            try:
                result = cache.get(key, max_age_seconds=ttl)
                if result is not None:
                    return result
            except Exception:
                logger.debug("Cache get failed for %s", key)
                return func(*args, **kwargs)

            # Call the function
            result = func(*args, **kwargs)

            # Store in cache
            try:
                if isinstance(result, dict):
                    cache.set(key, result, ttl_seconds=ttl)
            except Exception:
                logger.debug("Cache set failed for %s", key)

            return result

        return wrapper
    return decorator
