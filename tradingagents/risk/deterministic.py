"""Deterministic Risk Layer — NO LLM calls.

Applies hard limits, position sizing, stop-loss, and stress tests.
All computation is pure Python math. Zero external dependencies
beyond pydantic (via the v3 schemas).
"""

from __future__ import annotations

import math

from tradingagents.schemas.v3 import (
    Signal,
    StressTestResult,
    SynthesisOutput,
    RiskOutput,
)

# ── Hard Limits (from D4 Risk Manager research) ──────────────────────

MAX_POSITION_PCT: float = 0.02       # 2 % of NAV per position
MAX_SINGLE_LOSS_PCT: float = 0.01    # 1 % max loss per trade
STOP_LOSS_ATR_MULT: float = 2.0      # Stop at 2x ATR from entry

# ── Stress-test multipliers ──────────────────────────────────────────

_TECH_SECTORS = frozenset({"AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "NVDA", "TSLA", "AMD", "INTC"})

STRESS_SCENARIOS: tuple[tuple[str, float, float], ...] = (
    # (name, base_loss_multiplier, tech_override_multiplier | None)
    ("sector_shock_-5pct",     0.05, 0.05),
    ("rate_spike_+50bps",      0.01, 0.03),   # defensive=0.01, tech=0.03
    ("liquidity_drought",      0.02, 0.02),
    ("correlation_spike",      0.08, 0.08),
    ("vix_spike_to_40",        0.06, 0.06),
)


# ── Helpers ──────────────────────────────────────────────────────────


def _best_scenario_target(synthesis: SynthesisOutput) -> float:
    """Return the target price from the highest-probability scenario."""
    return max(synthesis.scenarios, key=lambda s: s.probability).target_price


def _estimate_price(synthesis: SynthesisOutput) -> float:
    """Estimate current price from scenarios and expected value.

    We derive it from the best scenario:
        target = price * (1 + return_pct / 100)
        => price = target / (1 + return_pct / 100)

    Falls back to target_price itself when return_pct is ~0.
    """
    best = max(synthesis.scenarios, key=lambda s: s.probability)
    if abs(best.return_pct) < 0.001:
        return best.target_price
    return best.target_price / (1.0 + best.return_pct / 100.0)


def _is_tech(ticker: str) -> bool:
    return ticker.upper() in _TECH_SECTORS


def _run_stress_tests(
    ticker: str,
    position_value: float,
    nav: float,
) -> list[StressTestResult]:
    """Run all five deterministic stress scenarios."""
    results: list[StressTestResult] = []
    is_tech = _is_tech(ticker)

    for name, base_mult, tech_mult in STRESS_SCENARIOS:
        multiplier = tech_mult if is_tech else base_mult
        loss_usd = position_value * multiplier
        loss_pct = loss_usd / nav if nav > 0 else 0.0
        results.append(
            StressTestResult(
                scenario=name,
                estimated_loss_usd=round(loss_usd, 2),
                estimated_loss_pct=round(loss_pct, 6),
            )
        )
    return results


def _risk_rating(stress_tests: list[StressTestResult]) -> str:
    """Derive rating from worst stress-test loss as pct of NAV."""
    worst_pct = max(st.estimated_loss_pct for st in stress_tests) if stress_tests else 0.0
    if worst_pct > 0.03:
        return "EXTREME"
    if worst_pct > 0.02:
        return "HIGH"
    if worst_pct > 0.01:
        return "MEDIUM"
    return "LOW"


# ── Main entry point ────────────────────────────────────────────────


def evaluate_risk(
    synthesis: SynthesisOutput,
    portfolio_nav: float = 100_000.0,
    existing_positions: dict[str, float] | None = None,
) -> RiskOutput:
    """Deterministic risk evaluation -- NO LLM calls.

    Applies hard limits, position sizing, stop-loss, and stress tests.
    All computation is pure Python math.

    Args:
        synthesis: Output from the Synthesis Agent.
        portfolio_nav: Current portfolio net-asset value in USD.
        existing_positions: Map of ticker -> current position value (USD).
            Used for concentration checks. ``None`` treated as empty.

    Returns:
        A fully-populated ``RiskOutput``.
    """
    existing_positions = existing_positions or {}
    ticker = synthesis.ticker
    price = _estimate_price(synthesis)
    target_price = _best_scenario_target(synthesis)

    # ── HOLD or zero-conviction → flat output ────────────────────────
    if synthesis.signal == Signal.HOLD or synthesis.conviction <= 0 or price <= 0:
        empty_stress = _run_stress_tests(ticker, 0.0, portfolio_nav)
        return RiskOutput(
            ticker=ticker,
            signal=synthesis.signal,
            risk_rating="LOW",
            base_shares=0,
            volatility_adjusted_shares=0,
            concentration_adjusted_shares=0,
            event_adjusted_shares=0,
            final_shares=0,
            position_value_usd=0.0,
            position_pct_of_portfolio=0.0,
            binding_constraint="signal_hold",
            stop_loss_price=0.0,
            stop_loss_type="volatility",
            take_profit_price=0.0,
            risk_reward_ratio=0.0,
            max_loss_usd=0.0,
            max_loss_pct_portfolio=0.0,
            stress_tests=empty_stress,
            risk_flags=[],
            execution_notes="No position — signal is HOLD or conviction is zero.",
        )

    # ── Step 1: Base position size ───────────────────────────────────
    conviction = synthesis.conviction
    base_shares_raw = (portfolio_nav * MAX_POSITION_PCT * conviction / 100.0) / price
    base_shares = math.floor(base_shares_raw)

    # ── Step 2: Disagreement discount (volatility proxy) ─────────────
    disagreement_discount = 0.4 + 0.6 * (1.0 - synthesis.disagreement_score)
    vol_adjusted_raw = base_shares_raw * disagreement_discount
    vol_adjusted = math.floor(vol_adjusted_raw)

    # ── Step 3: Concentration check ──────────────────────────────────
    existing_value = existing_positions.get(ticker, 0.0)
    max_position_value = portfolio_nav * MAX_POSITION_PCT
    remaining_room = max(max_position_value - existing_value, 0.0)
    concentration_cap_shares = math.floor(remaining_room / price) if price > 0 else 0
    concentration_adjusted = min(vol_adjusted, concentration_cap_shares)

    # ── Step 4: Max-loss cap  ────────────────────────────────────────
    #   max loss per trade = NAV * MAX_SINGLE_LOSS_PCT
    #   If stop-loss distance implies more loss than that, reduce shares.
    #   Approximate ATR as fraction of price using expected downside.
    worst_scenario = min(synthesis.scenarios, key=lambda s: s.return_pct)
    approx_atr_pct = abs(worst_scenario.return_pct) / 100.0 if worst_scenario.return_pct != 0 else 0.02
    stop_distance_pct = STOP_LOSS_ATR_MULT * approx_atr_pct
    stop_distance_usd = price * stop_distance_pct

    max_loss_usd_cap = portfolio_nav * MAX_SINGLE_LOSS_PCT
    if stop_distance_usd > 0:
        loss_cap_shares = math.floor(max_loss_usd_cap / stop_distance_usd)
    else:
        loss_cap_shares = concentration_adjusted

    event_adjusted = min(concentration_adjusted, loss_cap_shares)

    # ── Hard cap: never exceed MAX_POSITION_PCT ──────────────────────
    hard_cap_shares = math.floor(max_position_value / price) if price > 0 else 0
    final_shares = max(min(event_adjusted, hard_cap_shares), 0)

    # ── Determine binding constraint ─────────────────────────────────
    binding = "none"
    if final_shares == hard_cap_shares and hard_cap_shares < event_adjusted:
        binding = "max_position_pct"
    elif final_shares == loss_cap_shares and loss_cap_shares < concentration_adjusted:
        binding = "max_single_loss"
    elif final_shares == concentration_adjusted and concentration_adjusted < vol_adjusted:
        binding = "concentration"
    elif final_shares == vol_adjusted and vol_adjusted < base_shares:
        binding = "disagreement_discount"
    else:
        binding = "base_sizing"

    # ── Position metrics ─────────────────────────────────────────────
    position_value = final_shares * price
    position_pct = position_value / portfolio_nav if portfolio_nav > 0 else 0.0
    # Clamp to schema max (0.02) to satisfy pydantic constraint
    position_pct = min(position_pct, MAX_POSITION_PCT)

    # ── Stop loss & take profit ──────────────────────────────────────
    if synthesis.signal == Signal.BUY:
        stop_loss_price = round(price * (1.0 - stop_distance_pct), 2)
        take_profit_price = round(target_price, 2)
    else:  # SHORT
        stop_loss_price = round(price * (1.0 + stop_distance_pct), 2)
        take_profit_price = round(target_price, 2)

    # ── Risk/reward ──────────────────────────────────────────────────
    if synthesis.signal == Signal.BUY:
        reward_per_share = take_profit_price - price
        risk_per_share = price - stop_loss_price
    else:
        reward_per_share = price - take_profit_price
        risk_per_share = stop_loss_price - price

    risk_reward_ratio = (
        round(reward_per_share / risk_per_share, 2)
        if risk_per_share > 0 else 0.0
    )

    max_loss = final_shares * risk_per_share if risk_per_share > 0 else 0.0
    max_loss_pct = max_loss / portfolio_nav if portfolio_nav > 0 else 0.0

    # ── Stress tests ─────────────────────────────────────────────────
    stress_tests = _run_stress_tests(ticker, position_value, portfolio_nav)
    rating = _risk_rating(stress_tests)

    # ── Risk flags ───────────────────────────────────────────────────
    risk_flags: list[str] = []
    if synthesis.disagreement_score > 0.5:
        risk_flags.append("high_disagreement")
    if rating in ("HIGH", "EXTREME"):
        risk_flags.append(f"stress_test_{rating.lower()}")
    if position_pct > 0.015:
        risk_flags.append("near_position_cap")
    if risk_reward_ratio > 0 and risk_reward_ratio < 1.5:
        risk_flags.append("low_risk_reward")

    return RiskOutput(
        ticker=ticker,
        signal=synthesis.signal,
        risk_rating=rating,
        base_shares=base_shares,
        volatility_adjusted_shares=vol_adjusted,
        concentration_adjusted_shares=concentration_adjusted,
        event_adjusted_shares=event_adjusted,
        final_shares=final_shares,
        position_value_usd=round(position_value, 2),
        position_pct_of_portfolio=round(position_pct, 6),
        binding_constraint=binding,
        stop_loss_price=stop_loss_price,
        stop_loss_type="volatility",
        take_profit_price=take_profit_price,
        risk_reward_ratio=risk_reward_ratio,
        max_loss_usd=round(max_loss, 2),
        max_loss_pct_portfolio=round(max_loss_pct, 6),
        stress_tests=stress_tests,
        risk_flags=risk_flags,
        execution_notes=f"Sized via deterministic layer. Binding constraint: {binding}.",
    )


# ── Inline tests ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/Users/fongyeungwong/Documents/Trading-Agent/TradingAgents")
    from tradingagents.schemas.v3 import Scenario, Regime  # noqa: F811

    synth = SynthesisOutput(
        ticker="AAPL",
        date="2026-04-05",
        signal=Signal.BUY,
        conviction=60,
        scenarios=[
            Scenario(
                probability=0.6,
                target_price=275.0,
                return_pct=8.0,
                rationale="Earnings beat",
            )
        ],
        expected_value_pct=3.5,
        disagreement_score=0.25,
        decision_rationale="Thesis stronger",
        key_evidence=["Earnings catalyst"],
    )

    # Test 1: Basic risk evaluation
    result = evaluate_risk(synth, portfolio_nav=100_000)
    assert isinstance(result, RiskOutput)
    assert result.ticker == "AAPL"
    assert result.signal == Signal.BUY
    assert result.final_shares >= 0
    assert result.position_pct_of_portfolio <= 0.02
    assert result.stop_loss_price > 0
    assert result.take_profit_price > 0
    assert len(result.stress_tests) == 5
    print(f"Test 1 PASSED: {result.final_shares} shares, {result.risk_rating}")

    # Test 2: HOLD signal = 0 shares
    hold_synth = SynthesisOutput(
        ticker="TEST",
        date="2026-04-05",
        signal=Signal.HOLD,
        conviction=20,
        scenarios=[
            Scenario(
                probability=0.5,
                target_price=100,
                return_pct=0,
                rationale="Flat",
            )
        ],
        expected_value_pct=0,
        disagreement_score=0.8,
        decision_rationale="Ambiguous",
        key_evidence=[],
    )
    hold_result = evaluate_risk(hold_synth, portfolio_nav=100_000)
    assert hold_result.final_shares == 0
    print("Test 2 PASSED: HOLD -> 0 shares")

    # Test 3: Position cap enforcement
    assert result.position_pct_of_portfolio <= 0.02
    print("Test 3 PASSED: Position cap enforced")

    print("\nAll tests PASSED")
