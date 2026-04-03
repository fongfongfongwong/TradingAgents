"""Thread-safe singleton registry for data source connectors."""

from __future__ import annotations

import logging
import threading
from typing import Iterator

from .base import BaseConnector, ConnectorCategory

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Singleton registry that manages all data-source connectors.

    Usage::

        registry = ConnectorRegistry()
        registry.register(FinnhubConnector())
        connector = registry.get("finnhub")
        data = connector.fetch("AAPL", {"data_type": "quotes"})
    """

    _instance: ConnectorRegistry | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ConnectorRegistry:
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._connectors: dict[str, BaseConnector] = {}
                inst._registry_lock = threading.Lock()
                cls._instance = inst
            return cls._instance

    # -- CRUD -----------------------------------------------------------------

    def register(self, connector: BaseConnector) -> None:
        """Register a connector. Raises if name already taken."""
        with self._registry_lock:
            if connector.name in self._connectors:
                raise ValueError(
                    f"Connector '{connector.name}' is already registered"
                )
            if not 1 <= connector.tier <= 5:
                raise ValueError(
                    f"Connector '{connector.name}' has invalid tier {connector.tier} "
                    "(must be 1-5)"
                )
            self._connectors[connector.name] = connector
            logger.info(
                "Registered connector '%s' (tier %d)", connector.name, connector.tier
            )

    def unregister(self, name: str) -> None:
        """Remove a connector by name."""
        with self._registry_lock:
            connector = self._connectors.pop(name, None)
            if connector is None:
                raise KeyError(f"Connector '{name}' not found in registry")
            connector.disconnect()
            logger.info("Unregistered connector '%s'", name)

    def get(self, name: str) -> BaseConnector:
        """Retrieve a connector by name."""
        with self._registry_lock:
            if name not in self._connectors:
                raise KeyError(
                    f"Connector '{name}' not found. "
                    f"Available: {list(self._connectors.keys())}"
                )
            return self._connectors[name]

    # -- queries --------------------------------------------------------------

    def list_by_tier(self, tier: int) -> list[BaseConnector]:
        """Return all connectors at a given pricing tier."""
        with self._registry_lock:
            return [c for c in self._connectors.values() if c.tier == tier]

    def list_by_category(self, category: ConnectorCategory | str) -> list[BaseConnector]:
        """Return all connectors that provide data for *category*."""
        if isinstance(category, str):
            category = ConnectorCategory(category)
        with self._registry_lock:
            return [
                c
                for c in self._connectors.values()
                if category in c.categories
            ]

    def list_all(self) -> list[BaseConnector]:
        """Return all registered connectors."""
        with self._registry_lock:
            return list(self._connectors.values())

    @property
    def names(self) -> list[str]:
        with self._registry_lock:
            return list(self._connectors.keys())

    # -- operations -----------------------------------------------------------

    def health_check_all(self) -> dict[str, bool]:
        """Run health checks on every registered connector."""
        results: dict[str, bool] = {}
        with self._registry_lock:
            connectors = list(self._connectors.values())
        for conn in connectors:
            try:
                results[conn.name] = conn.health_check()
            except Exception:
                results[conn.name] = False
        return results

    def connect_all(self) -> None:
        """Connect all registered connectors."""
        with self._registry_lock:
            connectors = list(self._connectors.values())
        for conn in connectors:
            try:
                conn.connect()
            except Exception:
                logger.warning("Failed to connect '%s'", conn.name)

    def disconnect_all(self) -> None:
        """Disconnect all registered connectors."""
        with self._registry_lock:
            connectors = list(self._connectors.values())
        for conn in connectors:
            try:
                conn.disconnect()
            except Exception:
                logger.warning("Failed to disconnect '%s'", conn.name)

    def clear(self) -> None:
        """Remove all connectors (useful for testing)."""
        self.disconnect_all()
        with self._registry_lock:
            self._connectors.clear()

    # -- dunder ---------------------------------------------------------------

    def __len__(self) -> int:
        with self._registry_lock:
            return len(self._connectors)

    def __contains__(self, name: str) -> bool:
        with self._registry_lock:
            return name in self._connectors

    def __iter__(self) -> Iterator[BaseConnector]:
        with self._registry_lock:
            return iter(list(self._connectors.values()))

    def __repr__(self) -> str:
        return f"<ConnectorRegistry connectors={self.names}>"

    @classmethod
    def _reset_singleton(cls) -> None:
        """Reset singleton (testing only)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.clear()
            cls._instance = None
