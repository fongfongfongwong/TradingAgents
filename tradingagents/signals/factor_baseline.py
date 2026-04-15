"""Factor Baseline Model -- pure-computation factor scoring.

Computes a composite factor score from a TickerBriefing using three
factor categories (Momentum, Quality, Value) with fixed weights.
No LLM calls, no network I/O.

Spec (F3):
  Momentum(0.5): price>SMA200 -> +0.3, RSI zone +/-0.2, MACD +/-0.2, 20d change +/-0.3
  Quality(0.3):  volume +/-0.5, bollinger +/-0.25
  Value(0.2):    price vs SMA50 +/-0.5
  Composite = mom*0.5 + qual*0.3 + val*0.2  clamped [-1,1]
  Signal: >0.2 = BUY, <-0.2 = SHORT, else HOLD
"""

from __future__ import annotations

from tradingagents.schemas.v3 import Signal, TickerBriefing

# ── Weight constants ─────────────────────────────────────────────

_MOMENTUM_WEIGHT: float = 0.5
_QUALITY_WEIGHT: float = 0.3
_VALUE_WEIGHT: float = 0.2


# ── Helper ───────────────────────────────��───────────────────────


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """Clamp *value* to [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# ── Sub-factor scorers ───────────────────────────────────────────


def _score_momentum(briefing: TickerBriefing) -> float:
    """Momentum factor score in [-1, 1].

    - Price > SMA200 -> +0.3, else -0.3
    - RSI > 60 -> +0.2, RSI < 40 -> -0.2, else 0
    - MACD above signal -> +0.2, else -0.2
    - 20d change > 5% -> +0.3, < -5% -> -0.3, else 0
    """
    p = briefing.price
    score = 0.0

    if p.price > p.sma_200:
        score += 0.3
    else:
        score -= 0.3

    if p.rsi_14 > 60:
        score += 0.2
    elif p.rsi_14 < 40:
        score -= 0.2

    if p.macd_above_signal:
        score += 0.2
    else:
        score -= 0.2

    if p.change_20d_pct > 5.0:
        score += 0.3
    elif p.change_20d_pct < -5.0:
        score -= 0.3

    return _clamp(score)


def _score_quality(briefing: TickerBriefing) -> float:
    """Quality factor score in [-1, 1].

    - Volume vs 20d avg > 1.2 -> +0.5, < 0.8 -> -0.5, else 0
    - Bollinger upper_third -> +0.25, lower_third -> -0.25, else 0
    """
    p = briefing.price
    score = 0.0

    if p.volume_vs_avg_20d > 1.2:
        score += 0.5
    elif p.volume_vs_avg_20d < 0.8:
        score -= 0.5

    if p.bollinger_position == "upper_third":
        score += 0.25
    elif p.bollinger_position == "lower_third":
        score -= 0.25

    return _clamp(score)


def _score_value(briefing: TickerBriefing) -> float:
    """Value factor score in [-1, 1].

    - Price > SMA50 -> +0.5, else -0.5
    """
    if briefing.price.price > briefing.price.sma_50:
        return 0.5
    return -0.5


# ── Public API ─────────────────────────────────────────��─────────


def compute_factor_score(briefing: TickerBriefing) -> dict:
    """Compute composite factor score from a materialized briefing.

    Returns
    -------
    dict with keys:
        ticker, momentum_score, quality_score, value_score,
        composite_score, signal, components
    """
    momentum = _score_momentum(briefing)
    quality = _score_quality(briefing)
    value = _score_value(briefing)

    composite = _clamp(
        momentum * _MOMENTUM_WEIGHT
        + quality * _QUALITY_WEIGHT
        + value * _VALUE_WEIGHT,
    )

    if composite > 0.2:
        signal = Signal.BUY
    elif composite < -0.2:
        signal = Signal.SHORT
    else:
        signal = Signal.HOLD

    return {
        "ticker": briefing.ticker,
        "momentum_score": momentum,
        "quality_score": quality,
        "value_score": value,
        "composite_score": composite,
        "signal": signal,
        "components": {
            "momentum_weight": _MOMENTUM_WEIGHT,
            "quality_weight": _QUALITY_WEIGHT,
            "value_weight": _VALUE_WEIGHT,
        },
    }
