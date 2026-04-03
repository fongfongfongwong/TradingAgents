"""Tests for ConnectorRegistry singleton."""

import pytest
from tradingagents.dataflows.connectors.base import (
    BaseConnector,
    ConnectorCategory,
)
from tradingagents.dataflows.connectors.registry import ConnectorRegistry


class FakeConnector(BaseConnector):
    def __init__(self, name_: str, tier_: int, cats: list[ConnectorCategory], **kwargs):
        super().__init__(**kwargs)
        self._name = name_
        self._tier = tier_
        self._cats = cats

    @property
    def name(self):
        return self._name

    @property
    def tier(self):
        return self._tier

    @property
    def categories(self):
        return self._cats

    def _fetch_impl(self, ticker, params):
        return {"ticker": ticker, "source": self._name}


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset the singleton before each test."""
    ConnectorRegistry._reset_singleton()
    yield
    ConnectorRegistry._reset_singleton()


class TestRegistrySingleton:
    def test_same_instance(self):
        r1 = ConnectorRegistry()
        r2 = ConnectorRegistry()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        r1 = ConnectorRegistry()
        ConnectorRegistry._reset_singleton()
        r2 = ConnectorRegistry()
        assert r1 is not r2


class TestRegisterUnregister:
    def test_register(self):
        reg = ConnectorRegistry()
        c = FakeConnector("test", 1, [ConnectorCategory.MARKET_DATA])
        reg.register(c)
        assert "test" in reg
        assert len(reg) == 1

    def test_register_duplicate_raises(self):
        reg = ConnectorRegistry()
        c1 = FakeConnector("dup", 1, [ConnectorCategory.NEWS])
        c2 = FakeConnector("dup", 2, [ConnectorCategory.SENTIMENT])
        reg.register(c1)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(c2)

    def test_register_invalid_tier_raises(self):
        reg = ConnectorRegistry()
        c = FakeConnector("bad", 0, [ConnectorCategory.MARKET_DATA])
        with pytest.raises(ValueError, match="invalid tier"):
            reg.register(c)

    def test_unregister(self):
        reg = ConnectorRegistry()
        c = FakeConnector("rem", 1, [ConnectorCategory.MACRO])
        reg.register(c)
        reg.unregister("rem")
        assert "rem" not in reg
        assert len(reg) == 0

    def test_unregister_missing_raises(self):
        reg = ConnectorRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.unregister("ghost")


class TestGet:
    def test_get_existing(self):
        reg = ConnectorRegistry()
        c = FakeConnector("finn", 1, [ConnectorCategory.MARKET_DATA])
        reg.register(c)
        assert reg.get("finn") is c

    def test_get_missing_raises(self):
        reg = ConnectorRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.get("nope")


class TestFiltering:
    @pytest.fixture
    def populated_registry(self):
        reg = ConnectorRegistry()
        reg.register(FakeConnector("free1", 1, [ConnectorCategory.MARKET_DATA]))
        reg.register(FakeConnector("free2", 1, [ConnectorCategory.NEWS, ConnectorCategory.SENTIMENT]))
        reg.register(FakeConnector("paid1", 2, [ConnectorCategory.MARKET_DATA]))
        reg.register(FakeConnector("ent1", 4, [ConnectorCategory.FUNDAMENTALS]))
        return reg

    def test_list_by_tier(self, populated_registry):
        tier1 = populated_registry.list_by_tier(1)
        assert len(tier1) == 2
        assert all(c.tier == 1 for c in tier1)

    def test_list_by_tier_empty(self, populated_registry):
        assert populated_registry.list_by_tier(5) == []

    def test_list_by_category(self, populated_registry):
        market = populated_registry.list_by_category(ConnectorCategory.MARKET_DATA)
        assert len(market) == 2

    def test_list_by_category_string(self, populated_registry):
        news = populated_registry.list_by_category("news")
        assert len(news) == 1
        assert news[0].name == "free2"

    def test_list_all(self, populated_registry):
        assert len(populated_registry.list_all()) == 4

    def test_names(self, populated_registry):
        assert set(populated_registry.names) == {"free1", "free2", "paid1", "ent1"}


class TestOperations:
    def test_health_check_all(self):
        reg = ConnectorRegistry()
        reg.register(FakeConnector("h1", 1, [ConnectorCategory.MARKET_DATA]))
        reg.register(FakeConnector("h2", 1, [ConnectorCategory.NEWS]))
        results = reg.health_check_all()
        assert results == {"h1": True, "h2": True}

    def test_clear(self):
        reg = ConnectorRegistry()
        reg.register(FakeConnector("c1", 1, [ConnectorCategory.MACRO]))
        reg.register(FakeConnector("c2", 2, [ConnectorCategory.NEWS]))
        reg.clear()
        assert len(reg) == 0

    def test_iter(self):
        reg = ConnectorRegistry()
        reg.register(FakeConnector("i1", 1, [ConnectorCategory.MARKET_DATA]))
        reg.register(FakeConnector("i2", 1, [ConnectorCategory.NEWS]))
        names = [c.name for c in reg]
        assert set(names) == {"i1", "i2"}
