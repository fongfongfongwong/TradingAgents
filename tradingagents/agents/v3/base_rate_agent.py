"""Base Rate Agent — Statistical Anchor for v3 Debate System.

Calls Claude Sonnet 4.6 to provide historical base rates, regime
classification, and volatility forecasts. Falls back to a deterministic
mock computed from the TickerBriefing when the API is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from tradingagents.gateway.cost_tracker import (
    BudgetExceededError,
    CostEntry,
    compute_cost,
    get_cost_tracker,
)
from tradingagents.schemas.v3 import BaseRateOutput, Regime, TickerBriefing

logger = logging.getLogger(__name__)

_MAX_TOKENS = 2048
_PROMPT_VERSION = 1


def _get_model() -> str:
    """Return the base-rate model from runtime config (lazy lookup)."""
    from tradingagents.api.routes.config import get_runtime_config

    return get_runtime_config().base_rate_model


# ------------------------------------------------------------------
# Prompt construction
# ------------------------------------------------------------------

def _format_institutional_block(briefing: TickerBriefing) -> str:
    """Render the InstitutionalContext (Quiver) section of the prompt.

    Only emits real values when ``briefing.institutional.fetched_ok`` is
    ``True`` — otherwise returns a single "data unavailable" line so the
    LLM cannot mistake defaulted zeros for real signals.
    """
    inst = briefing.institutional
    if not inst.fetched_ok:
        return "## INSTITUTIONAL SIGNALS (Quiver)\n(data unavailable)"

    top_buyers = ", ".join(inst.congressional_top_buyers) or "none"
    top_sellers = ", ".join(inst.congressional_top_sellers) or "none"
    insider_buyers = ", ".join(inst.insider_top_buyers) or "none"
    return (
        "## INSTITUTIONAL SIGNALS (Quiver)\n"
        f"- Congressional net buys (30d): {inst.congressional_net_buys_30d} "
        f"(top buyers: {top_buyers}; top sellers: {top_sellers})\n"
        f"- Government contracts (90d): {inst.govt_contracts_count_90d} contracts "
        f"totaling ${inst.govt_contracts_total_usd:,.0f}\n"
        f"- Lobbying last quarter: ${inst.lobbying_usd_last_quarter:,.0f}\n"
        f"- Insider Form 4 (90d): net {inst.insider_net_txns_90d} transactions "
        f"(top buyers: {insider_buyers})"
    )


def _format_briefing(briefing: TickerBriefing) -> str:
    """Flatten briefing into a human-readable text block for the prompt."""
    p = briefing.price
    m = briefing.macro
    o = briefing.options
    n = briefing.news
    s = briefing.social
    e = briefing.events

    lines = [
        f"Ticker: {briefing.ticker}",
        f"Date: {briefing.date}",
        "",
        "--- Price ---",
        f"Price: {p.price:.2f}",
        f"1d change: {p.change_1d_pct:+.2f}%  |  5d: {p.change_5d_pct:+.2f}%  |  20d: {p.change_20d_pct:+.2f}%",
        f"SMA 20/50/200: {p.sma_20:.2f} / {p.sma_50:.2f} / {p.sma_200:.2f}",
        f"RSI-14: {p.rsi_14:.1f}",
        f"MACD above signal: {p.macd_above_signal}  (crossover {p.macd_crossover_days}d ago)",
        f"Bollinger position: {p.bollinger_position}",
        f"Volume vs 20d avg: {p.volume_vs_avg_20d:.2f}x",
        f"ATR-14: {p.atr_14:.2f}",
    ]

    # -- Fundamentals --
    if briefing.fundamentals:
        f = briefing.fundamentals
        lines.append("")
        lines.append(f"--- Fundamentals ---  (data age: {f.data_age_seconds}s)")
        if f.market_cap is not None:
            lines.append(f"Market Cap: ${f.market_cap / 1e9:.1f}B")
        if f.pe_ratio is not None:
            lines.append(f"P/E (TTM): {f.pe_ratio:.1f}")
        if f.forward_pe is not None:
            lines.append(f"Forward P/E: {f.forward_pe:.1f}")
        if f.eps_ttm is not None:
            lines.append(f"EPS (TTM): ${f.eps_ttm:.2f}")
        if f.revenue_ttm is not None:
            lines.append(f"Revenue (TTM): ${f.revenue_ttm / 1e9:.2f}B")
        if f.profit_margin is not None:
            lines.append(f"Profit Margin: {f.profit_margin * 100:.1f}%")
        if f.debt_to_equity is not None:
            lines.append(f"Debt/Equity: {f.debt_to_equity:.1f}")
        if f.dividend_yield is not None:
            lines.append(f"Dividend Yield: {f.dividend_yield * 100:.2f}%")
        if f.sector:
            lines.append(f"Sector: {f.sector} / {f.industry or 'N/A'}")

    lines += [
        "",
        "--- Macro ---",
        f"Regime: {m.regime.value}",
        f"VIX: {m.vix_level}",
        f"Fed funds rate: {m.fed_funds_rate}",
        f"Yield curve 2y10y: {m.yield_curve_2y10y_bps} bps",
        f"Sector ETF 5d: {m.sector_etf_5d_pct}%  |  20d: {m.sector_etf_20d_pct}%",
        "",
        "--- Options ---",
        f"Put/Call ratio: {o.put_call_ratio}",
        f"IV rank percentile: {o.iv_rank_percentile}",
        f"IV skew 25d: {o.iv_skew_25d}",
        f"Max pain: {o.max_pain_price}",
        f"Unusual activity: {o.unusual_activity_summary or 'None'}",
        "",
        "--- News ---",
        f"Headline sentiment avg: {n.headline_sentiment_avg:.2f}",
        f"Headlines: {'; '.join(n.top_headlines) if n.top_headlines else 'None'}",
        f"Event flags: {', '.join(n.event_flags) if n.event_flags else 'None'}",
        "",
        "--- Social ---",
        f"Mention volume vs avg: {s.mention_volume_vs_avg:.2f}x",
        f"Sentiment: {s.sentiment_score:.2f}",
        f"Narratives: {', '.join(s.trending_narratives) if s.trending_narratives else 'None'}",
        "",
        _format_institutional_block(briefing),
        "",
        "--- Events ---",
        f"Next earnings in: {e.next_earnings_days} days",
        f"Ex-div within 30d: {e.ex_dividend_within_30d}",
        f"Fed meeting within 30d: {e.fed_meeting_within_30d}",
        f"Known catalysts: {', '.join(e.known_catalysts) if e.known_catalysts else 'None'}",
        "",
        f"Data gaps: {', '.join(briefing.data_gaps) if briefing.data_gaps else 'None'}",
    ]
    return "\n".join(lines)


def _build_prompt(briefing: TickerBriefing) -> str:
    """Build the system + user prompt for the base rate agent."""
    ticker = briefing.ticker
    formatted = _format_briefing(briefing)

    return (
        f"You provide a statistical anchor for an investment debate about {ticker}.\n"
        "\n"
        "You are not advocating for or against the stock. You analyze historical patterns,\n"
        "market regime, and base rates to set realistic expectations.\n"
        "\n"
        "=== DATA BRIEFING ===\n"
        f"{formatted}\n"
        "\n"
        "=== ANALYTICAL METHOD ===\n"
        "Step 1: Historical Base Rate — Given this RSI, MACD, and momentum pattern, "
        "what is the typical 30-day return?\n"
        "Step 2: Distribution Estimate — Provide upside and downside percentage estimates.\n"
        "Step 3: Regime Classification — Is the market in RISK_ON, RISK_OFF, TRANSITIONING, or CRISIS?\n"
        "Step 4: Historical Analog — What past period most resembles current conditions?\n"
        "Step 5: Probability of Up Move — Based on the data (not narrative), "
        "what's the base rate probability of positive return in 30 days?\n"
        "Step 6: Volatility Forecast — Expected 20-day realized volatility.\n"
        "\n"
        "Output ONLY valid JSON matching the BaseRateOutput schema.\n"
        "The schema fields are:\n"
        f'  "ticker": "{ticker}",\n'
        '  "expected_move_pct": float,\n'
        '  "upside_pct": float,\n'
        '  "downside_pct": float (negative number),\n'
        '  "regime": one of "RISK_ON", "RISK_OFF", "TRANSITIONING", "CRISIS",\n'
        '  "historical_analog": string,\n'
        '  "base_rate_probability_up": float between 0 and 1,\n'
        '  "volatility_forecast_20d": float (positive),\n'
        '  "sector_momentum_rank": int or null\n'
    )


# ------------------------------------------------------------------
# Mock fallback (deterministic, no LLM)
# ------------------------------------------------------------------

def _mock_base_rate(briefing: TickerBriefing) -> BaseRateOutput:
    """Compute a heuristic BaseRateOutput from briefing data alone."""
    p = briefing.price

    # Simple heuristic: momentum -> expected move
    momentum = (p.change_5d_pct + p.change_20d_pct) / 2
    expected = momentum * 0.3  # mean reversion dampening
    up_prob = 0.5 + (momentum / 100)  # slight bias from momentum
    up_prob = max(0.3, min(0.7, up_prob))

    regime = briefing.macro.regime
    vol_forecast = (
        p.atr_14 / p.price * 100 * (252**0.5) if p.price > 0 else 20.0
    )

    return BaseRateOutput(
        ticker=briefing.ticker,
        expected_move_pct=round(expected, 2),
        upside_pct=round(abs(expected) + vol_forecast * 0.3, 2),
        downside_pct=round(-(abs(expected) + vol_forecast * 0.3), 2),
        regime=regime,
        historical_analog="Mock: No LLM analysis available.",
        base_rate_probability_up=round(up_prob, 2),
        volatility_forecast_20d=round(vol_forecast, 2),
        sector_momentum_rank=None,
        used_mock=True,
    )


# ------------------------------------------------------------------
# LLM call
# ------------------------------------------------------------------

def _parse_llm_response(raw_text: str, ticker: str) -> BaseRateOutput:
    """Parse the LLM's JSON response into a validated BaseRateOutput."""
    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[: -3]
    text = text.strip()

    data: dict[str, Any] = json.loads(text)

    # Ensure ticker matches
    data["ticker"] = ticker

    # Normalise regime to enum
    regime_raw = data.get("regime", "TRANSITIONING")
    if isinstance(regime_raw, str):
        data["regime"] = Regime(regime_raw.upper())

    return BaseRateOutput.model_validate(data)


def _call_llm(briefing: TickerBriefing) -> BaseRateOutput:
    """Call Claude via the Anthropic API and parse the result.

    Records per-call cost into the module cost tracker.
    """
    import anthropic  # deferred import to keep module importable without SDK

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    prompt = _build_prompt(briefing)
    model = _get_model()

    message = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    # -- Record cost --
    usage = getattr(message, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    get_cost_tracker().record(
        CostEntry(
            ticker=briefing.ticker,
            agent_name="base_rate",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost(model, input_tokens, output_tokens),
            timestamp=datetime.now(),
        )
    )

    raw_text = message.content[0].text
    return _parse_llm_response(raw_text, briefing.ticker)


# ------------------------------------------------------------------
# Public interface
# ------------------------------------------------------------------

def run_base_rate_agent(briefing: TickerBriefing) -> BaseRateOutput:
    """Provide statistical context and regime analysis for the given ticker.

    Uses the base-rate model configured in runtime config. Falls back to a
    deterministic mock when the LLM is unavailable or the configured budget
    has been exceeded.
    """
    try:
        get_cost_tracker().check_budget(briefing.ticker)
    except BudgetExceededError as budget_err:
        logger.warning(
            "base_rate agent fell back to mock for %s: %s",
            briefing.ticker,
            budget_err,
        )
        return _mock_base_rate(briefing)

    try:
        return _call_llm(briefing)
    except Exception as exc:
        logger.warning(
            "base_rate agent fell back to mock for %s: LLM call failed (%s)",
            briefing.ticker,
            exc,
        )
        return _mock_base_rate(briefing)


# ------------------------------------------------------------------
# Inline tests
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.path.insert(
        0, "/Users/fongyeungwong/Documents/Trading-Agent/TradingAgents"
    )
    from tradingagents.data.materializer import materialize_briefing

    os.environ.pop("ANTHROPIC_API_KEY", None)
    briefing = materialize_briefing("AAPL", "2026-04-05")
    result = run_base_rate_agent(briefing)
    assert isinstance(result, BaseRateOutput)
    assert result.ticker == "AAPL"
    assert 0.0 <= result.base_rate_probability_up <= 1.0
    assert result.regime in [r for r in Regime]
    assert result.volatility_forecast_20d > 0
    print(
        f"Test 1 PASSED: Mock mode "
        f"(prob_up={result.base_rate_probability_up}, regime={result.regime})"
    )

    # Test 2: Regime is valid enum
    assert isinstance(result.regime, Regime)
    print("Test 2 PASSED: Schema compliance")

    if os.environ.get("ANTHROPIC_API_KEY"):
        real = run_base_rate_agent(briefing)
        assert isinstance(real, BaseRateOutput)
        assert 0.0 <= real.base_rate_probability_up <= 1.0
        print(f"Test 3 PASSED: Real LLM (prob_up={real.base_rate_probability_up})")
    else:
        print("Test 3 SKIPPED: No API key")

    print("\nAll tests PASSED")
