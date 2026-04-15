"""Base connector ABC with built-in rate limiting and lifecycle management."""

from __future__ import annotations

import logging
import time
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Base exception for connector errors."""


class RateLimitExceededError(ConnectorError):
    """Raised when a connector's rate limit is exhausted."""


class ConnectorCategory(str, Enum):
    MARKET_DATA = "market_data"
    NEWS = "news"
    SENTIMENT = "sentiment"
    FUNDAMENTALS = "fundamentals"
    MACRO = "macro"
    REGULATORY = "regulatory"
    ALTERNATIVE = "alternative"
    DIVERGENCE = "divergence"
    OPTIONS = "options"


class _TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, max_tokens: int, refill_rate: float):
        self._max_tokens = max_tokens
        self._tokens = float(max_tokens)
        self._refill_rate = refill_rate  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._max_tokens,
                self._tokens + elapsed * self._refill_rate,
            )
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            return min(
                self._max_tokens,
                self._tokens + elapsed * self._refill_rate,
            )

    @property
    def max_tokens(self) -> int:
        return self._max_tokens


class BaseConnector(ABC):
    """Abstract base class for all data source connectors.

    Subclasses implement ``_fetch_impl`` and the abstract properties.
    The public ``fetch`` method handles rate limiting and connection checks.
    """

    def __init__(
        self,
        rate_limit: int = 60,
        rate_period: float = 60.0,
    ):
        self._connected = False
        self._bucket = _TokenBucket(
            max_tokens=rate_limit,
            refill_rate=rate_limit / rate_period,
        )

    # -- abstract properties --------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this connector (e.g. 'finnhub')."""

    @property
    @abstractmethod
    def tier(self) -> int:
        """Pricing tier: 1 (free) … 5 (enterprise)."""

    @property
    @abstractmethod
    def categories(self) -> list[ConnectorCategory]:
        """Data categories this connector provides."""

    # -- lifecycle ------------------------------------------------------------

    def connect(self) -> None:
        """Establish connection / validate credentials."""
        self._connected = True
        logger.info("Connector '%s' connected", self.name)

    def disconnect(self) -> None:
        """Release resources."""
        self._connected = False
        logger.info("Connector '%s' disconnected", self.name)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -- public API -----------------------------------------------------------

    def fetch(self, ticker: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch data with rate-limit and connection guards.

        Delegates to ``_fetch_impl`` after checks pass.
        """
        if not self._connected:
            self.connect()

        if not self._bucket.consume():
            raise RateLimitExceededError(
                f"Connector '{self.name}' rate limit exceeded "
                f"({self._bucket.max_tokens} calls/period)"
            )

        params = params or {}
        try:
            return self._fetch_impl(ticker, params)
        except Exception:
            logger.exception("Connector '%s' fetch failed for %s", self.name, ticker)
            raise

    @abstractmethod
    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Vendor-specific fetch logic. Subclasses must implement."""

    # -- probe support --------------------------------------------------------

    @property
    def probe_data_type(self) -> str:
        """Return the best data_type string to use for health probing.

        Subclasses can override this to pick a lightweight, always-available
        type that doesn't require special parameters.  The default returns
        ``"default"`` which the probe engine will use as-is.
        """
        return "default"

    # -- health / status ------------------------------------------------------

    def health_check(self) -> bool:
        """Return True if the connector can serve requests."""
        try:
            if not self._connected:
                self.connect()
            return self._connected
        except Exception:
            return False

    def rate_limit_status(self) -> dict[str, Any]:
        """Current rate-limit state."""
        return {
            "available": round(self._bucket.available, 1),
            "max": self._bucket.max_tokens,
            "utilization_pct": round(
                (1 - self._bucket.available / self._bucket.max_tokens) * 100, 1
            ),
        }

    # -- dunder ---------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} name={self.name!r} "
            f"tier={self.tier} connected={self._connected}>"
        )
