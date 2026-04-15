"""Deterministic macro regime classifier.

Classifies the market regime from a small set of macro signals: VIX level,
2y-10y yield curve spread (basis points), and SPY 20-day return (percent).

The rules are intentionally simple and deterministic so that the output is
reproducible across runs and testable with a truth table. Missing inputs are
treated as uninformative and lean the result toward ``TRANSITIONING``.
"""

from __future__ import annotations

from tradingagents.schemas.v3 import Regime

# Thresholds (kept at module level for visibility and easy tuning).
_VIX_CRISIS: float = 30.0
_VIX_BEARISH: float = 22.0
_VIX_RISK_ON_MAX: float = 16.0
_VIX_BULLISH_MAX: float = 20.0

_YIELD_CURVE_DEEP_INVERSION_BPS: float = -50.0

_SPY_20D_CRISIS_PCT: float = -3.0
_SPY_20D_BEARISH_PCT: float = -1.0
_SPY_20D_RISK_ON_PCT: float = 2.0
_SPY_20D_BULLISH_PCT: float = 0.0


def classify_regime(
    vix_level: float | None,
    yield_curve_2y10y_bps: float | None,
    spy_20d_pct: float | None,
) -> Regime:
    """Classify the macro regime from VIX, yield curve, and SPY momentum.

    Rules (evaluated in order — first match wins):

    1. ``RISK_OFF`` — ``VIX >= 30`` OR
       (``yield_curve < -50 bps`` AND ``spy_20d_pct < -3``).
    2. ``BEARISH_BIAS`` — ``VIX >= 22`` AND ``spy_20d_pct < -1``.
    3. ``RISK_ON`` — ``VIX < 16`` AND ``spy_20d_pct > 2`` AND ``yield_curve > 0``.
    4. ``BULLISH_BIAS`` — ``VIX < 20`` AND ``spy_20d_pct > 0``.
    5. ``TRANSITIONING`` — otherwise.

    Missing inputs (``None``) never satisfy a numeric comparison, so regimes
    that depend on the missing signal cannot be selected. With all inputs
    ``None`` the classifier returns ``TRANSITIONING``.
    """
    # Rule 1: RISK_OFF
    if vix_level is not None and vix_level >= _VIX_CRISIS:
        return Regime.RISK_OFF
    if (
        yield_curve_2y10y_bps is not None
        and spy_20d_pct is not None
        and yield_curve_2y10y_bps < _YIELD_CURVE_DEEP_INVERSION_BPS
        and spy_20d_pct < _SPY_20D_CRISIS_PCT
    ):
        return Regime.RISK_OFF

    # Rule 2: BEARISH_BIAS
    if (
        vix_level is not None
        and spy_20d_pct is not None
        and vix_level >= _VIX_BEARISH
        and spy_20d_pct < _SPY_20D_BEARISH_PCT
    ):
        return Regime.BEARISH_BIAS

    # Rule 3: RISK_ON
    if (
        vix_level is not None
        and spy_20d_pct is not None
        and yield_curve_2y10y_bps is not None
        and vix_level < _VIX_RISK_ON_MAX
        and spy_20d_pct > _SPY_20D_RISK_ON_PCT
        and yield_curve_2y10y_bps > 0
    ):
        return Regime.RISK_ON

    # Rule 4: BULLISH_BIAS
    if (
        vix_level is not None
        and spy_20d_pct is not None
        and vix_level < _VIX_BULLISH_MAX
        and spy_20d_pct > _SPY_20D_BULLISH_PCT
    ):
        return Regime.BULLISH_BIAS

    # Rule 5: fallback
    return Regime.TRANSITIONING
