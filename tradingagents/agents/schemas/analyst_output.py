"""Structured output schemas for analyst agents.

These Pydantic models provide validated, typed output for each analyst
so downstream consumers (debate agents, portfolio manager) can work
with structured signals instead of raw text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class FactorSignal(BaseModel):
    """A single directional signal produced by an analyst."""

    name: str = Field(..., description="Human-readable factor name, e.g. 'put_call_ratio'")
    value: float = Field(..., ge=-1.0, le=1.0, description="Signal strength from -1 (max bearish) to +1 (max bullish)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the signal, 0 = no confidence, 1 = certain")
    direction: Literal["bullish", "bearish", "neutral"] = Field(..., description="Directional interpretation")
    source: str = Field(..., description="Data source that produced this signal")
    timestamp: Optional[datetime] = Field(default=None, description="When the underlying data was observed")

    @field_validator("direction")
    @classmethod
    def direction_must_be_valid(cls, v: str) -> str:
        allowed = {"bullish", "bearish", "neutral"}
        if v not in allowed:
            raise ValueError(f"direction must be one of {allowed}, got '{v}'")
        return v


class AnalystReport(BaseModel):
    """Structured report produced by any analyst agent."""

    ticker: str = Field(..., description="Ticker symbol analyzed")
    analyst_type: str = Field(..., description="Type of analyst, e.g. 'options', 'macro', 'market'")
    text_report: str = Field(..., description="Full markdown text of the analyst report")
    signals: list[FactorSignal] = Field(default_factory=list, description="Extracted factor signals")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence in the analysis")
    sources_cited: list[str] = Field(default_factory=list, description="Data sources referenced")
    insufficient_data: bool = Field(default=False, description="True when data was too sparse for meaningful analysis")
