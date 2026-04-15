"""Tiered Screening Engine (Feature F2).

Classifies each ticker into Tier 1 (FULL), Tier 2 (QUICK), or Tier 3 (SCREEN)
based on volatility, momentum, options flow, and news signals. Computes a
baseline factor_score in [-1, 1] from medium-term momentum.
"""

from __future__ import annotations

from tradingagents.schemas.v3 import ScreeningResult, Tier, TickerBriefing


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def _check_tier1(briefing: TickerBriefing) -> list[str]:
    """Return trigger reasons if ANY Tier 1 condition fires."""
    reasons: list[str] = []
    p = briefing.price

    # 1. Price moved > 2x ATR
    if p.atr_14 > 0 and p.price > 0:
        atr_pct = (p.atr_14 / p.price) * 100
        if abs(p.change_1d_pct) > 2 * atr_pct:
            reasons.append("price_move_2x_atr")

    # 2. Extreme RSI
    if p.rsi_14 < 25:
        reasons.append("rsi_extreme_oversold")
    elif p.rsi_14 > 75:
        reasons.append("rsi_extreme_overbought")

    # 3. News event flags
    if briefing.news.event_flags:
        reasons.append("news_event_flag")

    # 4. Extreme options skew
    pcr = briefing.options.put_call_ratio
    if pcr is not None:
        if pcr > 1.5:
            reasons.append("options_pcr_high")
        elif pcr < 0.5:
            reasons.append("options_pcr_low")

    # 5. Unusual options activity
    if briefing.options.unusual_activity_summary:
        reasons.append("unusual_options_activity")

    return reasons


def _check_tier2(briefing: TickerBriefing) -> list[str]:
    """Return trigger reasons if ANY Tier 2 condition fires."""
    reasons: list[str] = []
    p = briefing.price

    # 1. Extended RSI
    if p.rsi_14 < 35:
        reasons.append("rsi_extended_oversold")
    elif p.rsi_14 > 65:
        reasons.append("rsi_extended_overbought")

    # 2. MACD crossover within 3 days
    if p.macd_crossover_days <= 3:
        reasons.append("macd_crossover_recent")

    # 3. High volume
    if p.volume_vs_avg_20d > 1.5:
        reasons.append("high_volume")

    # 4. Price moved > 1x ATR
    if p.atr_14 > 0 and p.price > 0:
        atr_pct = (p.atr_14 / p.price) * 100
        if abs(p.change_1d_pct) > atr_pct:
            reasons.append("price_move_1x_atr")

    return reasons


def _compute_factor_score(briefing: TickerBriefing) -> float:
    """Compute momentum-based factor score in [-1, 1].

    momentum = (change_5d + change_20d) / 2, capped at +/-20%, normalized.
    """
    raw = (briefing.price.change_5d_pct + briefing.price.change_20d_pct) / 2.0
    capped = _clamp(raw, -20.0, 20.0)
    return capped / 20.0


def screen_ticker(briefing: TickerBriefing) -> ScreeningResult:
    """Classify a ticker into Tier 1 (full), Tier 2 (quick), or Tier 3 (screen).

    Also computes a factor_score (momentum composite, range -1 to +1).
    """
    factor_score = _compute_factor_score(briefing)

    # Check Tier 1 first (ANY trigger)
    t1_reasons = _check_tier1(briefing)
    if t1_reasons:
        return ScreeningResult(
            ticker=briefing.ticker,
            tier=Tier.FULL,
            trigger_reasons=t1_reasons,
            factor_score=factor_score,
        )

    # Check Tier 2 (ANY trigger)
    t2_reasons = _check_tier2(briefing)
    if t2_reasons:
        return ScreeningResult(
            ticker=briefing.ticker,
            tier=Tier.QUICK,
            trigger_reasons=t2_reasons,
            factor_score=factor_score,
        )

    # Default: Tier 3
    return ScreeningResult(
        ticker=briefing.ticker,
        tier=Tier.SCREEN,
        trigger_reasons=["default_screen"],
        factor_score=factor_score,
    )


if __name__ == "__main__":
    from tradingagents.schemas.v3 import (
        PriceContext, OptionsContext, NewsContext, SocialContext,
        MacroContext, EventCalendar, Regime,
    )

    # Test 1: Tier 1 (extreme RSI)
    t1_briefing = TickerBriefing(
        ticker="TEST1", date="2026-04-05", snapshot_id="snap_test",
        price=PriceContext(
            price=100, change_1d_pct=5.0, change_5d_pct=10.0, change_20d_pct=15.0,
            sma_20=95, sma_50=90, sma_200=85, rsi_14=78.0, macd_above_signal=True,
            macd_crossover_days=1, bollinger_position="upper_third",
            volume_vs_avg_20d=2.0, atr_14=3.0, data_age_seconds=10,
        ),
        options=OptionsContext(), news=NewsContext(), social=SocialContext(),
        macro=MacroContext(), events=EventCalendar(),
    )
    r1 = screen_ticker(t1_briefing)
    assert r1.tier == Tier.FULL, f"Expected FULL, got {r1.tier}"
    assert any("rsi" in r.lower() for r in r1.trigger_reasons)
    print(f"Test 1 PASSED: Tier 1 (reasons: {r1.trigger_reasons})")

    # Test 2: Tier 3 (normal)
    t3_briefing = TickerBriefing(
        ticker="TEST3", date="2026-04-05", snapshot_id="snap_test",
        price=PriceContext(
            price=100, change_1d_pct=0.5, change_5d_pct=1.0, change_20d_pct=2.0,
            sma_20=99, sma_50=98, sma_200=95, rsi_14=52.0, macd_above_signal=True,
            macd_crossover_days=10, bollinger_position="middle_third",
            volume_vs_avg_20d=1.0, atr_14=2.0, data_age_seconds=10,
        ),
        options=OptionsContext(), news=NewsContext(), social=SocialContext(),
        macro=MacroContext(), events=EventCalendar(),
    )
    r3 = screen_ticker(t3_briefing)
    assert r3.tier == Tier.SCREEN, f"Expected SCREEN, got {r3.tier}"
    print("Test 2 PASSED: Tier 3 (normal)")

    # Test 3: Factor score range
    assert -1.0 <= r1.factor_score <= 1.0
    assert -1.0 <= r3.factor_score <= 1.0
    print("Test 3 PASSED: Factor scores in [-1, 1]")

    print("\nAll tests PASSED")
