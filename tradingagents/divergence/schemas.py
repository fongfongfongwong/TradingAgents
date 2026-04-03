"""Divergence Engine data schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


DIMENSIONS = ("institutional", "options", "price_action", "news", "retail")


class RegimeState(str, Enum):
    """Market regime classification."""

    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    TRANSITIONING = "TRANSITIONING"


class DimensionScore(BaseModel):
    """A single dimension's divergence score."""

    dimension: str
    value: float = Field(ge=-1.0, le=1.0, description="Normalized score in [-1, +1]")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in [0, 1]")
    sources: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dimension")
    @classmethod
    def _validate_dimension(cls, v: str) -> str:
        if v not in DIMENSIONS:
            raise ValueError(f"dimension must be one of {DIMENSIONS}, got {v!r}")
        return v


class DivergenceVector(BaseModel):
    """5-dimension divergence vector for a single ticker at a point in time."""

    ticker: str
    timestamp: datetime
    regime: RegimeState
    dimensions: dict[str, DimensionScore]
    composite_score: float = Field(
        ge=-1.0, le=1.0, description="Weighted composite in [-1, +1]"
    )
    weights: dict[str, float]

    # -- public helpers --------------------------------------------------------

    def to_agent_summary(self) -> str:
        """Human-readable summary suitable for LLM agent consumption."""
        lines = [
            f"Divergence Vector for {self.ticker} ({self.timestamp.strftime('%Y-%m-%d %H:%M')})",
            f"Regime: {self.regime.value}",
            f"Composite Score: {self.composite_score:+.3f}",
            "",
            "Dimensions:",
        ]
        for name in DIMENSIONS:
            if name in self.dimensions:
                d = self.dimensions[name]
                lines.append(
                    f"  {name:15s}  value={d.value:+.3f}  "
                    f"confidence={d.confidence:.2f}  "
                    f"weight={self.weights.get(name, 0):.2f}  "
                    f"sources={d.sources}"
                )
        strongest = self.strongest_signal()
        weakest = self.weakest_signal()
        lines.append("")
        lines.append(f"Strongest signal: {strongest.dimension} ({strongest.value:+.3f})")
        lines.append(f"Weakest signal:   {weakest.dimension} ({weakest.value:+.3f})")
        lines.append(f"Divergent: {self.is_divergent()}")
        return "\n".join(lines)

    def strongest_signal(self) -> DimensionScore:
        """Return the dimension with the largest absolute value."""
        return max(self.dimensions.values(), key=lambda d: abs(d.value))

    def weakest_signal(self) -> DimensionScore:
        """Return the dimension with the smallest absolute value."""
        return min(self.dimensions.values(), key=lambda d: abs(d.value))

    def is_divergent(self, threshold: float = 0.3) -> bool:
        """True when dimensions disagree beyond *threshold*.

        Divergence is measured as the spread between the most bullish and
        most bearish dimension scores.
        """
        if not self.dimensions:
            return False
        values = [d.value for d in self.dimensions.values()]
        spread = max(values) - min(values)
        return spread > threshold
