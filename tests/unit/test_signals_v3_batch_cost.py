"""Unit tests for G4 cost/models_used fields on the v3 batch endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tradingagents.api.main import create_app
from tradingagents.api.routes import signals_v3
from tradingagents.gateway.cost_tracker import (
    CostEntry,
    get_cost_tracker,
)
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
# Fixture factories (small, reused from sibling test)
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
        model_versions={
            "thesis": "claude-sonnet-4-5",
            "antithesis": "claude-sonnet-4-5",
            "base_rate": "claude-sonnet-4-5",
            "synthesis": "claude-opus-4-1-20250805",
        },
    )


def _fake_run_analysis(
    ticker: str,
    date: str | None = None,
    on_event: Any = None,
) -> FinalDecision:
    # Simulate recorded LLM usage for this ticker before returning the decision.
    tracker = get_cost_tracker()
    tracker.record(
        CostEntry(
            ticker=ticker,
            agent_name="thesis",
            model="claude-sonnet-4-5",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.0105,
            timestamp=datetime.now(),
        )
    )
    tracker.record(
        CostEntry(
            ticker=ticker,
            agent_name="synthesis",
            model="claude-opus-4-1-20250805",
            input_tokens=2000,
            output_tokens=1000,
            cost_usd=0.105,
            timestamp=datetime.now(),
        )
    )
    return _make_final_decision(ticker)


@pytest.fixture(autouse=True)
def _clear_state(monkeypatch: pytest.MonkeyPatch) -> None:
    signals_v3._cache.clear()
    signals_v3._SIGNALS_SEMAPHORE = None
    monkeypatch.setattr(signals_v3, "_l2_get", lambda *a, **kw: None)
    monkeypatch.setattr(signals_v3, "_l2_put", lambda *a, **kw: None)
    get_cost_tracker().reset()
    yield
    signals_v3._cache.clear()
    signals_v3._SIGNALS_SEMAPHORE = None
    get_cost_tracker().reset()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_batch_response_includes_cost_usd_and_models_used(client: TestClient) -> None:
    with patch.object(
        signals_v3, "_load_run_analysis", return_value=_fake_run_analysis
    ):
        resp = client.get("/api/v3/signals/batch", params={"tickers": "AAPL"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert "cost_usd" in item
    assert "models_used" in item
    assert item["cost_usd"] == pytest.approx(0.0105 + 0.105)
    # model_versions had 2 unique values -> deduped list.
    assert set(item["models_used"]) == {
        "claude-sonnet-4-5",
        "claude-opus-4-1-20250805",
    }


@pytest.mark.unit
def test_batch_zero_cost_when_nothing_recorded(client: TestClient) -> None:
    # A runner that doesn't record any cost.
    def _no_cost_runner(
        ticker: str, date: str | None = None, on_event: Any = None
    ) -> FinalDecision:
        return _make_final_decision(ticker)

    with patch.object(signals_v3, "_load_run_analysis", return_value=_no_cost_runner):
        resp = client.get("/api/v3/signals/batch", params={"tickers": "MSFT"})
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["cost_usd"] == pytest.approx(0.0)
    # models_used still populated from the decision's model_versions dict.
    assert len(item["models_used"]) >= 1
