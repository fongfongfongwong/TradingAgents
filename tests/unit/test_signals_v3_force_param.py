"""Unit tests for the ``force`` query parameter on ``GET /api/v3/signals/batch``.

When ``force=1`` the in-memory L1 TTL cache must be bypassed and the pipeline
re-run. Default behavior (no force) must remain unchanged -- a cache hit is
still served from cache. Also verifies the new second-dimension fields
(``options_direction`` / ``options_impact`` /
``realized_vol_20d_pct`` / ``atr_pct_of_price``) are passed through from the
``FinalDecision`` to the ``BatchSignalItem`` payload.
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
# Fixtures -- minimal FinalDecision with the new fields populated
# ---------------------------------------------------------------------------


def _make_decision(ticker: str) -> FinalDecision:
    thesis = ThesisOutput(
        ticker=ticker,
        valuation_gap_summary="fair",
        momentum_aligned=True,
        momentum_detail="positive",
        catalysts=[Catalyst(event="e", mechanism="m", magnitude_estimate="1%")],
        contrarian_signals=[],
        must_be_true=[
            MustBeTrue(
                condition=f"c{i}", probability=0.6, evidence="ev", falsifiable_by="x"
            )
            for i in range(3)
        ],
        weakest_link="none",
        confidence_rationale="ok",
        confidence_score=72,
    )
    antithesis = AntithesisOutput(
        ticker=ticker,
        overvaluation_summary="some",
        deterioration_present=False,
        deterioration_detail="none",
        risk_catalysts=[Catalyst(event="r", mechanism="m", magnitude_estimate="1%")],
        crowding_fragility=[],
        must_be_true=[
            MustBeTrue(
                condition=f"c{i}", probability=0.4, evidence="ev", falsifiable_by="x"
            )
            for i in range(3)
        ],
        weakest_link="none",
        confidence_rationale="ok",
        confidence_score=41,
    )
    base_rate = BaseRateOutput(
        ticker=ticker,
        expected_move_pct=2.0,
        upside_pct=4.0,
        downside_pct=-3.0,
        regime=Regime.RISK_ON,
        historical_analog="typical",
        base_rate_probability_up=0.55,
        volatility_forecast_20d=0.18,
    )
    synthesis = SynthesisOutput(
        ticker=ticker,
        date="2026-04-05",
        signal=Signal.BUY,
        conviction=68,
        scenarios=[
            Scenario(
                probability=0.6, target_price=210.0, return_pct=5.0, rationale="bull"
            ),
            Scenario(
                probability=0.4, target_price=195.0, return_pct=-2.0, rationale="bear"
            ),
        ],
        expected_value_pct=3.2,
        disagreement_score=0.25,
        decision_rationale="EV positive",
        key_evidence=["e1", "e2"],
    )
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
        thesis=thesis,
        antithesis=antithesis,
        base_rate=base_rate,
        synthesis=synthesis,
        risk=None,
        factor_baseline_score=0.25,
        signal=Signal.BUY,
        conviction=68,
        final_shares=50,
        pipeline_latency_ms=1234,
        options_direction="BULL",
        options_impact=78,
        realized_vol_20d_pct=32.5,
        atr_pct_of_price=2.4,
    )


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe the module-level L1 cache and stub out the L2 SQLite store."""
    signals_v3._cache.clear()
    # Neutralize the L2 SQLite cache so tests don't touch disk.
    monkeypatch.setattr(signals_v3, "_l2_get", lambda *a, **kw: None)
    monkeypatch.setattr(signals_v3, "_l2_put", lambda *a, **kw: None)
    yield
    signals_v3._cache.clear()


@pytest.fixture()
def app():
    return create_app()


# ---------------------------------------------------------------------------
# Async implementations (wrapped below in sync drivers)
# ---------------------------------------------------------------------------


async def _async_force_bypasses_cache(app) -> None:
    call_count = {"n": 0}

    def counting_run_analysis(
        ticker: str, date: str | None = None, on_event: Any = None
    ) -> FinalDecision:
        call_count["n"] += 1
        return _make_decision(ticker)

    with patch.object(
        signals_v3, "_load_run_analysis", return_value=counting_run_analysis
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First call: cold cache -> runs pipeline.
            first = await client.get(
                "/api/v3/signals/batch", params={"tickers": "AAPL"}
            )
            # Second call without force: must return the cached result.
            second = await client.get(
                "/api/v3/signals/batch", params={"tickers": "AAPL"}
            )
            # Third call with force=1: must re-run the pipeline.
            third = await client.get(
                "/api/v3/signals/batch",
                params={"tickers": "AAPL", "force": "1"},
            )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200

    assert first.json()[0]["cached"] is False
    assert second.json()[0]["cached"] is True
    assert third.json()[0]["cached"] is False
    assert call_count["n"] == 2  # once cold + once forced


async def _async_force_default_is_false(app) -> None:
    """Omitting ``force`` keeps the historic cached=True-on-second-call path."""
    call_count = {"n": 0}

    def counting_run_analysis(
        ticker: str, date: str | None = None, on_event: Any = None
    ) -> FinalDecision:
        call_count["n"] += 1
        return _make_decision(ticker)

    with patch.object(
        signals_v3, "_load_run_analysis", return_value=counting_run_analysis
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get(
                "/api/v3/signals/batch", params={"tickers": "AAPL"}
            )
            r2 = await client.get(
                "/api/v3/signals/batch", params={"tickers": "AAPL"}
            )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert call_count["n"] == 1


async def _async_new_fields_propagate(app) -> None:
    """``_decision_to_item`` must forward the new briefing-derived fields."""

    def stub_run_analysis(
        ticker: str, date: str | None = None, on_event: Any = None
    ) -> FinalDecision:
        return _make_decision(ticker)

    with patch.object(
        signals_v3, "_load_run_analysis", return_value=stub_run_analysis
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/v3/signals/batch", params={"tickers": "AAPL"}
            )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert item["options_direction"] == "BULL"
    assert item["options_impact"] == 78
    assert item["realized_vol_20d_pct"] == pytest.approx(32.5)
    assert item["atr_pct_of_price"] == pytest.approx(2.4)


# ---------------------------------------------------------------------------
# Sync wrappers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_force_bypasses_cache(app) -> None:
    asyncio.run(_async_force_bypasses_cache(app))


@pytest.mark.unit
def test_force_default_is_false(app) -> None:
    asyncio.run(_async_force_default_is_false(app))


@pytest.mark.unit
def test_new_fields_propagate(app) -> None:
    asyncio.run(_async_new_fields_propagate(app))
