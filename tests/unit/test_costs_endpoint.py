"""Unit tests for P0-4 cost observability endpoints."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tradingagents.api.models.responses import RuntimeConfig
from tradingagents.api.routes import config as config_module
from tradingagents.gateway.cost_tracker import CostEntry, get_cost_tracker


@pytest.fixture(autouse=True)
def _reset_tracker() -> None:
    tracker = get_cost_tracker()
    tracker.reset()
    yield
    tracker.reset()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a deterministic runtime config."""
    cfg = RuntimeConfig(budget_daily_usd=10.0, budget_per_ticker_usd=2.0)
    monkeypatch.setattr(config_module, "get_runtime_config", lambda: cfg)
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(config_module.router)
    return TestClient(app)


def _entry(
    ticker: str,
    cost: float,
    *,
    agent: str = "thesis",
    model: str = "claude-sonnet-4-5",
) -> CostEntry:
    return CostEntry(
        ticker=ticker,
        agent_name=agent,
        model=model,
        input_tokens=100,
        output_tokens=50,
        cost_usd=cost,
        timestamp=datetime.now(),
    )


@pytest.mark.unit
def test_costs_today_empty(client: TestClient) -> None:
    resp = client.get("/api/config/costs/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_usd"] == 0.0
    assert body["pct_of_daily_budget"] == 0.0
    assert body["budget_daily_usd"] == 10.0
    assert body["budget_per_ticker_usd"] == 2.0
    assert body["by_agent"] == {}
    assert body["by_ticker"] == {}
    assert body["by_model"] == {}
    assert body["call_count"] == 0
    assert body["budget_breached"] is False
    assert "date" in body


@pytest.mark.unit
def test_costs_today_aggregates_all_breakdowns(client: TestClient) -> None:
    tracker = get_cost_tracker()
    # 10 entries across multiple agents/tickers/models.
    tracker.record(_entry("AAPL", 0.10, agent="thesis", model="claude-sonnet-4-5"))
    tracker.record(_entry("AAPL", 0.20, agent="antithesis", model="claude-sonnet-4-5"))
    tracker.record(_entry("AAPL", 0.05, agent="base_rate", model="claude-haiku-4-5-20251001"))
    tracker.record(_entry("AAPL", 0.15, agent="synthesis", model="claude-opus-4-1-20250805"))
    tracker.record(_entry("MSFT", 0.10, agent="thesis", model="claude-sonnet-4-5"))
    tracker.record(_entry("MSFT", 0.20, agent="antithesis", model="claude-sonnet-4-5"))
    tracker.record(_entry("MSFT", 0.05, agent="base_rate", model="claude-haiku-4-5-20251001"))
    tracker.record(_entry("NVDA", 0.30, agent="thesis", model="claude-sonnet-4-5"))
    tracker.record(_entry("NVDA", 0.40, agent="synthesis", model="claude-opus-4-1-20250805"))
    tracker.record(_entry("NVDA", 0.05, agent="base_rate", model="claude-haiku-4-5-20251001"))

    resp = client.get("/api/config/costs/today")
    assert resp.status_code == 200
    body = resp.json()

    assert body["call_count"] == 10
    assert body["total_usd"] == pytest.approx(1.60)
    # 1.60 / 10.0 = 16%
    assert body["pct_of_daily_budget"] == pytest.approx(16.0, abs=0.01)
    assert body["budget_breached"] is False

    # by_agent
    assert body["by_agent"]["thesis"] == pytest.approx(0.50)
    assert body["by_agent"]["antithesis"] == pytest.approx(0.40)
    assert body["by_agent"]["base_rate"] == pytest.approx(0.15)
    assert body["by_agent"]["synthesis"] == pytest.approx(0.55)

    # by_ticker
    assert body["by_ticker"]["AAPL"] == pytest.approx(0.50)
    assert body["by_ticker"]["MSFT"] == pytest.approx(0.35)
    assert body["by_ticker"]["NVDA"] == pytest.approx(0.75)

    # by_model
    assert body["by_model"]["claude-sonnet-4-5"] == pytest.approx(0.90)
    assert body["by_model"]["claude-haiku-4-5-20251001"] == pytest.approx(0.15)
    assert body["by_model"]["claude-opus-4-1-20250805"] == pytest.approx(0.55)


@pytest.mark.unit
def test_costs_today_budget_breached(client: TestClient) -> None:
    tracker = get_cost_tracker()
    # Daily budget is 10.0; push above it.
    tracker.record(_entry("AAPL", 6.0))
    tracker.record(_entry("MSFT", 5.0))

    resp = client.get("/api/config/costs/today")
    body = resp.json()
    assert body["total_usd"] == pytest.approx(11.0)
    assert body["budget_breached"] is True
    assert body["pct_of_daily_budget"] == pytest.approx(110.0)


@pytest.mark.unit
def test_costs_today_per_model_names(client: TestClient) -> None:
    tracker = get_cost_tracker()
    tracker.record(_entry("AAPL", 0.25, model="claude-sonnet-4-5"))
    tracker.record(_entry("AAPL", 0.75, model="claude-opus-4-1-20250805"))

    resp = client.get("/api/config/costs/today")
    body = resp.json()
    assert set(body["by_model"].keys()) == {
        "claude-sonnet-4-5",
        "claude-opus-4-1-20250805",
    }
    assert body["by_model"]["claude-sonnet-4-5"] == pytest.approx(0.25)
    assert body["by_model"]["claude-opus-4-1-20250805"] == pytest.approx(0.75)


@pytest.mark.unit
def test_costs_range_returns_sorted_list(client: TestClient) -> None:
    tracker = get_cost_tracker()
    tracker.record(_entry("AAPL", 0.40))
    tracker.record(_entry("MSFT", 0.60))

    resp = client.get("/api/config/costs/range?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 7
    # Sorted ascending by date.
    dates = [d["date"] for d in body]
    assert dates == sorted(dates)
    # Today's entry (last in list) should have total 1.0.
    assert body[-1]["total_usd"] == pytest.approx(1.0)
    assert body[-1]["call_count"] == 2
    # Earlier days empty.
    for day in body[:-1]:
        assert day["total_usd"] == 0.0
        assert day["call_count"] == 0


@pytest.mark.unit
def test_costs_range_clamps_days(client: TestClient) -> None:
    resp = client.get("/api/config/costs/range?days=500")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 90  # clamped to max

    resp = client.get("/api/config/costs/range?days=0")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1  # clamped to min
