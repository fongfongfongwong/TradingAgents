"""Structured debate round with confidence scoring for TradingAgents."""

from __future__ import annotations

import re
from pydantic import BaseModel, field_validator


class StructuredArgument(BaseModel):
    """A single structured argument from a debate participant."""

    agent_name: str
    position: str  # "bullish", "bearish", or "neutral"
    probability: float  # 0-1, predicted probability of positive return
    confidence: float  # 0-1, how confident the agent is
    reasoning: str
    key_evidence: list[str]
    fake_bet: float  # virtual dollars they'd wager, 0-1000

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("bullish", "bearish", "neutral"):
            raise ValueError(f"position must be 'bullish', 'bearish', or 'neutral', got '{v}'")
        return v

    @field_validator("probability")
    @classmethod
    def validate_probability(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"probability must be between 0 and 1, got {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {v}")
        return v

    @field_validator("fake_bet")
    @classmethod
    def validate_fake_bet(cls, v: float) -> float:
        if not 0.0 <= v <= 1000.0:
            raise ValueError(f"fake_bet must be between 0 and 1000, got {v}")
        return v


def _extract_field(text: str, field_name: str, default: str = "") -> str:
    """Extract a field value from LLM text output using regex."""
    # Try "Field: value" or "Field = value" patterns
    patterns = [
        rf"(?i){field_name}\s*[:=]\s*(.+?)(?:\n|$)",
        rf"(?i)\*\*{field_name}\*\*\s*[:=]\s*(.+?)(?:\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return default


def _extract_float(text: str, field_name: str, default: float = 0.5) -> float:
    """Extract a float field from LLM text output."""
    raw = _extract_field(text, field_name)
    if not raw:
        return default
    # Handle percentage format like "75%" -> 0.75
    pct_match = re.search(r"([\d.]+)\s*%", raw)
    if pct_match:
        try:
            return float(pct_match.group(1)) / 100.0
        except ValueError:
            return default
    # Handle plain float
    float_match = re.search(r"[\d.]+", raw)
    if float_match:
        try:
            val = float(float_match.group())
            # If value > 1 and looks like a percentage, normalize
            if val > 1.0 and field_name.lower() in ("probability", "confidence"):
                val = val / 100.0
            return val
        except ValueError:
            return default
    return default


def _extract_list(text: str, field_name: str) -> list[str]:
    """Extract a list field from LLM text output."""
    # Find the section starting with the field name
    pattern = rf"(?i){field_name}\s*[:=]\s*\n?((?:\s*[-*]\s*.+\n?)+)"
    match = re.search(pattern, text)
    if match:
        items_text = match.group(1)
        items = re.findall(r"[-*]\s*(.+?)(?:\n|$)", items_text)
        return [item.strip() for item in items if item.strip()]

    # Try inline comma-separated or semicolon-separated
    raw = _extract_field(text, field_name)
    if raw:
        # Split on commas or semicolons
        items = re.split(r"[;,]", raw)
        return [item.strip() for item in items if item.strip()]

    return []


def _extract_position(text: str) -> str:
    """Extract position from text, inferring from context if needed."""
    raw = _extract_field(text, "position")
    if raw:
        lower = raw.lower()
        if "bull" in lower:
            return "bullish"
        if "bear" in lower:
            return "bearish"
        if "neutral" in lower:
            return "neutral"

    # Infer from the overall text
    lower_text = text.lower()
    bull_signals = sum(1 for w in ["bullish", "buy", "long", "upside", "growth"] if w in lower_text)
    bear_signals = sum(1 for w in ["bearish", "sell", "short", "downside", "risk"] if w in lower_text)

    if bull_signals > bear_signals:
        return "bullish"
    if bear_signals > bull_signals:
        return "bearish"
    return "neutral"


def parse_structured_argument(llm_output: str) -> StructuredArgument:
    """Parse structured data from LLM text output.

    Attempts to extract structured fields using regex patterns. If parsing
    fails for any field, returns sensible defaults with low confidence.

    Args:
        llm_output: Raw text output from an LLM debate participant.

    Returns:
        A StructuredArgument with extracted or default values.
    """
    agent_name = _extract_field(llm_output, "agent_name") or _extract_field(llm_output, "agent")
    if not agent_name:
        # Try to infer from common prefixes
        for prefix in ("Bull Analyst:", "Bear Analyst:", "Neutral Analyst:"):
            if prefix.lower() in llm_output.lower():
                agent_name = prefix.rstrip(":")
                break
        else:
            agent_name = "unknown_agent"

    position = _extract_position(llm_output)
    probability = _extract_float(llm_output, "probability", default=0.5)
    confidence = _extract_float(llm_output, "confidence", default=0.3)
    reasoning = _extract_field(llm_output, "reasoning") or llm_output[:500]
    key_evidence = _extract_list(llm_output, "key_evidence") or _extract_list(llm_output, "evidence")
    fake_bet = _extract_float(llm_output, "fake_bet", default=100.0)

    # Clamp values to valid ranges
    probability = max(0.0, min(1.0, probability))
    confidence = max(0.0, min(1.0, confidence))
    fake_bet = max(0.0, min(1000.0, fake_bet))

    if not key_evidence:
        key_evidence = ["No structured evidence extracted"]

    return StructuredArgument(
        agent_name=agent_name,
        position=position,
        probability=probability,
        confidence=confidence,
        reasoning=reasoning,
        key_evidence=key_evidence,
        fake_bet=fake_bet,
    )
