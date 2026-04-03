"""Token budget management for multi-source context engineering."""

from __future__ import annotations

from tradingagents.context.token_counter import TokenCounter

DEFAULT_ALLOCATIONS: dict[str, float] = {
    "market_data": 0.20,
    "news": 0.20,
    "fundamentals": 0.20,
    "divergence": 0.15,
    "macro": 0.10,
    "social": 0.10,
    "other": 0.05,
}


class TokenBudgetManager:
    """Manage per-category token budgets and truncate context to fit.

    Parameters
    ----------
    total_budget : int
        Maximum number of tokens for the combined context.
    allocations : dict | None
        Mapping of ``{category: fraction}`` where fractions should sum
        to 1.0.  Falls back to :data:`DEFAULT_ALLOCATIONS` when *None*.
    """

    def __init__(
        self,
        total_budget: int = 8000,
        allocations: dict[str, float] | None = None,
    ) -> None:
        self.total_budget = total_budget
        self.allocations = dict(allocations) if allocations else dict(DEFAULT_ALLOCATIONS)
        self._counter = TokenCounter(method="approximate")
        self._last_usage: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allocate(self, category: str) -> int:
        """Return the token budget for *category*."""
        fraction = self.allocations.get(category, self.allocations.get("other", 0.05))
        return int(self.total_budget * fraction)

    def fit_to_budget(self, text: str, budget: int) -> str:
        """Truncate *text* so its token count stays within *budget*.

        Truncation is performed at sentence boundaries when possible.
        A ``[truncated]`` marker is appended when text is shortened.
        """
        if not text:
            return text
        if self._counter.count(text) <= budget:
            return text

        # Approximate character limit from token budget.
        char_limit = budget * 4

        truncated = text[:char_limit]

        # Try to cut at the last sentence boundary.
        for sep in (".  ", ". ", ".\n", "! ", "? "):
            idx = truncated.rfind(sep)
            if idx > 0:
                truncated = truncated[: idx + 1]
                break

        return truncated.rstrip() + " [truncated]"

    def prepare_context(
        self,
        data: dict[str, str],
        priorities: dict[str, float] | None = None,
    ) -> str:
        """Combine multiple data categories into a single context string.

        Parameters
        ----------
        data : dict[str, str]
            Mapping of ``{category: text_content}``.
        priorities : dict[str, float] | None
            Optional override allocations used instead of the instance
            defaults.  Fractions need not sum to 1.0 -- they are
            normalised internally.

        Returns
        -------
        str
            The combined context, guaranteed to fit within
            :attr:`total_budget` tokens.
        """
        allocs = self._resolve_allocations(data, priorities)
        self._last_usage = {}

        parts: list[str] = []
        for category, text in data.items():
            cat_budget = int(self.total_budget * allocs.get(category, 0.05))
            fitted = self.fit_to_budget(text, cat_budget)
            self._last_usage[category] = self._counter.count(fitted)
            if fitted:
                parts.append(f"## {category}\n{fitted}")

        combined = "\n\n".join(parts)

        # Final safety trim if combined exceeds total budget.
        if self._counter.count(combined) > self.total_budget:
            combined = self.fit_to_budget(combined, self.total_budget)

        return combined

    def stats(self) -> dict:
        """Return allocation and usage statistics."""
        return {
            "total_budget": self.total_budget,
            "allocations": dict(self.allocations),
            "last_usage": dict(self._last_usage),
            "total_used": sum(self._last_usage.values()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_allocations(
        self,
        data: dict[str, str],
        priorities: dict[str, float] | None,
    ) -> dict[str, float]:
        """Return normalised allocation fractions for the given data keys."""
        if priorities:
            total = sum(priorities.values()) or 1.0
            return {k: v / total for k, v in priorities.items()}
        # Use instance allocations, filling missing categories with "other".
        return {cat: self.allocations.get(cat, self.allocations.get("other", 0.05)) for cat in data}
