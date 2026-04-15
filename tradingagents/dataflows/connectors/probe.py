"""Data source probe engine with standardized quality metrics.

Provides a unified way to monitor and compare all registered data source
connectors across dimensions like latency, freshness, completeness, and
rate-limit utilization.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .base import BaseConnector, ConnectorError, RateLimitExceededError
from .registry import ConnectorRegistry

logger = logging.getLogger(__name__)

_DEFAULT_PROBE_TICKER = "AAPL"

# Fields we expect in a minimal successful probe response
_EXPECTED_FIELDS_BY_DATA_TYPE: dict[str, list[str]] = {
    "quote": ["ticker", "current_price", "source"],
    "ohlcv": ["ticker", "bars", "source"],
    "news": ["ticker", "articles", "source"],
    "sentiment": ["ticker", "source"],
    "fundamentals": ["ticker", "data", "source"],
    "indicators": ["ticker", "indicators", "source"],
    "default": ["ticker", "source"],
}


@dataclass(frozen=True)
class ProbeResult:
    """Immutable snapshot of a single connector probe."""

    connector_name: str
    reachable: bool
    latency_ms: float
    freshness_seconds: float | None
    completeness_pct: float
    error_rate_1h: int
    rate_limit_pct: float
    health_score: float
    status: str  # ok | warn | err | unknown
    categories: list[str]
    tier: int
    last_probed_at: str  # ISO 8601
    detail: str
    sample_ticker: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_name": self.connector_name,
            "reachable": self.reachable,
            "latency_ms": round(self.latency_ms, 1),
            "freshness_seconds": (
                round(self.freshness_seconds, 1)
                if self.freshness_seconds is not None
                else None
            ),
            "completeness_pct": round(self.completeness_pct, 1),
            "error_rate_1h": self.error_rate_1h,
            "rate_limit_pct": round(self.rate_limit_pct, 1),
            "health_score": round(self.health_score, 1),
            "status": self.status,
            "categories": self.categories,
            "tier": self.tier,
            "last_probed_at": self.last_probed_at,
            "detail": self.detail,
            "sample_ticker": self.sample_ticker,
        }


class _ProbeHistory:
    """Rolling 1-hour error counter per connector (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # connector_name -> deque of error timestamps (epoch seconds)
        self._errors: dict[str, deque[float]] = {}
        # connector_name -> deque of ProbeResult dicts for trend
        self._results: dict[str, deque[dict[str, Any]]] = {}
        self._max_results = 60  # keep last 60 probes per connector

    def record_error(self, name: str) -> None:
        with self._lock:
            if name not in self._errors:
                self._errors[name] = deque()
            self._errors[name].append(time.time())

    def error_count_1h(self, name: str) -> int:
        cutoff = time.time() - 3600
        with self._lock:
            dq = self._errors.get(name)
            if not dq:
                return 0
            # Evict old entries
            while dq and dq[0] < cutoff:
                dq.popleft()
            return len(dq)

    def record_result(self, result: ProbeResult) -> None:
        with self._lock:
            name = result.connector_name
            if name not in self._results:
                self._results[name] = deque(maxlen=self._max_results)
            self._results[name].append(result.to_dict())

    def get_history(self, name: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            dq = self._results.get(name)
            if not dq:
                return []
            items = list(dq)
            return items[-limit:]


def _compute_health_score(
    reachable: bool,
    latency_ms: float,
    completeness_pct: float,
    rate_limit_pct: float,
) -> float:
    """Weighted composite: reachable(40) + latency(20) + completeness(20) + rate(20)."""
    if not reachable:
        return 0.0

    # Latency score: 100 at 0ms, 0 at >= 5000ms
    latency_score = max(0.0, 100.0 - (latency_ms / 50.0))

    # Rate limit score: 100 at 0% utilization, 0 at 100%
    rate_score = 100.0 - rate_limit_pct

    score = (
        40.0 * (1.0 if reachable else 0.0)
        + 20.0 * (latency_score / 100.0)
        + 20.0 * (completeness_pct / 100.0)
        + 20.0 * (rate_score / 100.0)
    )
    return max(0.0, min(100.0, score))


def _derive_status(health_score: float, reachable: bool) -> str:
    if not reachable:
        return "err"
    if health_score >= 70:
        return "ok"
    if health_score >= 40:
        return "warn"
    return "err"


def _pick_probe_data_type(connector: BaseConnector) -> str:
    """Choose a lightweight data_type to probe.

    Prefers the connector's own ``probe_data_type`` property.
    Falls back to a category-based guess if the property returns "default".
    """
    # Prefer the connector's explicit probe type
    explicit = connector.probe_data_type
    if explicit != "default":
        return explicit

    from .base import ConnectorCategory

    cat_map = {
        ConnectorCategory.MARKET_DATA: "ohlcv",
        ConnectorCategory.NEWS: "news",
        ConnectorCategory.SENTIMENT: "sentiment",
        ConnectorCategory.FUNDAMENTALS: "fundamentals",
        ConnectorCategory.MACRO: "series",
        ConnectorCategory.OPTIONS: "options",
        ConnectorCategory.REGULATORY: "filings",
    }
    for cat in connector.categories:
        if cat in cat_map:
            return cat_map[cat]
    return "default"


def _measure_completeness(data: dict[str, Any], data_type: str) -> float:
    """Measure what % of expected fields are present and non-None."""
    expected = _EXPECTED_FIELDS_BY_DATA_TYPE.get(
        data_type, _EXPECTED_FIELDS_BY_DATA_TYPE["default"]
    )
    if not expected:
        return 100.0
    present = sum(1 for f in expected if data.get(f) is not None)
    return (present / len(expected)) * 100.0


def _estimate_freshness(data: dict[str, Any]) -> float | None:
    """Attempt to extract a timestamp from probe data and compute age in seconds."""
    now = time.time()

    # Try common timestamp fields
    for key in ("timestamp", "published_at", "last_updated", "fetched_at"):
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            if val > 1e12:  # milliseconds
                val = val / 1000.0
            if val > 1e9:  # plausible epoch
                return max(0.0, now - val)
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return max(0.0, now - dt.timestamp())
            except (ValueError, TypeError):
                pass

    # Check nested articles for news
    articles = data.get("articles")
    if isinstance(articles, list) and articles:
        first = articles[0]
        if isinstance(first, dict):
            return _estimate_freshness(first)

    return None


class SourceProber:
    """Probes all registered connectors with standardized quality metrics.

    Thread-safe. Caches results for ``cache_ttl_seconds`` to avoid
    hammering external APIs on every frontend poll.
    """

    def __init__(
        self,
        probe_ticker: str = _DEFAULT_PROBE_TICKER,
        cache_ttl_seconds: float = 60.0,
        probe_timeout_seconds: float = 10.0,
    ) -> None:
        self._probe_ticker = probe_ticker
        self._cache_ttl = cache_ttl_seconds
        self._probe_timeout = probe_timeout_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, ProbeResult] = {}
        self._cache_ts: dict[str, float] = {}
        self._history = _ProbeHistory()

    # -- public ---------------------------------------------------------------

    def probe_all(self, force: bool = False) -> list[ProbeResult]:
        """Probe every registered connector. Returns cached if fresh."""
        registry = ConnectorRegistry()
        connectors = registry.list_all()
        results: list[ProbeResult] = []
        for conn in connectors:
            results.append(self.probe_one(conn.name, force=force))
        return results

    def probe_one(self, name: str, force: bool = False) -> ProbeResult:
        """Probe a single connector by name."""
        # Check cache
        if not force:
            with self._lock:
                cached = self._cache.get(name)
                ts = self._cache_ts.get(name, 0)
                if cached and (time.time() - ts) < self._cache_ttl:
                    return cached

        registry = ConnectorRegistry()
        connector = registry.get(name)
        result = self._run_probe(connector)

        # Update cache
        with self._lock:
            self._cache[name] = result
            self._cache_ts[name] = time.time()

        self._history.record_result(result)
        return result

    def get_history(self, name: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent probe history for trend display."""
        return self._history.get_history(name, limit)

    # -- internal -------------------------------------------------------------

    def _run_probe(self, connector: BaseConnector) -> ProbeResult:
        """Execute a single probe against a connector."""
        name = connector.name
        categories = [c.value for c in connector.categories]
        data_type = _pick_probe_data_type(connector)

        reachable = False
        latency_ms = 0.0
        completeness_pct = 0.0
        freshness: float | None = None
        detail = ""

        start = time.monotonic()
        try:
            data = connector.fetch(
                self._probe_ticker, {"data_type": data_type}
            )
            elapsed = time.monotonic() - start
            latency_ms = elapsed * 1000.0
            reachable = True
            completeness_pct = _measure_completeness(data, data_type)
            freshness = _estimate_freshness(data)
            detail = f"OK \u2014 {latency_ms:.0f}ms"
            if isinstance(data, dict):
                # Add some context to detail
                for key in ("total", "total_results", "articles"):
                    if key in data:
                        val = data[key]
                        if isinstance(val, list):
                            detail += f", {len(val)} items"
                        elif isinstance(val, (int, float)):
                            detail += f", {key}={val}"
                        break

        except RateLimitExceededError:
            elapsed = time.monotonic() - start
            latency_ms = elapsed * 1000.0
            detail = "Rate limit exceeded"
            self._history.record_error(name)
        except ConnectorError as exc:
            elapsed = time.monotonic() - start
            latency_ms = elapsed * 1000.0
            detail = f"Error: {exc}"
            self._history.record_error(name)
        except Exception as exc:
            elapsed = time.monotonic() - start
            latency_ms = elapsed * 1000.0
            detail = f"Unexpected: {type(exc).__name__}: {exc}"
            self._history.record_error(name)

        # Rate limit info
        rl = connector.rate_limit_status()
        rate_limit_pct = rl.get("utilization_pct", 0.0)

        error_rate = self._history.error_count_1h(name)
        health_score = _compute_health_score(
            reachable, latency_ms, completeness_pct, rate_limit_pct
        )
        status = _derive_status(health_score, reachable)

        return ProbeResult(
            connector_name=name,
            reachable=reachable,
            latency_ms=latency_ms,
            freshness_seconds=freshness,
            completeness_pct=completeness_pct,
            error_rate_1h=error_rate,
            rate_limit_pct=rate_limit_pct,
            health_score=health_score,
            status=status,
            categories=categories,
            tier=connector.tier,
            last_probed_at=datetime.now(timezone.utc).isoformat(),
            detail=detail,
            sample_ticker=self._probe_ticker,
        )


# Module-level singleton
_prober: SourceProber | None = None
_prober_lock = threading.Lock()


def get_prober() -> SourceProber:
    """Return the module-level SourceProber singleton."""
    global _prober
    with _prober_lock:
        if _prober is None:
            _prober = SourceProber()
        return _prober
