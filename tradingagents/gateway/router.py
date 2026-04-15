"""LLM Router - Routes agents to appropriate model tiers."""

from __future__ import annotations

from enum import Enum

from .cost_tracker import PRICING


class ModelTier(str, Enum):
    EXTRACT = "extract"
    REASON = "reason"
    DECIDE = "decide"


# Maps agent names to their processing tier.
AGENT_TIER_MAP: dict[str, ModelTier] = {
    # EXTRACT tier - data gathering and extraction
    "Market Analyst": ModelTier.EXTRACT,
    "Social Media Analyst": ModelTier.EXTRACT,
    "News Analyst": ModelTier.EXTRACT,
    "Fundamentals Analyst": ModelTier.EXTRACT,
    "Options Analyst": ModelTier.EXTRACT,
    "Macro Analyst": ModelTier.EXTRACT,
    # REASON tier - synthesis and argumentation
    "Bull Researcher": ModelTier.REASON,
    "Bear Researcher": ModelTier.REASON,
    # DECIDE tier - final decision-making
    "Research Manager": ModelTier.DECIDE,
    "Trader": ModelTier.DECIDE,
    "Aggressive Analyst": ModelTier.DECIDE,
    "Conservative Analyst": ModelTier.DECIDE,
    "Neutral Analyst": ModelTier.DECIDE,
    "Portfolio Manager": ModelTier.DECIDE,
}

DEFAULT_TIER_MODELS: dict[str, str] = {
    "extract": "gpt-4o-mini",
    "reason": "gpt-4o",
    "decide": "gpt-4o",
}


class LLMRouter:
    """Routes agents to the appropriate LLM model based on their tier."""

    def __init__(self, tier_config: dict | None = None) -> None:
        self.tier_models = dict(DEFAULT_TIER_MODELS)
        if tier_config:
            self.tier_models.update(tier_config)

    def get_tier(self, agent_name: str) -> ModelTier:
        """Return the tier for the given agent. Defaults to REASON for unknown agents."""
        return AGENT_TIER_MAP.get(agent_name, ModelTier.REASON)

    def get_model(self, agent_name: str) -> str:
        """Return the model name for the given agent based on its tier."""
        tier = self.get_tier(agent_name)
        return self.tier_models[tier.value]

    def estimate_cost(
        self, agent_name: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Estimate the USD cost for a call by the given agent."""
        model = self.get_model(agent_name)
        pricing = PRICING.get(model, PRICING.get("default", {"input": 0.0, "output": 0.0}))
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
