"""Unit tests for batch signals concurrency limiting + force bypass."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from tradingagents.api.main import create_app
from tradingagents.api.routes import signals_v3
from tradingagents.gateway import signals_cache


# ---------------------------------------------------------------------------
# Shared stub decision matching FinalDecision duck-typing expectations
# ---------------------------------------------------------------------------


class _StubSignal:
    value = "BUY"


class _StubTier:
    value = 1


class _StubThesis:
    confidence_score = 72


class _StubAnti:
    confidence_score = 41


class _StubSynth:
    expected_value_pct = 3.2
    disagreement_score = 0.25


class _StubDecision:
    def __init__(self) -> None:
        self.signal = _StubSignal()
        self.tier = _StubTier()
        self.conviction = 68
        self.final_shares = 50
        self.pipeline_latency_ms = 123
        self.thesis = _StubThesis()
        self.antithesis = _StubAnti()
        self.synthesis = _StubSynth()
        self.model_versions = {"thesis": "claude-sonnet-4-5"}
        # Fields that may be populated by a sibling sub-agent
        self.options_direction = None
        self.options_impact = None
        self.realized_vol_20d_pct = None
        self.atr_pct_of_price = None


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path):
    """Redirect L2 to tmp, clear L1, reset semaphore, clean up after."""
    original_db = signals_cache.db_path()
    signals_cache._set_db_path(tmp_path / "signals_cache.db")
    signals_v3._cache.clear()
    signals_v3._SIGNALS_SEMAPHORE = None
    signals_v3._batch_progress.clear()
    yield
    signals_v3._cache.clear()
    signals_v3._SIGNALS_SEMAPHORE = None
    signals_v3._batch_progress.clear()
    signals_cache._set_db_path(original_db)


# ---------------------------------------------------------------------------
# 1. Semaphore limits to 5 concurrent pipeline runs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_semaphore_limits_to_five_concurrent() -> None:
    state = {"in_flight": 0, "peak": 0}
    gate = asyncio.Event()

    async def _runner() -> None:
        def fake_run_analysis(
            ticker: str, date: str | None = None, on_event: Any = None
        ) -> _StubDecision:
            # Blocking counter increment/decrement; runs on worker thread
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
            # Spin briefly to let other workers queue up
            import time

            time.sleep(0.05)
            state["in_flight"] -= 1
            return _StubDecision()

        with patch.object(
            signals_v3, "_load_run_analysis", return_value=fake_run_analysis
        ):
            # 20 distinct tickers, force=True to bypass both cache tiers
            results = await asyncio.gather(
                *(
                    signals_v3._run_one(f"SYM{i}", "2026-04-05", force=True)
                    for i in range(20)
                )
            )
        gate.set()
        assert len(results) == 20

    asyncio.run(_runner())
    assert gate.is_set()
    assert state["peak"] <= 5, f"peak concurrency was {state['peak']}"
    assert state["peak"] >= 1


# ---------------------------------------------------------------------------
# 2. force=1 bypasses both L1 and L2 cache
# ---------------------------------------------------------------------------


async def _async_test_force_bypasses_cache(app) -> None:
    calls = {"n": 0}

    def fake_run_analysis(
        ticker: str, date: str | None = None, on_event: Any = None
    ) -> _StubDecision:
        calls["n"] += 1
        return _StubDecision()

    with patch.object(signals_v3, "_load_run_analysis", return_value=fake_run_analysis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First call: cold, computes
            r1 = await client.get(
                "/api/v3/signals/batch", params={"tickers": "AAPL"}
            )
            # Second call: should be cached (L1)
            r2 = await client.get(
                "/api/v3/signals/batch", params={"tickers": "AAPL"}
            )
            # Third call with force=1: should recompute
            r3 = await client.get(
                "/api/v3/signals/batch",
                params={"tickers": "AAPL", "force": "1"},
            )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200
    assert calls["n"] == 2, f"expected 2 pipeline calls (cold + force), got {calls['n']}"
    assert r1.json()[0]["cached"] is False
    assert r2.json()[0]["cached"] is True
    assert r3.json()[0]["cached"] is False


@pytest.mark.unit
def test_force_bypasses_cache() -> None:
    app = create_app()
    asyncio.run(_async_test_force_bypasses_cache(app))


# ---------------------------------------------------------------------------
# 3. Without force, L1 cache hit returns immediately (no pipeline call)
# ---------------------------------------------------------------------------


async def _async_test_cache_hit_skips_pipeline(app) -> None:
    calls = {"n": 0}

    def fake_run_analysis(
        ticker: str, date: str | None = None, on_event: Any = None
    ) -> _StubDecision:
        calls["n"] += 1
        return _StubDecision()

    with patch.object(signals_v3, "_load_run_analysis", return_value=fake_run_analysis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/v3/signals/batch", params={"tickers": "MSFT"})
            await client.get("/api/v3/signals/batch", params={"tickers": "MSFT"})
            await client.get("/api/v3/signals/batch", params={"tickers": "MSFT"})

    assert calls["n"] == 1


@pytest.mark.unit
def test_cache_hit_skips_pipeline() -> None:
    app = create_app()
    asyncio.run(_async_test_cache_hit_skips_pipeline(app))


# ---------------------------------------------------------------------------
# 4. L2 SQLite hit populates L1 on second process
# ---------------------------------------------------------------------------


async def _async_test_l2_hit_populates_l1(app) -> None:
    calls = {"n": 0}

    def fake_run_analysis(
        ticker: str, date: str | None = None, on_event: Any = None
    ) -> _StubDecision:
        calls["n"] += 1
        return _StubDecision()

    with patch.object(signals_v3, "_load_run_analysis", return_value=fake_run_analysis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get(
                "/api/v3/signals/batch", params={"tickers": "NVDA"}
            )
            assert r1.status_code == 200

            # Clear L1 only; L2 should still have the entry
            signals_v3._cache.clear()

            r2 = await client.get(
                "/api/v3/signals/batch", params={"tickers": "NVDA"}
            )
            assert r2.status_code == 200

    assert calls["n"] == 1, "second call should hit L2, not re-run pipeline"
    assert r2.json()[0]["cached"] is True


@pytest.mark.unit
def test_l2_hit_populates_l1() -> None:
    app = create_app()
    asyncio.run(_async_test_l2_hit_populates_l1(app))
