"""Cost Tracker - Records and reports LLM usage costs."""

from __future__ import annotations

from dataclasses import dataclass, field

# Pricing per 1M tokens (USD) for common models.
PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    # Google
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # Fallback
    "default": {"input": 1.00, "output": 3.00},
}


@dataclass
class _UsageRecord:
    agent_name: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float


class CostTracker:
    """Tracks LLM usage and cost across agents and tiers."""

    def __init__(self, budget_limit: float | None = None) -> None:
        self.budget_limit = budget_limit
        self._records: list[_UsageRecord] = []

    # -- recording -----------------------------------------------------------

    def record(
        self,
        agent_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record a single LLM call's token usage."""
        pricing = PRICING.get(model, PRICING["default"])
        cost = (input_tokens / 1_000_000) * pricing["input"] + (
            output_tokens / 1_000_000
        ) * pricing["output"]
        self._records.append(
            _UsageRecord(
                agent_name=agent_name,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
            )
        )

    # -- queries -------------------------------------------------------------

    def total_cost(self) -> float:
        """Return total cost across all recorded usage."""
        return sum(r.cost for r in self._records)

    def cost_by_agent(self) -> dict[str, float]:
        """Return cost breakdown per agent name."""
        result: dict[str, float] = {}
        for r in self._records:
            result[r.agent_name] = result.get(r.agent_name, 0.0) + r.cost
        return result

    def cost_by_tier(self) -> dict[str, float]:
        """Return cost breakdown per model tier.

        Requires the router's AGENT_TIER_MAP to classify agents.
        Unknown agents are grouped under 'reason'.
        """
        from .router import AGENT_TIER_MAP, ModelTier

        result: dict[str, float] = {}
        for r in self._records:
            tier = AGENT_TIER_MAP.get(r.agent_name, ModelTier.REASON).value
            result[tier] = result.get(tier, 0.0) + r.cost
        return result

    def is_over_budget(self) -> bool:
        """Return True if total cost exceeds the budget limit."""
        if self.budget_limit is None:
            return False
        return self.total_cost() > self.budget_limit

    def summary(self) -> str:
        """Return a human-readable cost summary."""
        lines = [f"Total cost: ${self.total_cost():.4f}"]
        if self.budget_limit is not None:
            lines.append(f"Budget limit: ${self.budget_limit:.4f}")
            lines.append(f"Over budget: {self.is_over_budget()}")
        agent_costs = self.cost_by_agent()
        if agent_costs:
            lines.append("Cost by agent:")
            for agent, cost in sorted(agent_costs.items()):
                lines.append(f"  {agent}: ${cost:.4f}")
        tier_costs = self.cost_by_tier()
        if tier_costs:
            lines.append("Cost by tier:")
            for tier, cost in sorted(tier_costs.items()):
                lines.append(f"  {tier}: ${cost:.4f}")
        return "\n".join(lines)

    def reset(self) -> None:
        """Clear all recorded usage."""
        self._records.clear()
