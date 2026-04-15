"""Tests for parallel execution of thesis/antithesis/base_rate agents in runner.py."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.schemas.v3 import (
    AntithesisOutput,
    BaseRateOutput,
    Catalyst,
    MustBeTrue,
    Regime,
    RiskOutput,
    Scenario,
    ScreeningResult,
    Signal,
    StressTestResult,
    SynthesisOutput,
    ThesisOutput,
    Tier,
)


def _make_catalyst() -> Catalyst:
    return Catalyst(event="earnings", mechanism="beat", magnitude_estimate="5%")


def _make_must_be_true() -> MustBeTrue:
    return MustBeTrue(
        condition="revenue grows",
        probability=0.7,
        evidence="trend",
        falsifiable_by="miss",
    )


def _make_thesis(**overrides) -> ThesisOutput:
    defaults = dict(
        ticker="TEST",
        direction="BUY",
        valuation_gap_summary="undervalued",
        momentum_aligned=True,
        momentum_detail="strong uptrend",
        catalysts=[_make_catalyst()],
        contrarian_signals=["signal1"],
        must_be_true=[_make_must_be_true()] * 3,
        weakest_link="execution risk",
        confidence_rationale="strong fundamentals",
        confidence_score=80,
        used_mock=True,
    )
    defaults.update(overrides)
    return ThesisOutput(**defaults)


def _make_antithesis(**overrides) -> AntithesisOutput:
    defaults = dict(
        ticker="TEST",
        direction="SHORT",
        overvaluation_summary="overvalued",
        deterioration_present=True,
        deterioration_detail="margin compression",
        risk_catalysts=[_make_catalyst()],
        crowding_fragility=["crowded trade"],
        must_be_true=[_make_must_be_true()] * 3,
        weakest_link="valuation support",
        confidence_rationale="weak outlook",
        confidence_score=70,
        used_mock=True,
    )
    defaults.update(overrides)
    return AntithesisOutput(**defaults)


def _make_base_rate(**overrides) -> BaseRateOutput:
    defaults = dict(
        ticker="TEST",
        expected_move_pct=2.5,
        upside_pct=5.0,
        downside_pct=-3.0,
        regime=Regime.RISK_ON,
        historical_analog="2021 recovery",
        base_rate_probability_up=0.55,
        volatility_forecast_20d=0.25,
        used_mock=True,
    )
    defaults.update(overrides)
    return BaseRateOutput(**defaults)


def _build_common_patches():
    """Return a list of patch context managers for everything outside the 3 agents."""
    briefing = MagicMock()
    briefing.snapshot_id = "snap-test"
    briefing.data_gaps = []
    briefing.options = None
    briefing.price = None
    briefing.volatility = None

    screening = ScreeningResult(
        ticker="TEST", tier=Tier.FULL, trigger_reasons=["test"], factor_score=0.5
    )

    patches = [
        patch(
            "tradingagents.data.materializer.materialize_briefing",
            return_value=briefing,
        ),
        patch(
            "tradingagents.data.screener.screen_ticker",
            return_value=screening,
        ),
        patch(
            "tradingagents.signals.factor_baseline.compute_factor_score",
            return_value={"composite_score": 0.5, "signal": Signal.BUY},
        ),
        patch(
            "tradingagents.risk.deterministic.evaluate_risk",
            return_value=_make_risk_output(),
        ),
        patch("tradingagents.data.snapshot.init_db"),
        patch("tradingagents.data.snapshot.store_snapshot"),
    ]
    return patches, briefing


def _make_synth_output() -> SynthesisOutput:
    return SynthesisOutput(
        ticker="TEST", date="2026-04-06", signal=Signal.BUY, conviction=75,
        scenarios=[Scenario(probability=0.6, target_price=110, return_pct=10.0, rationale="test")],
        expected_value_pct=1.5, disagreement_score=0.3, decision_rationale="test",
        key_evidence=["ev1"], used_mock=True,
    )


def _make_risk_output() -> RiskOutput:
    return RiskOutput(
        ticker="TEST", signal=Signal.BUY, risk_rating="LOW",
        base_shares=10, volatility_adjusted_shares=10, concentration_adjusted_shares=10,
        event_adjusted_shares=10, final_shares=10, position_value_usd=1000.0,
        position_pct_of_portfolio=0.01, binding_constraint="none",
        stop_loss_price=90.0, stop_loss_type="volatility", take_profit_price=120.0,
        risk_reward_ratio=2.0, max_loss_usd=100.0, max_loss_pct_portfolio=0.005,
        stress_tests=[], risk_flags=[],
    )


def _make_synthesis_mod():
    synthesis_mod = MagicMock()
    synthesis_mod.run_synthesis_agent.return_value = _make_synth_output()
    synthesis_mod._PROMPT_VERSION = 1
    return synthesis_mod


class TestParallelExecution:
    """Test that thesis, antithesis, and base_rate agents run in parallel."""

    def test_all_three_agents_run_concurrently(self):
        """All 3 agents should overlap in execution, not run strictly sequentially."""
        call_log: list[tuple[str, str, float]] = []
        lock = threading.Lock()

        thesis_out = _make_thesis()
        antithesis_out = _make_antithesis()
        base_rate_out = _make_base_rate()

        def fake_thesis(briefing):
            with lock:
                call_log.append(("thesis", "start", time.monotonic()))
            time.sleep(0.1)
            with lock:
                call_log.append(("thesis", "end", time.monotonic()))
            return thesis_out

        def fake_antithesis(briefing):
            with lock:
                call_log.append(("antithesis", "start", time.monotonic()))
            time.sleep(0.1)
            with lock:
                call_log.append(("antithesis", "end", time.monotonic()))
            return antithesis_out

        def fake_base_rate(briefing):
            with lock:
                call_log.append(("base_rate", "start", time.monotonic()))
            time.sleep(0.1)
            with lock:
                call_log.append(("base_rate", "end", time.monotonic()))
            return base_rate_out

        synthesis_mod = _make_synthesis_mod()

        thesis_mod = MagicMock()
        thesis_mod.run_thesis_agent = fake_thesis
        thesis_mod._mock_thesis = lambda b: _make_thesis()
        thesis_mod._PROMPT_VERSION = 1

        antithesis_mod = MagicMock()
        antithesis_mod.run_antithesis_agent = fake_antithesis
        antithesis_mod._mock_antithesis = lambda b: _make_antithesis()
        antithesis_mod._PROMPT_VERSION = 1

        base_rate_mod = MagicMock()
        base_rate_mod.run_base_rate_agent = fake_base_rate
        base_rate_mod._mock_base_rate = lambda b: _make_base_rate()
        base_rate_mod._PROMPT_VERSION = 1

        def load_module(filename):
            return {
                "thesis_agent.py": thesis_mod,
                "antithesis_agent.py": antithesis_mod,
                "base_rate_agent.py": base_rate_mod,
                "synthesis_agent.py": synthesis_mod,
            }[filename]

        common_patches, _ = _build_common_patches()

        with patch(
            "tradingagents.pipeline.runner._load_agent_module",
            side_effect=load_module,
        ):
            for p in common_patches:
                p.start()
            try:
                from tradingagents.pipeline.runner import run_analysis

                run_analysis("TEST", date="2025-01-01")
            finally:
                for p in common_patches:
                    p.stop()

        # Verify all 3 started
        starts = [(name, t) for name, phase, t in call_log if phase == "start"]
        ends = [(name, t) for name, phase, t in call_log if phase == "end"]
        assert len(starts) == 3, f"Expected 3 starts, got {len(starts)}"
        assert len(ends) == 3, f"Expected 3 ends, got {len(ends)}"

        # Check overlap: the last agent to start should have started before
        # the first agent to end (proves concurrency)
        last_start = max(t for _, t in starts)
        first_end = min(t for _, t in ends)
        assert last_start < first_end, (
            "Agents did not run concurrently: last start "
            f"({last_start:.4f}) >= first end ({first_end:.4f})"
        )


class TestFailureFallback:
    """Test that if one agent raises, the others still complete."""

    def test_one_agent_fails_others_succeed(self):
        """If thesis raises, antithesis and base_rate should still run,
        and synthesis should receive a mock fallback for thesis."""
        thesis_out = _make_thesis()
        antithesis_out = _make_antithesis()
        base_rate_out = _make_base_rate()

        call_count = 0

        def failing_thesis(briefing):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("LLM API failure")
            # Second call (mock fallback) succeeds
            return thesis_out

        synthesis_mod = _make_synthesis_mod()

        thesis_mod = MagicMock()
        thesis_mod.run_thesis_agent = failing_thesis
        thesis_mod._mock_thesis = lambda briefing: thesis_out  # mock fallback
        thesis_mod._PROMPT_VERSION = 1

        antithesis_mod = MagicMock()
        antithesis_mod.run_antithesis_agent.return_value = antithesis_out
        antithesis_mod._mock_antithesis = lambda briefing: antithesis_out
        antithesis_mod._PROMPT_VERSION = 1

        base_rate_mod = MagicMock()
        base_rate_mod.run_base_rate_agent.return_value = base_rate_out
        base_rate_mod._mock_base_rate = lambda briefing: base_rate_out
        base_rate_mod._PROMPT_VERSION = 1

        def load_module(filename):
            return {
                "thesis_agent.py": thesis_mod,
                "antithesis_agent.py": antithesis_mod,
                "base_rate_agent.py": base_rate_mod,
                "synthesis_agent.py": synthesis_mod,
            }[filename]

        common_patches, _ = _build_common_patches()

        with patch(
            "tradingagents.pipeline.runner._load_agent_module",
            side_effect=load_module,
        ):
            for p in common_patches:
                p.start()
            try:
                from tradingagents.pipeline.runner import run_analysis

                result = run_analysis("TEST", date="2025-01-01")
            finally:
                for p in common_patches:
                    p.stop()

        # Synthesis should have been called with the mock-fallback thesis
        synthesis_mod.run_synthesis_agent.assert_called_once()
        call_args = synthesis_mod.run_synthesis_agent.call_args[0]
        assert isinstance(call_args[0], ThesisOutput)  # thesis (mock fallback)
        assert isinstance(call_args[1], AntithesisOutput)  # antithesis
        assert isinstance(call_args[2], BaseRateOutput)  # base_rate


class TestSynthesisReceivesCorrectObjects:
    """Test that synthesis receives the exact thesis/antithesis/base_rate objects."""

    def test_synthesis_gets_correct_inputs(self):
        thesis_out = _make_thesis(confidence_score=92)
        antithesis_out = _make_antithesis(confidence_score=63)
        base_rate_out = _make_base_rate(base_rate_probability_up=0.71)

        synthesis_mod = _make_synthesis_mod()

        thesis_mod = MagicMock()
        thesis_mod.run_thesis_agent.return_value = thesis_out
        thesis_mod._mock_thesis = lambda b: thesis_out
        thesis_mod._PROMPT_VERSION = 1

        antithesis_mod = MagicMock()
        antithesis_mod.run_antithesis_agent.return_value = antithesis_out
        antithesis_mod._mock_antithesis = lambda b: antithesis_out
        antithesis_mod._PROMPT_VERSION = 1

        base_rate_mod = MagicMock()
        base_rate_mod.run_base_rate_agent.return_value = base_rate_out
        base_rate_mod._mock_base_rate = lambda b: base_rate_out
        base_rate_mod._PROMPT_VERSION = 1

        def load_module(filename):
            return {
                "thesis_agent.py": thesis_mod,
                "antithesis_agent.py": antithesis_mod,
                "base_rate_agent.py": base_rate_mod,
                "synthesis_agent.py": synthesis_mod,
            }[filename]

        common_patches, _ = _build_common_patches()

        with patch(
            "tradingagents.pipeline.runner._load_agent_module",
            side_effect=load_module,
        ):
            for p in common_patches:
                p.start()
            try:
                from tradingagents.pipeline.runner import run_analysis

                run_analysis("TEST", date="2025-01-01")
            finally:
                for p in common_patches:
                    p.stop()

        # Verify synthesis received the exact objects
        synthesis_mod.run_synthesis_agent.assert_called_once_with(
            thesis_out, antithesis_out, base_rate_out
        )
