"""Cost Tracker - Records and reports LLM usage costs.

Two APIs live in this module:

1. The legacy per-instance ``CostTracker`` used by the v1 gateway (records
   usage grouped by agent/tier, configurable soft budget).
2. The G4 module-level tracker (see :func:`get_cost_tracker` below) which
   enforces hard daily and per-ticker budgets and is consulted by the v3
   debate agents before every LLM call.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

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
    # Anthropic — include both short aliases and dated IDs
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-1-20250805": {"input": 15.00, "output": 75.00},
    "claude-opus-4-5": {"input": 15.00, "output": 75.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
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


# ---------------------------------------------------------------------------
# G4: Module-level tracker with budget enforcement
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)


# Anthropic pricing (per 1M tokens, USD). Placeholder 0.0 for other providers.
MODEL_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    "claude-opus-4-1-20250805": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the USD cost for a single LLM call.

    Unknown models log a warning and return ``0.0`` so cost tracking can
    never crash the pipeline.
    """
    pricing = MODEL_PRICING_USD_PER_1M.get(model)
    if pricing is None:
        _logger.warning("Unknown model %s in cost pricing; cost=0.0", model)
        return 0.0
    return (
        (input_tokens / 1_000_000) * pricing["input"]
        + (output_tokens / 1_000_000) * pricing["output"]
    )


class BudgetExceededError(Exception):
    """Raised when a ticker or the day exceeds its configured USD budget."""


@dataclass(frozen=True)
class CostEntry:
    """A single recorded LLM call for budget bookkeeping."""

    ticker: str
    agent_name: str  # "thesis", "antithesis", "base_rate", "synthesis"
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime


class ModuleCostTracker:
    """Thread-safe per-day + per-ticker cost accumulator.

    This is intentionally a different class from the legacy ``CostTracker``
    above so we don't break existing call sites. It is the tracker exposed
    by :func:`get_cost_tracker`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[CostEntry] = []

    # -- internal helpers ---------------------------------------------------

    def _read_runtime_budget(self) -> tuple[float, float]:
        """Return (daily_budget_usd, per_ticker_budget_usd).

        Imported lazily to avoid a circular import during module load.
        """
        try:
            from tradingagents.api.routes.config import get_runtime_config

            cfg = get_runtime_config()
            return float(cfg.budget_daily_usd), float(cfg.budget_per_ticker_usd)
        except Exception as exc:  # pragma: no cover -- defensive
            _logger.warning(
                "Failed to read runtime budget (%s); using 0 (disabled).", exc
            )
            return 0.0, 0.0

    # -- public API ---------------------------------------------------------

    def record(self, entry: CostEntry) -> None:
        """Append an entry to the accumulator."""
        with self._lock:
            self._entries.append(entry)

    def daily_total_usd(self, day: date | None = None) -> float:
        """Return the total spent on *day* (default: today)."""
        target = day or date.today()
        with self._lock:
            return sum(
                e.cost_usd for e in self._entries if e.timestamp.date() == target
            )

    def ticker_total_usd(self, ticker: str, day: date | None = None) -> float:
        """Return the total spent on *ticker* during *day* (default: today)."""
        target = day or date.today()
        with self._lock:
            return sum(
                e.cost_usd
                for e in self._entries
                if e.ticker == ticker and e.timestamp.date() == target
            )

    def daily_total_by_agent(self, day: date | None = None) -> dict[str, float]:
        """Return ``{agent_name: cost_usd}`` for *day* (default: today)."""
        target = day or date.today()
        result: dict[str, float] = {}
        with self._lock:
            for e in self._entries:
                if e.timestamp.date() != target:
                    continue
                result[e.agent_name] = result.get(e.agent_name, 0.0) + e.cost_usd
        return result

    def daily_total_by_ticker(self, day: date | None = None) -> dict[str, float]:
        """Return ``{ticker: cost_usd}`` for *day* (default: today)."""
        target = day or date.today()
        result: dict[str, float] = {}
        with self._lock:
            for e in self._entries:
                if e.timestamp.date() != target:
                    continue
                result[e.ticker] = result.get(e.ticker, 0.0) + e.cost_usd
        return result

    def daily_total_by_model(self, day: date | None = None) -> dict[str, float]:
        """Return ``{model: cost_usd}`` for *day* (default: today)."""
        target = day or date.today()
        result: dict[str, float] = {}
        with self._lock:
            for e in self._entries:
                if e.timestamp.date() != target:
                    continue
                result[e.model] = result.get(e.model, 0.0) + e.cost_usd
        return result

    def call_count_today(self, day: date | None = None) -> int:
        """Return the number of LLM calls recorded on *day* (default: today)."""
        target = day or date.today()
        with self._lock:
            return sum(1 for e in self._entries if e.timestamp.date() == target)

    def daily_totals_range(self, days: int) -> list[dict[str, Any]]:
        """Return a list of ``{date, total_usd, call_count}`` for the last *days* days.

        Sorted ascending by date. ``days`` is clamped to [1, 90].
        """
        from datetime import timedelta

        days = max(1, min(90, int(days)))
        today = date.today()
        start = today - timedelta(days=days - 1)
        # Seed result with zero entries so gaps are visible.
        totals: dict[date, dict[str, float]] = {
            start + timedelta(days=i): {"total_usd": 0.0, "call_count": 0}
            for i in range(days)
        }
        with self._lock:
            for e in self._entries:
                d = e.timestamp.date()
                if d < start or d > today:
                    continue
                bucket = totals[d]
                bucket["total_usd"] += e.cost_usd
                bucket["call_count"] += 1
        return [
            {
                "date": d.isoformat(),
                "total_usd": round(v["total_usd"], 6),
                "call_count": int(v["call_count"]),
            }
            for d, v in sorted(totals.items())
        ]

    def check_budget(self, ticker: str) -> None:
        """Raise :class:`BudgetExceededError` if *ticker* has no budget left.

        Enforces both the daily and the per-ticker budgets configured in
        :class:`RuntimeConfig`. A budget of ``0`` disables that check.
        """
        daily_limit, ticker_limit = self._read_runtime_budget()
        daily_spent = self.daily_total_usd()
        ticker_spent = self.ticker_total_usd(ticker)

        if daily_limit > 0 and daily_spent >= daily_limit:
            raise BudgetExceededError(
                f"daily budget exceeded: ${daily_spent:.4f} >= ${daily_limit:.2f}"
            )
        if ticker_limit > 0 and ticker_spent >= ticker_limit:
            raise BudgetExceededError(
                f"per-ticker budget exceeded for {ticker}: "
                f"${ticker_spent:.4f} >= ${ticker_limit:.2f}"
            )

    def reset(self) -> None:
        """Clear all recorded entries. Intended for tests."""
        with self._lock:
            self._entries.clear()


_module_tracker = ModuleCostTracker()


def get_cost_tracker() -> ModuleCostTracker:
    """Return the process-wide cost tracker singleton."""
    return _module_tracker
