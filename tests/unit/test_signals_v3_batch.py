"""Unit tests for GET /api/v3/signals/batch.

Covers:
  * Route registration on the FastAPI app
  * Batch execution for multiple tickers with the v3 pipeline mocked
  * Error isolation: one ticker crashing does not break the batch
  * In-memory 10-minute TTL cache (``cached=True`` on second call)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from tradingagents.api.main import create_app
from tradingagents.api.routes import signals_v3
from tradingagents.schemas.v3 import (
    AntithesisOutput,
    BaseRateOutput,
    Catalyst,
    FinalDecision,
    MustBeTrue,
    Regime,
    Scenario,
    ScreeningResult,
    Signal,
    SynthesisOutput,
    ThesisOutput,
    Tier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_thesis(ticker: str) -> ThesisOutput:
    return ThesisOutput(
        ticker=ticker,
        valuation_gap_summary="fair",
        momentum_aligned=True,
        momentum_detail="positive",
        catalysts=[Catalyst(event="e", mechanism="m", magnitude_estimate="1%")],
        contrarian_signals=[],
        must_be_true=[
            MustBeTrue(condition=f"c{i}", probability=0.6, evidence="ev", falsifiable_by="x")
            for i in range(3)
        ],
        weakest_link="none",
        confidence_rationale="ok",
        confidence_score=72,
    )


def _make_antithesis(ticker: str) -> AntithesisOutput:
    return AntithesisOutput(
        ticker=ticker,
        overvaluation_summary="some",
        deterioration_present=False,
        deterioration_detail="none",
        risk_catalysts=[Catalyst(event="r", mechanism="m", magnitude_estimate="1%")],
        crowding_fragility=[],
        must_be_true=[
            MustBeTrue(condition=f"c{i}", probability=0.4, evidence="ev", falsifiable_by="x")
            for i in range(3)
        ],
        weakest_link="none",
        confidence_rationale="ok",
        confidence_score=41,
    )


def _make_base_rate(ticker: str) -> BaseRateOutput:
    return BaseRateOutput(
        ticker=ticker,
        expected_move_pct=2.0,
        upside_pct=4.0,
        downside_pct=-3.0,
        regime=Regime.RISK_ON,
        historical_analog="typical",
        base_rate_probability_up=0.55,
        volatility_forecast_20d=0.18,
    )


def _make_synthesis(ticker: str) -> SynthesisOutput:
    return SynthesisOutput(
        ticker=ticker,
        date="2026-04-05",
        signal=Signal.BUY,
        conviction=68,
        scenarios=[
            Scenario(probability=0.6, target_price=210.0, return_pct=5.0, rationale="bull"),
            Scenario(probability=0.4, target_price=195.0, return_pct=-2.0, rationale="bear"),
        ],
        expected_value_pct=3.2,
        disagreement_score=0.25,
        decision_rationale="EV positive",
        key_evidence=["e1", "e2"],
    )


def _make_final_decision(ticker: str) -> FinalDecision:
    return FinalDecision(
        ticker=ticker,
        date="2026-04-05",
        snapshot_id=f"snap-{ticker}",
        tier=Tier.FULL,
        screening=ScreeningResult(
            ticker=ticker,
            tier=Tier.FULL,
            trigger_reasons=["high_volume"],
            factor_score=0.25,
        ),
        thesis=_make_thesis(ticker),
        antithesis=_make_antithesis(ticker),
        base_rate=_make_base_rate(ticker),
        synthesis=_make_synthesis(ticker),
        risk=None,
        factor_baseline_score=0.25,
        signal=Signal.BUY,
        conviction=68,
        final_shares=50,
        pipeline_latency_ms=1234,
    )


def _fake_run_analysis(
    ticker: str,
    date: str | None = None,
    on_event: Any = None,
) -> FinalDecision:
    if ticker == "BROKEN":
        raise RuntimeError("mocked data gateway outage")
    return _make_final_decision(ticker)


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe the module-level L1 TTL cache and stub out L2 between tests.

    The L2 SQLite cache persists at ``~/.tradingagents/signals_cache.db`` and
    would otherwise leak state across unrelated test runs. We neutralize it
    with monkeypatches so these tests remain hermetic.
    """
    signals_v3._cache.clear()
    monkeypatch.setattr(signals_v3, "_l2_get", lambda *a, **kw: None)
    monkeypatch.setattr(signals_v3, "_l2_put", lambda *a, **kw: None)
    yield
    signals_v3._cache.clear()


@pytest.fixture()
def app():
    return create_app()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_router_registers_batch_route() -> None:
    paths = [r.path for r in signals_v3.router.routes]
    assert "/api/v3/signals/batch" in paths


@pytest.mark.unit
async def _async_test_batch_signals_returns_items_for_each_ticker(app) -> None:
    with patch.object(signals_v3, "_load_run_analysis", return_value=_fake_run_analysis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v3/signals/batch", params={"tickers": "AAPL,MSFT"})

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2

    tickers = [item["ticker"] for item in body]
    assert tickers == ["AAPL", "MSFT"]

    for item in body:
        # All spec fields present
        assert set(item.keys()) == {
            "ticker",
            "signal",
            "conviction",
            "tier",
            "expected_value_pct",
            "thesis_confidence",
            "antithesis_confidence",
            "disagreement_score",
            "final_shares",
            "pipeline_latency_ms",
            "data_gaps",
            "cached",
            "cost_usd",
            "models_used",
            # Steps 3+4: second-dimension briefing-derived fields.
            "options_direction",
            "options_impact",
            "realized_vol_20d_pct",
            "atr_pct_of_price",
            # Round 2: HAR-RV Ridge forecast fields propagated from
            # VolatilityContext (may be None when model is not trained).
            "predicted_rv_1d_pct",
            "predicted_rv_5d_pct",
            "rv_forecast_delta_pct",
            "rv_forecast_model_version",
            "used_mock",
            # Risk layer and real-time price fields.
            "tp_price",
            "sl_price",
            "risk_reward",
            "last_price",
            "change_pct",
        }
        assert item["signal"] == "BUY"
        assert item["conviction"] == 68
        assert item["tier"] == 1
        assert item["expected_value_pct"] == pytest.approx(3.2)
        assert item["thesis_confidence"] == pytest.approx(72.0)
        assert item["antithesis_confidence"] == pytest.approx(41.0)
        assert item["disagreement_score"] == pytest.approx(0.25)
        assert item["final_shares"] == 50
        assert item["pipeline_latency_ms"] == 1234
        assert item["data_gaps"] == []
        assert item["cached"] is False


@pytest.mark.unit
async def _async_test_batch_signals_isolates_failing_ticker(app) -> None:
    with patch.object(signals_v3, "_load_run_analysis", return_value=_fake_run_analysis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v3/signals/batch",
                params={"tickers": "AAPL,BROKEN,MSFT"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3

    by_ticker = {item["ticker"]: item for item in body}
    assert by_ticker["AAPL"]["signal"] == "BUY"
    assert by_ticker["MSFT"]["signal"] == "BUY"

    broken = by_ticker["BROKEN"]
    assert broken["signal"] == "HOLD"
    assert broken["conviction"] == 0
    assert broken["final_shares"] == 0
    assert any("pipeline_error" in gap for gap in broken["data_gaps"])


@pytest.mark.unit
async def _async_test_batch_signals_cache_ttl(app) -> None:
    call_count = {"n": 0}

    def counting_run_analysis(
        ticker: str,
        date: str | None = None,
        on_event: Any = None,
    ) -> FinalDecision:
        call_count["n"] += 1
        return _make_final_decision(ticker)

    with patch.object(
        signals_v3, "_load_run_analysis", return_value=counting_run_analysis
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/api/v3/signals/batch", params={"tickers": "AAPL"})
            second = await client.get("/api/v3/signals/batch", params={"tickers": "AAPL"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count["n"] == 1  # second call served from cache
    assert first.json()[0]["cached"] is False
    assert second.json()[0]["cached"] is True


@pytest.mark.unit
async def _async_test_batch_signals_rejects_empty_ticker_list(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v3/signals/batch", params={"tickers": ",,,"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Sync wrappers -- drive the async tests with asyncio.run so we don't need
# pytest-asyncio as a dependency.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_batch_signals_returns_items_for_each_ticker(app) -> None:
    asyncio.run(_async_test_batch_signals_returns_items_for_each_ticker(app))


@pytest.mark.unit
def test_batch_signals_isolates_failing_ticker(app) -> None:
    asyncio.run(_async_test_batch_signals_isolates_failing_ticker(app))


@pytest.mark.unit
def test_batch_signals_cache_ttl(app) -> None:
    asyncio.run(_async_test_batch_signals_cache_ttl(app))


@pytest.mark.unit
def test_batch_signals_rejects_empty_ticker_list(app) -> None:
    asyncio.run(_async_test_batch_signals_rejects_empty_ticker_list(app))
