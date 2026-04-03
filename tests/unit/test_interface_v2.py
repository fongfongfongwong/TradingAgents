"""Tests for interface_v2 (route_to_connector) and migration (LegacyAdapter)."""

from __future__ import annotations

import pytest
from typing import Any
from unittest.mock import patch, MagicMock

from tradingagents.dataflows.connectors.base import BaseConnector, ConnectorCategory
from tradingagents.dataflows.connectors.registry import ConnectorRegistry
from tradingagents.dataflows.interface_v2 import route_to_connector, METHOD_CONNECTOR_MAP
from tradingagents.dataflows.migration import LegacyAdapter, create_legacy_adapters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubConnector(BaseConnector):
    """Minimal concrete connector for testing."""

    def __init__(self, name: str = "finnhub", tier: int = 1, categories=None):
        super().__init__(rate_limit=100)
        self._name = name
        self._tier = tier
        self._categories = categories or [ConnectorCategory.NEWS]
        self._last_fetch: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def categories(self) -> list[ConnectorCategory]:
        return list(self._categories)

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        self._last_fetch = {"ticker": ticker, "params": params}
        return {"data": f"stub-{self._name}-{ticker}", "source": self._name}


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the ConnectorRegistry singleton before and after each test."""
    ConnectorRegistry._reset_singleton()
    yield
    ConnectorRegistry._reset_singleton()


# ===================================================================
# TASK 1 tests: route_to_connector
# ===================================================================

class TestRouteToConnectorFallback:
    """When no connectors are registered, behaviour == route_to_vendor."""

    @patch("tradingagents.dataflows.interface_v2.route_to_vendor")
    def test_fallback_when_no_connectors(self, mock_rtv):
        """route_to_connector delegates to route_to_vendor when registry is empty."""
        mock_rtv.return_value = "vendor-result"
        result = route_to_connector("get_stock_data", "AAPL", "2024-01-01", "2024-06-01")
        mock_rtv.assert_called_once_with("get_stock_data", "AAPL", "2024-01-01", "2024-06-01")
        assert result == "vendor-result"

    @patch("tradingagents.dataflows.interface_v2.route_to_vendor")
    def test_fallback_for_unknown_method(self, mock_rtv):
        """Methods not in METHOD_CONNECTOR_MAP fall back immediately."""
        mock_rtv.return_value = "fallback"
        result = route_to_connector("some_unknown_method", "AAPL")
        mock_rtv.assert_called_once_with("some_unknown_method", "AAPL")
        assert result == "fallback"

    @patch("tradingagents.dataflows.interface_v2.route_to_vendor")
    def test_fallback_when_wrong_connector_registered(self, mock_rtv):
        """Connector registered under different name does not intercept the call."""
        mock_rtv.return_value = "vendor-data"
        registry = ConnectorRegistry()
        registry.register(_StubConnector(name="other_connector"))

        result = route_to_connector("get_news", "AAPL")
        # "get_news" maps to connector name "finnhub", not "other_connector"
        mock_rtv.assert_called_once()
        assert result == "vendor-data"


class TestRouteToConnectorUsesConnector:
    """When a matching connector is registered, it is used."""

    def test_connector_serves_request(self):
        """route_to_connector uses the connector when it is registered."""
        stub = _StubConnector(name="finnhub")
        registry = ConnectorRegistry()
        registry.register(stub)

        result = route_to_connector("get_news", "TSLA")
        assert result["source"] == "finnhub"
        assert "TSLA" in result["data"]

    def test_connector_receives_correct_params(self):
        """Connector fetch receives data_type from METHOD_CONNECTOR_MAP."""
        stub = _StubConnector(name="finnhub")
        registry = ConnectorRegistry()
        registry.register(stub)

        route_to_connector("get_news", "MSFT")
        assert stub._last_fetch is not None
        assert stub._last_fetch["ticker"] == "MSFT"
        assert stub._last_fetch["params"]["data_type"] == "news"

    def test_connector_with_kwargs(self):
        """kwargs are forwarded through to the connector."""
        stub = _StubConnector(name="yfinance", categories=[ConnectorCategory.MARKET_DATA])
        registry = ConnectorRegistry()
        registry.register(stub)

        route_to_connector("get_stock_data", "GOOG", window=30)
        assert stub._last_fetch["params"]["window"] == 30

    def test_method_connector_map_completeness(self):
        """Every entry in METHOD_CONNECTOR_MAP has a valid structure."""
        for method, (connector_name, data_type) in METHOD_CONNECTOR_MAP.items():
            assert isinstance(connector_name, str)
            assert isinstance(data_type, str)
            assert len(connector_name) > 0
            assert len(data_type) > 0


# ===================================================================
# TASK 2 tests: LegacyAdapter
# ===================================================================

class TestLegacyAdapter:
    """LegacyAdapter wraps plain callables as a connector."""

    def test_wraps_function_returning_string(self):
        """String return value is normalised to dict."""
        def fake_fetch(ticker):
            return f"data-for-{ticker}"

        adapter = LegacyAdapter(
            adapter_name="test_adapter",
            methods={"my_method": fake_fetch},
        )
        result = adapter.fetch("AAPL", {"data_type": "my_method", "method_name": "my_method"})
        assert result["data"] == "data-for-AAPL"
        assert result["source"] == "test_adapter"

    def test_wraps_function_returning_dict(self):
        """Dict return value is passed through with source added."""
        def fake_fetch(ticker):
            return {"price": 150.0}

        adapter = LegacyAdapter(
            adapter_name="test_adapter",
            methods={"price": fake_fetch},
        )
        result = adapter.fetch("AAPL", {"data_type": "price", "method_name": "price"})
        assert result["price"] == 150.0
        assert result["source"] == "test_adapter"

    def test_missing_method_raises(self):
        """Accessing a non-existent method raises KeyError."""
        adapter = LegacyAdapter(adapter_name="empty", methods={})
        with pytest.raises(KeyError, match="no method"):
            adapter.fetch("AAPL", {"data_type": "missing", "method_name": "missing"})

    def test_method_names_property(self):
        """method_names returns all registered method names."""
        adapter = LegacyAdapter(
            adapter_name="multi",
            methods={"a": lambda t: t, "b": lambda t: t},
        )
        assert sorted(adapter.method_names) == ["a", "b"]

    def test_adapter_properties(self):
        """name, tier, and categories are set correctly."""
        adapter = LegacyAdapter(
            adapter_name="my_conn",
            methods={},
            adapter_tier=2,
            adapter_categories=[ConnectorCategory.NEWS, ConnectorCategory.SENTIMENT],
        )
        assert adapter.name == "my_conn"
        assert adapter.tier == 2
        assert ConnectorCategory.NEWS in adapter.categories

    def test_extra_args_forwarded(self):
        """Extra positional args are forwarded via params['extra_args']."""
        calls = []

        def recorder(ticker, start, end):
            calls.append((ticker, start, end))
            return "ok"

        adapter = LegacyAdapter(
            adapter_name="rec",
            methods={"m": recorder},
        )
        adapter.fetch("SPY", {
            "data_type": "m",
            "method_name": "m",
            "extra_args": ["2024-01-01", "2024-06-01"],
        })
        assert calls == [("SPY", "2024-01-01", "2024-06-01")]


class TestCreateLegacyAdapters:
    """create_legacy_adapters builds adapters from VENDOR_METHODS."""

    def test_creates_adapters_for_known_vendors(self):
        """Should produce at least yfinance and alpha_vantage adapters."""
        adapters = create_legacy_adapters()
        assert "yfinance" in adapters
        assert "alpha_vantage" in adapters

    def test_adapters_have_methods(self):
        """Each adapter should expose at least one method."""
        adapters = create_legacy_adapters()
        for vendor_name, adapter in adapters.items():
            assert len(adapter.method_names) > 0, f"{vendor_name} adapter has no methods"
