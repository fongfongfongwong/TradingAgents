"""Tests for the LLM Gateway - router and cost tracker."""

import pytest

from tradingagents.gateway.router import LLMRouter, ModelTier, AGENT_TIER_MAP
from tradingagents.gateway.cost_tracker import CostTracker, PRICING


# ---------------------------------------------------------------------------
# LLMRouter tests
# ---------------------------------------------------------------------------


class TestModelTier:
    def test_tier_values(self):
        assert ModelTier.EXTRACT.value == "extract"
        assert ModelTier.REASON.value == "reason"
        assert ModelTier.DECIDE.value == "decide"


class TestLLMRouter:
    def test_default_tier_models(self):
        router = LLMRouter()
        assert router.tier_models["extract"] == "gpt-4o-mini"
        assert router.tier_models["reason"] == "gpt-4o"
        assert router.tier_models["decide"] == "gpt-4o"

    def test_custom_tier_config_overrides(self):
        router = LLMRouter(tier_config={"extract": "gpt-3.5-turbo", "decide": "o1"})
        assert router.get_model("Market Analyst") == "gpt-3.5-turbo"
        assert router.get_model("Trader") == "o1"
        # reason tier should remain default
        assert router.get_model("Bull Researcher") == "gpt-4o"

    def test_get_model_extract_agent(self):
        router = LLMRouter()
        assert router.get_model("Market Analyst") == "gpt-4o-mini"

    def test_get_model_reason_agent(self):
        router = LLMRouter()
        assert router.get_model("Bull Researcher") == "gpt-4o"

    def test_get_model_decide_agent(self):
        router = LLMRouter()
        assert router.get_model("Trader") == "gpt-4o"

    def test_unknown_agent_defaults_to_reason(self):
        router = LLMRouter()
        assert router.get_tier("Unknown Agent") == ModelTier.REASON
        assert router.get_model("Unknown Agent") == "gpt-4o"

    @pytest.mark.parametrize(
        "agent",
        [
            "Market Analyst",
            "Social Media Analyst",
            "News Analyst",
            "Fundamentals Analyst",
            "Options Analyst",
            "Macro Analyst",
        ],
    )
    def test_all_analysts_map_to_extract(self, agent):
        router = LLMRouter()
        assert router.get_tier(agent) == ModelTier.EXTRACT

    @pytest.mark.parametrize("agent", ["Bull Researcher", "Bear Researcher"])
    def test_researchers_map_to_reason(self, agent):
        router = LLMRouter()
        assert router.get_tier(agent) == ModelTier.REASON

    @pytest.mark.parametrize(
        "agent",
        [
            "Research Manager",
            "Trader",
            "Aggressive Analyst",
            "Conservative Analyst",
            "Neutral Analyst",
            "Portfolio Manager",
        ],
    )
    def test_managers_map_to_decide(self, agent):
        router = LLMRouter()
        assert router.get_tier(agent) == ModelTier.DECIDE

    def test_estimate_cost_known_model(self):
        router = LLMRouter()
        # gpt-4o-mini: input $0.15/1M, output $0.60/1M
        cost = router.estimate_cost("Market Analyst", 1_000_000, 1_000_000)
        assert abs(cost - 0.75) < 1e-6

    def test_estimate_cost_unknown_model_uses_default(self):
        router = LLMRouter(tier_config={"extract": "some-unknown-model"})
        # default pricing: input $1.00/1M, output $3.00/1M
        cost = router.estimate_cost("Market Analyst", 1_000_000, 1_000_000)
        assert abs(cost - 4.00) < 1e-6


# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------


class TestCostTracker:
    def test_record_and_total(self):
        tracker = CostTracker()
        # gpt-4o-mini: input $0.15/1M, output $0.60/1M
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 500_000)
        expected = 0.15 + 0.30
        assert abs(tracker.total_cost() - expected) < 1e-6

    def test_cost_by_agent(self):
        tracker = CostTracker()
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 0)
        tracker.record("News Analyst", "gpt-4o-mini", 1_000_000, 0)
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 0)
        breakdown = tracker.cost_by_agent()
        assert abs(breakdown["Market Analyst"] - 0.30) < 1e-6
        assert abs(breakdown["News Analyst"] - 0.15) < 1e-6

    def test_cost_by_tier(self):
        tracker = CostTracker()
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 0)  # extract
        tracker.record("Bull Researcher", "gpt-4o", 1_000_000, 0)  # reason
        tracker.record("Trader", "gpt-4o", 1_000_000, 0)  # decide
        breakdown = tracker.cost_by_tier()
        assert "extract" in breakdown
        assert "reason" in breakdown
        assert "decide" in breakdown

    def test_is_over_budget_no_limit(self):
        tracker = CostTracker(budget_limit=None)
        tracker.record("Market Analyst", "gpt-4o-mini", 10_000_000, 10_000_000)
        assert tracker.is_over_budget() is False

    def test_is_over_budget_under(self):
        tracker = CostTracker(budget_limit=10.0)
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 0)
        assert tracker.is_over_budget() is False

    def test_is_over_budget_over(self):
        tracker = CostTracker(budget_limit=0.01)
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert tracker.is_over_budget() is True

    def test_summary_contains_total(self):
        tracker = CostTracker()
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 0)
        summary = tracker.summary()
        assert "Total cost:" in summary
        assert "$" in summary

    def test_summary_with_budget(self):
        tracker = CostTracker(budget_limit=5.0)
        summary = tracker.summary()
        assert "Budget limit:" in summary

    def test_reset_clears_all(self):
        tracker = CostTracker()
        tracker.record("Market Analyst", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert tracker.total_cost() > 0
        tracker.reset()
        assert tracker.total_cost() == 0.0
        assert tracker.cost_by_agent() == {}

    def test_pricing_dict_has_common_models(self):
        for model in ("gpt-4o", "gpt-4o-mini", "gpt-4"):
            assert model in PRICING
            assert "input" in PRICING[model]
            assert "output" in PRICING[model]
