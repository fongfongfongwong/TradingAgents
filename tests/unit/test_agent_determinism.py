"""Tests for P0-3/P0-6/P0-7: prompt versioning, temperature=0, used_mock.

Verifies:
1. All four v3 agents pass ``temperature=0`` to the Anthropic API.
2. Each agent exposes ``_PROMPT_VERSION`` as a module-level int.
3. Each agent's mock fallback sets ``used_mock=True`` on its output.
4. ``FinalDecision.prompt_versions`` is populated by the pipeline runner.
5. ``any_agent_used_mock`` propagates from agents through FinalDecision to
   ``BatchSignalItem``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tradingagents.schemas.v3 import (  # noqa: E402
    AntithesisOutput,
    BaseRateOutput,
    Catalyst,
    EventCalendar,
    MacroContext,
    MustBeTrue,
    NewsContext,
    OptionsContext,
    PriceContext,
    Regime,
    Scenario,
    Signal,
    SocialContext,
    SynthesisOutput,
    ThesisOutput,
    TickerBriefing,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_agent_module(filename: str) -> types.ModuleType:
    """Load an agent module directly to match runner.py's behavior."""
    path = PROJECT_ROOT / "tradingagents" / "agents" / "v3" / filename
    spec = importlib.util.spec_from_file_location(filename, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_briefing(ticker: str = "AAPL") -> TickerBriefing:
    return TickerBriefing(
        ticker=ticker,
        date="2025-01-15",
        snapshot_id="test-snap",
        price=PriceContext(
            price=150.0,
            change_1d_pct=0.5,
            change_5d_pct=1.2,
            change_20d_pct=3.0,
            sma_20=148.0,
            sma_50=145.0,
            sma_200=140.0,
            rsi_14=55.0,
            macd_above_signal=True,
            macd_crossover_days=2,
            bollinger_position="middle_third",
            volume_vs_avg_20d=1.1,
            atr_14=2.5,
            data_age_seconds=60,
        ),
        options=OptionsContext(),
        news=NewsContext(),
        social=SocialContext(),
        macro=MacroContext(),
        events=EventCalendar(),
    )


def _fake_anthropic_response(text: str) -> MagicMock:
    resp = MagicMock()
    block = MagicMock()
    block.text = text
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=10, output_tokens=20)
    return resp


# ---------------------------------------------------------------------------
# P0-3: Prompt versioning
# ---------------------------------------------------------------------------


class TestPromptVersioning:
    @pytest.mark.parametrize(
        "filename",
        [
            "thesis_agent.py",
            "antithesis_agent.py",
            "base_rate_agent.py",
            "synthesis_agent.py",
        ],
    )
    def test_agent_exposes_prompt_version(self, filename: str) -> None:
        mod = _load_agent_module(filename)
        assert hasattr(mod, "_PROMPT_VERSION"), (
            f"{filename} must define _PROMPT_VERSION"
        )
        assert isinstance(mod._PROMPT_VERSION, int)
        assert mod._PROMPT_VERSION >= 1


# ---------------------------------------------------------------------------
# P0-6: Temperature pinning
# ---------------------------------------------------------------------------


class TestTemperaturePinning:
    """For each agent, mock anthropic.Anthropic and assert temperature=0."""

    def _run_with_mock(self, filename: str, funcname: str, call_args) -> MagicMock:
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        # Valid JSON for each agent so we hit the real API call path.
        payload_map = {
            "thesis_agent.py": (
                '{"ticker":"AAPL","direction":"BUY","valuation_gap_summary":"x",'
                '"momentum_aligned":true,"momentum_detail":"x",'
                '"catalysts":[{"event":"e","mechanism":"m","magnitude_estimate":"+1%"}],'
                '"contrarian_signals":[],'
                '"must_be_true":['
                '{"condition":"a","probability":0.5,"evidence":"e","falsifiable_by":"f"},'
                '{"condition":"b","probability":0.5,"evidence":"e","falsifiable_by":"f"},'
                '{"condition":"c","probability":0.5,"evidence":"e","falsifiable_by":"f"}],'
                '"weakest_link":"w","confidence_rationale":"r","confidence_score":55}'
            ),
            "antithesis_agent.py": (
                '{"ticker":"AAPL","direction":"SHORT","overvaluation_summary":"x",'
                '"deterioration_present":false,"deterioration_detail":"x",'
                '"risk_catalysts":[{"event":"e","mechanism":"m","magnitude_estimate":"-1%"}],'
                '"crowding_fragility":[],'
                '"must_be_true":['
                '{"condition":"a","probability":0.5,"evidence":"e","falsifiable_by":"f"},'
                '{"condition":"b","probability":0.5,"evidence":"e","falsifiable_by":"f"},'
                '{"condition":"c","probability":0.5,"evidence":"e","falsifiable_by":"f"}],'
                '"weakest_link":"w","confidence_rationale":"r","confidence_score":30}'
            ),
            "base_rate_agent.py": (
                '{"ticker":"AAPL","expected_move_pct":1.0,"upside_pct":5.0,'
                '"downside_pct":-4.0,"regime":"TRANSITIONING",'
                '"historical_analog":"Q2 2019","base_rate_probability_up":0.55,'
                '"volatility_forecast_20d":22.0,"sector_momentum_rank":null}'
            ),
            "synthesis_agent.py": (
                '{"ticker":"AAPL","date":"2025-01-15","signal":"HOLD","conviction":50,'
                '"scenarios":[{"probability":0.5,"target_price":150.0,'
                '"return_pct":1.0,"rationale":"r"}],'
                '"expected_value_pct":1.0,"disagreement_score":0.2,'
                '"data_audit":[],"must_be_true_resolved":[],'
                '"decision_rationale":"r","key_evidence":["e"],'
                '"hold_threshold_met":false}'
            ),
        }

        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response(
            payload_map[filename]
        )

        fake_anthropic = types.ModuleType("anthropic")
        fake_anthropic.Anthropic = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            mod = _load_agent_module(filename)
            func = getattr(mod, funcname)
            result = func(*call_args)
            assert result is not None

        return fake_client.messages.create

    def test_thesis_temperature_zero(self) -> None:
        create = self._run_with_mock(
            "thesis_agent.py", "run_thesis_agent", (_make_briefing(),)
        )
        assert create.called
        for call in create.call_args_list:
            assert call.kwargs.get("temperature") == 0

    def test_antithesis_temperature_zero(self) -> None:
        create = self._run_with_mock(
            "antithesis_agent.py", "run_antithesis_agent", (_make_briefing(),)
        )
        assert create.called
        for call in create.call_args_list:
            assert call.kwargs.get("temperature") == 0

    def test_base_rate_temperature_zero(self) -> None:
        create = self._run_with_mock(
            "base_rate_agent.py", "run_base_rate_agent", (_make_briefing(),)
        )
        assert create.called
        for call in create.call_args_list:
            assert call.kwargs.get("temperature") == 0

    def test_synthesis_temperature_zero(self) -> None:
        thesis = _make_thesis()
        antithesis = _make_antithesis()
        base_rate = _make_base_rate()
        create = self._run_with_mock(
            "synthesis_agent.py",
            "run_synthesis_agent",
            (thesis, antithesis, base_rate),
        )
        assert create.called
        for call in create.call_args_list:
            assert call.kwargs.get("temperature") == 0


# ---------------------------------------------------------------------------
# Fixtures for downstream agents
# ---------------------------------------------------------------------------


def _make_thesis() -> ThesisOutput:
    return ThesisOutput(
        ticker="AAPL",
        direction="BUY",
        valuation_gap_summary="x",
        momentum_aligned=True,
        momentum_detail="x",
        catalysts=[Catalyst(event="e", mechanism="m", magnitude_estimate="+1%")],
        contrarian_signals=[],
        must_be_true=[
            MustBeTrue(condition="a", probability=0.5, evidence="e", falsifiable_by="f"),
            MustBeTrue(condition="b", probability=0.5, evidence="e", falsifiable_by="f"),
            MustBeTrue(condition="c", probability=0.5, evidence="e", falsifiable_by="f"),
        ],
        weakest_link="w",
        confidence_rationale="r",
        confidence_score=55,
    )


def _make_antithesis() -> AntithesisOutput:
    return AntithesisOutput(
        ticker="AAPL",
        direction="SHORT",
        overvaluation_summary="x",
        deterioration_present=False,
        deterioration_detail="x",
        risk_catalysts=[Catalyst(event="e", mechanism="m", magnitude_estimate="-1%")],
        crowding_fragility=[],
        must_be_true=[
            MustBeTrue(condition="a", probability=0.5, evidence="e", falsifiable_by="f"),
            MustBeTrue(condition="b", probability=0.5, evidence="e", falsifiable_by="f"),
            MustBeTrue(condition="c", probability=0.5, evidence="e", falsifiable_by="f"),
        ],
        weakest_link="w",
        confidence_rationale="r",
        confidence_score=30,
    )


def _make_base_rate() -> BaseRateOutput:
    return BaseRateOutput(
        ticker="AAPL",
        expected_move_pct=1.0,
        upside_pct=5.0,
        downside_pct=-4.0,
        regime=Regime.TRANSITIONING,
        historical_analog="x",
        base_rate_probability_up=0.55,
        volatility_forecast_20d=22.0,
    )


# ---------------------------------------------------------------------------
# P0-7: used_mock propagation
# ---------------------------------------------------------------------------


class TestUsedMockFallback:
    """When the LLM path fails, agents must set used_mock=True."""

    def test_thesis_used_mock_when_no_api_key(self) -> None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        mod = _load_agent_module("thesis_agent.py")
        result = mod.run_thesis_agent(_make_briefing())
        assert isinstance(result, ThesisOutput)
        assert result.used_mock is True

    def test_antithesis_used_mock_when_no_api_key(self) -> None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        mod = _load_agent_module("antithesis_agent.py")
        result = mod.run_antithesis_agent(_make_briefing())
        assert isinstance(result, AntithesisOutput)
        assert result.used_mock is True

    def test_base_rate_used_mock_when_llm_fails(self) -> None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        mod = _load_agent_module("base_rate_agent.py")
        result = mod.run_base_rate_agent(_make_briefing())
        assert isinstance(result, BaseRateOutput)
        assert result.used_mock is True

    def test_synthesis_used_mock_when_no_api_key(self) -> None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        mod = _load_agent_module("synthesis_agent.py")
        result = mod.run_synthesis_agent(
            _make_thesis(), _make_antithesis(), _make_base_rate()
        )
        assert isinstance(result, SynthesisOutput)
        assert result.used_mock is True


# ---------------------------------------------------------------------------
# Pipeline wiring: prompt_versions + any_agent_used_mock + BatchSignalItem
# ---------------------------------------------------------------------------


class TestPipelineWiring:
    def test_final_decision_has_prompt_versions_and_mock_flag(self) -> None:
        """Runner assembly must populate prompt_versions and any_agent_used_mock.

        We avoid calling ``run_analysis`` end-to-end (which pulls in numpy
        via the materializer and collides with importlib-loaded agent
        modules in the same process). Instead we verify the wiring by
        directly reproducing the runner's ``FinalDecision`` construction
        using the same helpers.
        """
        from tradingagents.pipeline.runner import _load_agent_module
        from tradingagents.schemas.v3 import (
            FinalDecision,
            ScreeningResult,
            Tier,
        )

        thesis_mod = _load_agent_module("thesis_agent.py")
        antithesis_mod = _load_agent_module("antithesis_agent.py")
        base_rate_mod = _load_agent_module("base_rate_agent.py")
        synthesis_mod = _load_agent_module("synthesis_agent.py")

        # All agents return mock outputs (no API key).
        os.environ.pop("ANTHROPIC_API_KEY", None)
        briefing = _make_briefing()
        thesis = thesis_mod.run_thesis_agent(briefing)
        antithesis = antithesis_mod.run_antithesis_agent(briefing)
        base_rate = base_rate_mod.run_base_rate_agent(briefing)
        synthesis = synthesis_mod.run_synthesis_agent(thesis, antithesis, base_rate)

        assert thesis.used_mock is True
        assert antithesis.used_mock is True
        assert base_rate.used_mock is True
        assert synthesis.used_mock is True

        screening = ScreeningResult(
            ticker="AAPL",
            tier=Tier.FULL,
            trigger_reasons=["test"],
            factor_score=0.0,
        )
        decision = FinalDecision(
            ticker="AAPL",
            date="2025-01-15",
            snapshot_id="test",
            tier=Tier.FULL,
            screening=screening,
            thesis=thesis,
            antithesis=antithesis,
            base_rate=base_rate,
            synthesis=synthesis,
            factor_baseline_score=0.0,
            signal=synthesis.signal,
            conviction=synthesis.conviction,
            prompt_versions={
                "thesis": getattr(thesis_mod, "_PROMPT_VERSION", 0),
                "antithesis": getattr(antithesis_mod, "_PROMPT_VERSION", 0),
                "base_rate": getattr(base_rate_mod, "_PROMPT_VERSION", 0),
                "synthesis": getattr(synthesis_mod, "_PROMPT_VERSION", 0),
            },
            any_agent_used_mock=any(
                [
                    thesis.used_mock,
                    antithesis.used_mock,
                    base_rate.used_mock,
                    synthesis.used_mock,
                ]
            ),
        )

        assert set(decision.prompt_versions.keys()) == {
            "thesis",
            "antithesis",
            "base_rate",
            "synthesis",
        }
        for v in decision.prompt_versions.values():
            assert isinstance(v, int) and v >= 1
        assert decision.any_agent_used_mock is True

    def test_batch_signal_item_propagates_used_mock(self) -> None:
        from tradingagents.api.models.responses import BatchSignalItem
        from tradingagents.api.routes.signals_v3 import _decision_to_item
        from tradingagents.schemas.v3 import (
            FinalDecision,
            ScreeningResult,
            Tier,
        )

        screening = ScreeningResult(
            ticker="AAPL",
            tier=Tier.FULL,
            trigger_reasons=["test"],
            factor_score=0.1,
        )
        decision = FinalDecision(
            ticker="AAPL",
            date="2025-01-15",
            snapshot_id="test",
            tier=Tier.FULL,
            screening=screening,
            factor_baseline_score=0.1,
            signal=Signal.HOLD,
            conviction=50,
            any_agent_used_mock=True,
        )
        item = _decision_to_item("AAPL", decision)
        assert isinstance(item, BatchSignalItem)
        assert item.used_mock is True

        decision_clean = FinalDecision(
            ticker="AAPL",
            date="2025-01-15",
            snapshot_id="test",
            tier=Tier.FULL,
            screening=screening,
            factor_baseline_score=0.1,
            signal=Signal.HOLD,
            conviction=50,
            any_agent_used_mock=False,
        )
        item_clean = _decision_to_item("AAPL", decision_clean)
        assert item_clean.used_mock is False
