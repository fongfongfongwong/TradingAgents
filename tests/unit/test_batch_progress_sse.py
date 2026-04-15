"""Unit tests for POST /signals/batch/start and the SSE progress stream."""

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


class _StubSignal:
    value = "BUY"


class _StubTier:
    value = 1


class _StubThesis:
    confidence_score = 70


class _StubAnti:
    confidence_score = 40


class _StubSynth:
    expected_value_pct = 2.5
    disagreement_score = 0.3


class _StubDecision:
    def __init__(self) -> None:
        self.signal = _StubSignal()
        self.tier = _StubTier()
        self.conviction = 65
        self.final_shares = 25
        self.pipeline_latency_ms = 100
        self.thesis = _StubThesis()
        self.antithesis = _StubAnti()
        self.synthesis = _StubSynth()
        self.model_versions = {"thesis": "claude-sonnet-4-5"}
        self.options_direction = None
        self.options_impact = None
        self.realized_vol_20d_pct = None
        self.atr_pct_of_price = None


def _fake_run_analysis(
    ticker: str, date: str | None = None, on_event: Any = None
) -> _StubDecision:
    return _StubDecision()


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path):
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


@pytest.fixture()
def app():
    return create_app()


# ---------------------------------------------------------------------------
# 1. POST /signals/batch/start returns a batch_id
# ---------------------------------------------------------------------------


async def _async_test_start_batch_returns_id(app) -> None:
    with patch.object(signals_v3, "_load_run_analysis", return_value=_fake_run_analysis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v3/signals/batch/start",
                json={"tickers": ["AAPL", "MSFT", "NVDA"], "force": False},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert "batch_id" in body
    assert len(body["batch_id"]) >= 8
    assert body["total"] == 3


@pytest.mark.unit
def test_start_batch_returns_id(app) -> None:
    asyncio.run(_async_test_start_batch_returns_id(app))


# ---------------------------------------------------------------------------
# 2. Unknown batch_id returns 404 on both status + stream
# ---------------------------------------------------------------------------


async def _async_test_unknown_batch_404(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/api/v3/signals/batch/deadbeef0000/status")
        r2 = await client.get("/api/v3/signals/batch/deadbeef0000/stream")
    assert r1.status_code == 404
    assert r2.status_code == 404


@pytest.mark.unit
def test_unknown_batch_404(app) -> None:
    asyncio.run(_async_test_unknown_batch_404(app))


# ---------------------------------------------------------------------------
# 3. Active batch status endpoint reports running
# ---------------------------------------------------------------------------


async def _async_test_batch_status_running_then_complete(app) -> None:
    release = asyncio.Event()

    async def slow_run_one(ticker: str, analysis_date: str, *, force: bool = False, on_event=None):
        await release.wait()
        from tradingagents.api.models.responses import BatchSignalItem

        return BatchSignalItem(
            ticker=ticker,
            signal="BUY",
            conviction=60,
            tier=1,
            expected_value_pct=2.0,
            thesis_confidence=70.0,
            antithesis_confidence=40.0,
            disagreement_score=0.3,
            final_shares=10,
            pipeline_latency_ms=10,
            data_gaps=[],
            cached=False,
            cost_usd=0.01,
            models_used=[],
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(signals_v3, "_run_one", side_effect=slow_run_one):
            start = await client.post(
                "/api/v3/signals/batch/start",
                json={"tickers": ["AAPL", "MSFT"]},
            )
            assert start.status_code == 200
            batch_id = start.json()["batch_id"]

            # Poll while the workers are blocked on `release`
            await asyncio.sleep(0.1)
            running = await client.get(
                f"/api/v3/signals/batch/{batch_id}/status"
            )
            assert running.status_code == 200
            rbody = running.json()
            assert rbody["status"] == "running"
            assert rbody["total"] == 2

            # Let workers finish
            release.set()

            # Wait for completion (bounded)
            for _ in range(50):
                status = await client.get(
                    f"/api/v3/signals/batch/{batch_id}/status"
                )
                if status.json()["status"] == "complete":
                    break
                await asyncio.sleep(0.05)

            final = await client.get(
                f"/api/v3/signals/batch/{batch_id}/status"
            )
            fbody = final.json()
            assert fbody["status"] == "complete"
            assert fbody["completed"] == 2
            assert fbody["failed"] == 0
            assert len(fbody["results"]) == 2


@pytest.mark.unit
def test_batch_status_running_then_complete(app) -> None:
    asyncio.run(_async_test_batch_status_running_then_complete(app))


# ---------------------------------------------------------------------------
# 4. Empty ticker list yields 422
# ---------------------------------------------------------------------------


async def _async_test_start_batch_rejects_empty(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v3/signals/batch/start", json={"tickers": []}
        )
    assert r.status_code == 422


@pytest.mark.unit
def test_start_batch_rejects_empty(app) -> None:
    asyncio.run(_async_test_start_batch_rejects_empty(app))
