"""Unit tests for G4 module-level cost tracker + budget enforcement."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest

from tradingagents.api.routes import config as config_module
from tradingagents.api.models.responses import RuntimeConfig
from tradingagents.gateway.cost_tracker import (
    BudgetExceededError,
    CostEntry,
    MODEL_PRICING_USD_PER_1M,
    compute_cost,
    get_cost_tracker,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tracker() -> None:
    """Ensure each test starts with a clean tracker."""
    tracker = get_cost_tracker()
    tracker.reset()
    yield
    tracker.reset()


@pytest.fixture()
def tight_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a tiny budget regardless of what lives on disk."""
    tiny = RuntimeConfig(budget_daily_usd=1.0, budget_per_ticker_usd=0.50)
    monkeypatch.setattr(config_module, "get_runtime_config", lambda: tiny)


@pytest.fixture()
def generous_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a generous budget so check_budget never trips."""
    big = RuntimeConfig(budget_daily_usd=10_000.0, budget_per_ticker_usd=1_000.0)
    monkeypatch.setattr(config_module, "get_runtime_config", lambda: big)


# ---------------------------------------------------------------------------
# compute_cost
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_cost_sonnet() -> None:
    # 1M input @ $3, 1M output @ $15 = $18 for 1M/1M.
    cost = compute_cost("claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


@pytest.mark.unit
def test_compute_cost_opus() -> None:
    # 1M input @ $15, 1M output @ $75 = $90.
    cost = compute_cost("claude-opus-4-1-20250805", 1_000_000, 1_000_000)
    assert cost == pytest.approx(90.0)


@pytest.mark.unit
def test_compute_cost_haiku_small_tokens() -> None:
    # 2000 input @ $1/1M + 500 output @ $5/1M = 0.002 + 0.0025 = 0.0045
    cost = compute_cost("claude-haiku-4-5-20251001", 2000, 500)
    assert cost == pytest.approx(0.0045)


@pytest.mark.unit
def test_compute_cost_unknown_model_returns_zero() -> None:
    cost = compute_cost("some-random-model-v99", 1_000_000, 1_000_000)
    assert cost == 0.0
    assert "some-random-model-v99" not in MODEL_PRICING_USD_PER_1M


# ---------------------------------------------------------------------------
# record / totals
# ---------------------------------------------------------------------------


def _entry(
    ticker: str,
    cost: float,
    *,
    agent: str = "thesis",
    model: str = "claude-sonnet-4-5",
    timestamp: datetime | None = None,
) -> CostEntry:
    return CostEntry(
        ticker=ticker,
        agent_name=agent,
        model=model,
        input_tokens=10,
        output_tokens=10,
        cost_usd=cost,
        timestamp=timestamp or datetime.now(),
    )


@pytest.mark.unit
def test_record_accumulates_daily_total() -> None:
    tracker = get_cost_tracker()
    tracker.record(_entry("AAPL", 0.10))
    tracker.record(_entry("AAPL", 0.20))
    tracker.record(_entry("MSFT", 0.05))
    assert tracker.daily_total_usd() == pytest.approx(0.35)
    assert tracker.ticker_total_usd("AAPL") == pytest.approx(0.30)
    assert tracker.ticker_total_usd("MSFT") == pytest.approx(0.05)
    assert tracker.ticker_total_usd("NVDA") == pytest.approx(0.0)


@pytest.mark.unit
def test_daily_total_scoped_by_date() -> None:
    tracker = get_cost_tracker()
    yesterday = datetime.now() - timedelta(days=1)
    tracker.record(_entry("AAPL", 99.0, timestamp=yesterday))
    tracker.record(_entry("AAPL", 0.25))
    # Today's totals must not include yesterday's entry.
    assert tracker.daily_total_usd() == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_budget_passes_when_under(
    generous_budget: None,  # noqa: ARG001
) -> None:
    tracker = get_cost_tracker()
    tracker.record(_entry("AAPL", 5.0))
    # Must not raise.
    tracker.check_budget("AAPL")


@pytest.mark.unit
def test_check_budget_raises_when_daily_exceeded(
    tight_budget: None,  # noqa: ARG001
) -> None:
    tracker = get_cost_tracker()
    tracker.record(_entry("AAPL", 0.40))
    tracker.record(_entry("MSFT", 0.40))
    tracker.record(_entry("NVDA", 0.30))  # daily = 1.10 >= 1.0
    with pytest.raises(BudgetExceededError, match="daily budget"):
        tracker.check_budget("TSLA")


@pytest.mark.unit
def test_check_budget_raises_when_per_ticker_exceeded(
    tight_budget: None,  # noqa: ARG001
) -> None:
    tracker = get_cost_tracker()
    tracker.record(_entry("AAPL", 0.60))  # per-ticker limit is 0.50
    with pytest.raises(BudgetExceededError, match="per-ticker budget"):
        tracker.check_budget("AAPL")
    # Other tickers still allowed.
    tracker.check_budget("MSFT")


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_concurrent_record_is_thread_safe() -> None:
    tracker = get_cost_tracker()
    per_thread = 200
    num_threads = 10

    def worker(i: int) -> None:
        for _ in range(per_thread):
            tracker.record(_entry(f"T{i}", 0.01))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = per_thread * num_threads * 0.01
    assert tracker.daily_total_usd() == pytest.approx(expected)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reset_clears_all_state() -> None:
    tracker = get_cost_tracker()
    tracker.record(_entry("AAPL", 0.10))
    tracker.record(_entry("MSFT", 0.20))
    tracker.reset()
    assert tracker.daily_total_usd() == 0.0
    assert tracker.ticker_total_usd("AAPL") == 0.0
    assert tracker.ticker_total_usd("MSFT") == 0.0
