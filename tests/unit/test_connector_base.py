"""Tests for BaseConnector ABC and rate limiting."""

import time
import pytest
from tradingagents.dataflows.connectors.base import (
    BaseConnector,
    ConnectorCategory,
    ConnectorError,
    RateLimitExceededError,
)


class MockConnector(BaseConnector):
    """Concrete test implementation of BaseConnector."""

    @property
    def name(self) -> str:
        return "mock"

    @property
    def tier(self) -> int:
        return 1

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.MARKET_DATA]

    def _fetch_impl(self, ticker, params):
        return {"ticker": ticker, "source": "mock", **params}


class FailingConnector(BaseConnector):
    @property
    def name(self):
        return "failing"

    @property
    def tier(self):
        return 2

    @property
    def categories(self):
        return [ConnectorCategory.NEWS]

    def _fetch_impl(self, ticker, params):
        raise ConnectionError("API unreachable")


class TestBaseConnectorLifecycle:
    def test_initial_state_disconnected(self):
        c = MockConnector()
        assert not c.is_connected

    def test_connect_sets_connected(self):
        c = MockConnector()
        c.connect()
        assert c.is_connected

    def test_disconnect_clears_connected(self):
        c = MockConnector()
        c.connect()
        c.disconnect()
        assert not c.is_connected

    def test_fetch_auto_connects(self):
        c = MockConnector()
        assert not c.is_connected
        result = c.fetch("AAPL")
        assert c.is_connected
        assert result["ticker"] == "AAPL"

    def test_repr(self):
        c = MockConnector()
        assert "mock" in repr(c)
        assert "tier=1" in repr(c)


class TestBaseConnectorFetch:
    def test_fetch_returns_data(self):
        c = MockConnector()
        result = c.fetch("NVDA", {"data_type": "ohlcv"})
        assert result == {"ticker": "NVDA", "source": "mock", "data_type": "ohlcv"}

    def test_fetch_default_params(self):
        c = MockConnector()
        result = c.fetch("TSLA")
        assert result == {"ticker": "TSLA", "source": "mock"}

    def test_fetch_propagates_errors(self):
        c = FailingConnector()
        with pytest.raises(ConnectionError, match="API unreachable"):
            c.fetch("AAPL")


class TestRateLimiting:
    def test_rate_limit_exhaustion(self):
        c = MockConnector(rate_limit=3, rate_period=60.0)
        c.connect()
        c.fetch("A")
        c.fetch("B")
        c.fetch("C")
        with pytest.raises(RateLimitExceededError):
            c.fetch("D")

    def test_rate_limit_refill(self):
        c = MockConnector(rate_limit=2, rate_period=0.1)  # 20 tokens/sec
        c.connect()
        c.fetch("A")
        c.fetch("B")
        with pytest.raises(RateLimitExceededError):
            c.fetch("C")
        time.sleep(0.15)  # Wait for refill
        result = c.fetch("D")  # Should succeed after refill
        assert result["ticker"] == "D"

    def test_rate_limit_status(self):
        c = MockConnector(rate_limit=10, rate_period=60.0)
        c.connect()
        status = c.rate_limit_status()
        assert status["max"] == 10
        assert status["available"] == 10.0
        c.fetch("A")
        status = c.rate_limit_status()
        assert status["available"] < 10


class TestHealthCheck:
    def test_healthy_connector(self):
        c = MockConnector()
        assert c.health_check() is True

    def test_failing_health_check(self):
        c = FailingConnector()
        # health_check calls connect which succeeds for FailingConnector
        assert c.health_check() is True


class TestConnectorCategory:
    def test_category_values(self):
        assert ConnectorCategory.MARKET_DATA == "market_data"
        assert ConnectorCategory.DIVERGENCE == "divergence"
        assert ConnectorCategory.MACRO == "macro"
