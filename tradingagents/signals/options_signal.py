"""Options-based long/short signal derivation from OptionsContext.

Shared by the divergence route and the pipeline runner to ensure consistent
behavior across both computation paths.
"""

from __future__ import annotations
from typing import Any, Literal

_BULL_THRESHOLD = 0.25
_BEAR_THRESHOLD = -0.25


def compute_options_value(options: Any) -> tuple[float, float]:
    """Compute the continuous [-1, +1] options signal value from an OptionsContext.

    Returns (value, confidence).
    value > 0 = bullish (call-heavy, low put skew)
    value < 0 = bearish (put-heavy, high put skew)

    Uses put/call ratio and 25-delta IV skew:
    - pcr_score = clamp((0.85 - pcr) * 2.0, -1, 1)    # < 0.85 -> bullish
    - skew_score = clamp(-iv_skew_25d * 3.0, -1, 1)   # negative skew (call-skew) -> bullish
    - value = 0.6 * pcr_score + 0.4 * skew_score

    Returns (0.0, 0.0) if both inputs are None.
    """
    if options is None:
        return 0.0, 0.0

    pcr = getattr(options, "put_call_ratio", None)
    iv_skew = getattr(options, "iv_skew_25d", None)
    iv_rank = getattr(options, "iv_rank_percentile", None)

    if pcr is None and iv_skew is None:
        return 0.0, 0.0

    def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, x))

    pcr_score = clamp((0.85 - float(pcr)) * 2.0) if pcr is not None else 0.0
    skew_score = clamp(-float(iv_skew) * 3.0) if iv_skew is not None else 0.0

    value = clamp(0.6 * pcr_score + 0.4 * skew_score)

    # Confidence: higher when both inputs are present + IV rank is informative
    confidence = 0.4
    if pcr is not None:
        confidence += 0.2
    if iv_skew is not None:
        confidence += 0.2
    if iv_rank is not None:
        confidence += 0.2

    return value, confidence


def classify_options_direction(
    value: float,
    previous_direction: Literal["BULL", "BEAR", "NEUTRAL"] | None = None,
    hysteresis_band: float = 0.10,
) -> tuple[Literal["BULL", "BEAR", "NEUTRAL"], int]:
    """Classify a continuous options value into BULL/BEAR/NEUTRAL with hysteresis.

    Args:
        value: continuous score in [-1, +1]
        previous_direction: last direction for this ticker (for hysteresis anchor)
        hysteresis_band: how much the value must cross past the threshold to flip
                         when the previous state is known

    Returns:
        (direction, impact) where impact = round(min(100, abs(value) * 100))

    Threshold logic:
    - Base thresholds: +/-0.25 (widened from old +/-0.15 to reduce noise)
    - If previous_direction is given, apply hysteresis: must cross the OPPOSITE
      threshold by `hysteresis_band` to flip to the opposite direction.
    """
    impact = int(min(100, round(abs(value) * 100)))

    if previous_direction is None:
        if value > 0.25:
            return "BULL", impact
        elif value < -0.25:
            return "BEAR", impact
        else:
            return "NEUTRAL", impact

    if previous_direction == "BULL":
        if value < -0.25 - hysteresis_band:
            return "BEAR", impact
        elif value > 0.25 - hysteresis_band:
            return "BULL", impact
        else:
            return "NEUTRAL", impact

    if previous_direction == "BEAR":
        if value > 0.25 + hysteresis_band:
            return "BULL", impact
        elif value < -0.25 + hysteresis_band:
            return "BEAR", impact
        else:
            return "NEUTRAL", impact

    # previous == NEUTRAL: clean thresholds
    if value > 0.25:
        return "BULL", impact
    elif value < -0.25:
        return "BEAR", impact
    else:
        return "NEUTRAL", impact


def derive_options_signal(
    options: Any,
    previous_direction: Literal["BULL", "BEAR", "NEUTRAL"] | None = None,
) -> tuple[Literal["BULL", "BEAR", "NEUTRAL"] | None, int | None]:
    """High-level wrapper: (value, confidence) -> (direction, impact).

    Returns (None, None) if the OptionsContext has no usable data.
    """
    if options is None:
        return None, None

    pcr = getattr(options, "put_call_ratio", None)
    iv_skew = getattr(options, "iv_skew_25d", None)
    iv_rank = getattr(options, "iv_rank_percentile", None)
    if pcr is None and iv_skew is None and iv_rank is None:
        return None, None

    value, _ = compute_options_value(options)
    direction, impact = classify_options_direction(value, previous_direction)
    return direction, impact
