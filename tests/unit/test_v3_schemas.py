"""Unit tests for v3 Pydantic schemas.

Covers the reasoning fields surfaced in Feature G3 (AnalysisTab Reasoning
Panels) and backward-compatibility guarantees for ``FinalDecision.data_gaps``.
"""

from __future__ import annotations

import pytest

from tradingagents.schemas.v3 import (
    AntithesisOutput,
    Catalyst,
    FinalDecision,
    MustBeTrue,
    Regime,
    ScreeningResult,
    Signal,
    SynthesisOutput,
    ThesisOutput,
    Tier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _must_be_true_set() -> list[MustBeTrue]:
    return [
        MustBeTrue(
            condition=f"condition-{i}",
            probability=0.6,
            evidence="evidence",
            falsifiable_by="metric",
        )
        for i in range(3)
    ]


def _catalyst() -> Catalyst:
    return Catalyst(event="Earnings", mechanism="beat", magnitude_estimate="+5%")


# ---------------------------------------------------------------------------
# Thesis / Antithesis reasoning fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_thesis_output_with_reasoning_fields() -> None:
    thesis = ThesisOutput(
        ticker="AAPL",
        valuation_gap_summary="15% below fair value",
        momentum_aligned=True,
        momentum_detail="Price above 20/50/200 SMAs; MACD positive for 14 days.",
        catalysts=[_catalyst()],
        contrarian_signals=["RSI approaching overbought", "Insider selling uptick"],
        must_be_true=_must_be_true_set(),
        weakest_link="Valuation premium vs peers",
        confidence_rationale="High catalyst clarity and supportive momentum.",
        confidence_score=72,
    )
    assert thesis.confidence_rationale.startswith("High catalyst")
    assert len(thesis.contrarian_signals) == 2
    assert thesis.momentum_detail.endswith("14 days.")


@pytest.mark.unit
def test_antithesis_output_with_reasoning_fields() -> None:
    antithesis = AntithesisOutput(
        ticker="AAPL",
        overvaluation_summary="Trades at 30x forward earnings",
        deterioration_present=True,
        deterioration_detail="Gross margin compression QoQ, China softness.",
        risk_catalysts=[_catalyst()],
        crowding_fragility=["Top-10 hedge-fund long", "Options skew inverted"],
        must_be_true=_must_be_true_set(),
        weakest_link="Macro regime still supportive",
        confidence_rationale="Crowded long with deteriorating fundamentals.",
        confidence_score=65,
    )
    assert antithesis.crowding_fragility == [
        "Top-10 hedge-fund long",
        "Options skew inverted",
    ]
    assert "deteriorating" in antithesis.confidence_rationale


@pytest.mark.unit
def test_synthesis_output_key_evidence_list() -> None:
    synthesis = SynthesisOutput(
        ticker="AAPL",
        date="2026-04-05",
        signal=Signal.BUY,
        conviction=68,
        scenarios=[
            {
                "probability": 0.6,
                "target_price": 200.0,
                "return_pct": 12.0,
                "rationale": "Base case",
            }
        ],
        expected_value_pct=7.2,
        disagreement_score=0.3,
        decision_rationale="Thesis wins on catalyst clarity.",
        key_evidence=[
            "EPS beat of +8% vs consensus",
            "Options skew favorable",
            "Sector momentum rank top-5",
        ],
    )
    assert len(synthesis.key_evidence) == 3
    assert synthesis.key_evidence[0].startswith("EPS beat")


# ---------------------------------------------------------------------------
# FinalDecision.data_gaps backward compatibility
# ---------------------------------------------------------------------------


def _minimal_final_decision_payload() -> dict:
    return {
        "ticker": "AAPL",
        "date": "2026-04-05",
        "snapshot_id": "snap-1",
        "tier": Tier.FULL,
        "screening": ScreeningResult(
            ticker="AAPL",
            tier=Tier.FULL,
            trigger_reasons=["factor_score>0.4"],
            factor_score=0.55,
        ),
        "factor_baseline_score": 0.55,
        "signal": Signal.BUY,
        "conviction": 68,
    }


@pytest.mark.unit
def test_final_decision_data_gaps_defaults_to_empty_list() -> None:
    """Legacy payloads omitting data_gaps must still parse."""
    decision = FinalDecision(**_minimal_final_decision_payload())
    assert decision.data_gaps == []


@pytest.mark.unit
def test_final_decision_accepts_data_gaps() -> None:
    payload = _minimal_final_decision_payload()
    payload["data_gaps"] = [
        "news:finnhub_fallback:rate_limit",
        "options:analytics_fallback",
    ]
    decision = FinalDecision(**payload)
    assert len(decision.data_gaps) == 2
    assert decision.data_gaps[0].startswith("news:")


# ---------------------------------------------------------------------------
# Round-trip JSON serialization (ensures API response shape is stable)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_final_decision_json_roundtrip_preserves_data_gaps() -> None:
    payload = _minimal_final_decision_payload()
    payload["data_gaps"] = ["macro:fred_fallback"]
    decision = FinalDecision(**payload)

    dumped = decision.model_dump(mode="json")
    assert dumped["data_gaps"] == ["macro:fred_fallback"]

    restored = FinalDecision.model_validate(dumped)
    assert restored.data_gaps == ["macro:fred_fallback"]
    assert restored.signal == Signal.BUY


@pytest.mark.unit
def test_regime_enum_is_exported() -> None:
    """Guard against accidental removal — other tests/consumers rely on it."""
    assert Regime.RISK_ON.value == "RISK_ON"


# ---------------------------------------------------------------------------
# HAR-RV Ridge forecast fields on VolatilityContext
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_volatility_context_has_rv_forecast_field_defaults() -> None:
    """New HAR-RV fields must default to ``None`` for backward compat."""
    from tradingagents.schemas.v3 import VolatilityContext

    ctx = VolatilityContext()
    assert ctx.predicted_rv_1d_pct is None
    assert ctx.predicted_rv_5d_pct is None
    assert ctx.rv_forecast_model_version is None
    assert ctx.rv_forecast_delta_pct is None


@pytest.mark.unit
def test_volatility_context_rv_forecast_roundtrip() -> None:
    """VolatilityContext with RV fields serializes and deserializes cleanly."""
    from tradingagents.schemas.v3 import VolatilityContext

    ctx = VolatilityContext(
        realized_vol_20d_pct=18.2,
        predicted_rv_1d_pct=19.5,
        predicted_rv_5d_pct=20.1,
        rv_forecast_model_version="har_rv_ridge_v1_trained_2026-04-05",
        rv_forecast_delta_pct=1.3,
    )
    dumped = ctx.model_dump(mode="json")
    assert dumped["predicted_rv_1d_pct"] == 19.5
    assert dumped["predicted_rv_5d_pct"] == 20.1
    assert dumped["rv_forecast_model_version"] == "har_rv_ridge_v1_trained_2026-04-05"
    assert dumped["rv_forecast_delta_pct"] == 1.3

    restored = VolatilityContext.model_validate(dumped)
    assert restored.predicted_rv_1d_pct == 19.5
    assert restored.rv_forecast_model_version == "har_rv_ridge_v1_trained_2026-04-05"


@pytest.mark.unit
def test_volatility_context_parses_legacy_payload_without_rv_fields() -> None:
    """Old cached briefings (pre-HAR-RV) must still parse."""
    from tradingagents.schemas.v3 import VolatilityContext

    legacy = {
        "realized_vol_5d_pct": 20.0,
        "realized_vol_20d_pct": 22.0,
        "realized_vol_60d_pct": 25.0,
        "atr_14_pct_of_price": 2.1,
        "bollinger_band_width_pct": 5.5,
        "iv_rank_percentile": 42.0,
        "vol_regime": "NORMAL",
        "vol_percentile_1y": 60.0,
        "kline_last_20": [],
        "data_age_seconds": 0,
    }
    ctx = VolatilityContext.model_validate(legacy)
    assert ctx.predicted_rv_1d_pct is None
    assert ctx.rv_forecast_model_version is None
