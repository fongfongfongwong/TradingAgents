"""Antithesis Agent — Downside Risk Mapping (Feature F6).

Constructs the strongest possible bearish case for a given ticker
using the Downside Risk Mapping methodology. Calls Claude Sonnet 4.6
via the Anthropic API; falls back to a deterministic mock if the
API is unavailable.
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
from tradingagents.schemas.v3 import (
    AntithesisOutput,
    Catalyst,
    MustBeTrue,
    TickerBriefing,
)

logger = logging.getLogger(__name__)

_PROMPT_VERSION = 1


def _get_model() -> str:
    """Return the antithesis model from runtime config (lazy lookup)."""
    from tradingagents.api.routes.config import get_runtime_config

    return get_runtime_config().antithesis_model


# ------------------------------------------------------------------
# Briefing formatter
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
    """Render a TickerBriefing into a human-readable text block."""
    price = briefing.price
    opts = briefing.options
    news = briefing.news
    social = briefing.social
    macro = briefing.macro
    events = briefing.events

    lines: list[str] = [
        f"Ticker: {briefing.ticker}",
        f"Date: {briefing.date}",
        f"Snapshot ID: {briefing.snapshot_id}",
        "",
        "--- PRICE ---",
        f"Price: ${price.price:.2f}",
        f"1D Change: {price.change_1d_pct:+.2f}%",
        f"5D Change: {price.change_5d_pct:+.2f}%",
        f"20D Change: {price.change_20d_pct:+.2f}%",
        f"SMA20: {price.sma_20:.2f}  SMA50: {price.sma_50:.2f}  SMA200: {price.sma_200:.2f}",
        f"RSI(14): {price.rsi_14:.1f}",
        f"MACD above signal: {price.macd_above_signal}  (crossover {price.macd_crossover_days}d ago)",
        f"Bollinger position: {price.bollinger_position}",
        f"Volume vs 20d avg: {price.volume_vs_avg_20d:.2f}x",
        f"ATR(14): {price.atr_14:.2f}",
    ]

    # -- Fundamentals --
    if briefing.fundamentals:
        f = briefing.fundamentals
        lines.append("")
        lines.append(f"--- FUNDAMENTALS ---  (data age: {f.data_age_seconds}s)")
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
        "--- OPTIONS ---",
        f"Put/Call Ratio: {opts.put_call_ratio}",
        f"IV Rank Percentile: {opts.iv_rank_percentile}",
        f"IV Skew (25d): {opts.iv_skew_25d}",
        f"Max Pain: {opts.max_pain_price}",
        f"Unusual Activity: {opts.unusual_activity_summary or 'None'}",
        "",
        "--- NEWS ---",
        f"Headline Sentiment Avg: {news.headline_sentiment_avg:+.2f}",
        f"Headlines: {'; '.join(news.top_headlines) if news.top_headlines else 'None'}",
        f"Event Flags: {', '.join(news.event_flags) if news.event_flags else 'None'}",
        "",
        "--- SOCIAL ---",
        f"Mention Volume vs Avg: {social.mention_volume_vs_avg:.2f}x",
        f"Sentiment Score: {social.sentiment_score:+.2f}",
        f"Trending Narratives: {', '.join(social.trending_narratives) if social.trending_narratives else 'None'}",
        "",
        _format_institutional_block(briefing),
        "",
        "--- MACRO ---",
        f"Regime: {macro.regime.value}",
        f"VIX: {macro.vix_level}",
        f"Fed Funds Rate: {macro.fed_funds_rate}",
        f"Yield Curve 2y10y: {macro.yield_curve_2y10y_bps} bps",
        f"Sector ETF 5D: {macro.sector_etf_5d_pct}%  20D: {macro.sector_etf_20d_pct}%",
        "",
        "--- EVENTS ---",
        f"Next Earnings: {events.next_earnings_days} days" if events.next_earnings_days is not None else "Next Earnings: Unknown",
        f"Ex-Dividend within 30d: {events.ex_dividend_within_30d}",
        f"Fed Meeting within 30d: {events.fed_meeting_within_30d}",
        f"Known Catalysts: {', '.join(events.known_catalysts) if events.known_catalysts else 'None'}",
        "",
        f"--- DATA GAPS: {', '.join(briefing.data_gaps) if briefing.data_gaps else 'None'} ---",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------
# System prompt builder
# ------------------------------------------------------------------


def _build_prompt(briefing: TickerBriefing) -> str:
    """Build the full antithesis prompt with formatted briefing data."""
    formatted = _format_briefing(briefing)
    return f"""You construct the strongest possible case that {briefing.ticker} will decrease in price \
over the next 30 trading days.

You are not pretending to be pessimistic. You are applying Downside Risk Mapping \
methodology to identify genuine risks in the data.

=== DATA BRIEFING ===
{formatted}

=== ANALYTICAL METHOD ===
Step 1: Overvaluation Assessment — Is the stock expensive vs sector/history?
Step 2: Deterioration Signals — Price below SMA50? RSI overbought? MACD bearish?
Step 3: Risk Catalyst Identification — What could move price down? Be specific with mechanisms.
Step 4: Crowding & Fragility — Low short interest + low put/call = complacent positioning.
Step 5: Must-Be-True Conditions — List exactly 3 falsifiable conditions for bearish thesis.
Step 6: Confidence — Rate 0-100. Identify your weakest link.

=== ANTI-SYCOPHANCY RULES ===
- If the data does not support a bearish case, say so explicitly.
- Your confidence score MUST reflect the actual strength of evidence.

Output ONLY valid JSON matching the AntithesisOutput schema.

The schema requires these fields:
- ticker: str (must be "{briefing.ticker}")
- direction: "SHORT" (literal)
- overvaluation_summary: str
- deterioration_present: bool
- deterioration_detail: str
- risk_catalysts: list of objects with {{event, mechanism, magnitude_estimate}}
- crowding_fragility: list of str
- must_be_true: list of exactly 3 objects with {{condition, probability (0-1), evidence, falsifiable_by}}
- weakest_link: str
- confidence_rationale: str
- confidence_score: int (0-100)"""


# ------------------------------------------------------------------
# LLM call
# ------------------------------------------------------------------


def _call_llm(briefing: TickerBriefing) -> AntithesisOutput | None:
    """Call Claude and parse the response into AntithesisOutput.

    Returns None if the API call fails for any reason. Records per-call
    cost into the module cost tracker.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning(
            "antithesis agent fell back to mock for %s: ANTHROPIC_API_KEY not set",
            briefing.ticker,
        )
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning(
            "antithesis agent fell back to mock for %s: anthropic package not installed",
            briefing.ticker,
        )
        return None

    prompt = _build_prompt(briefing)
    model = _get_model()

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=2048,
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
                agent_name="antithesis",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=compute_cost(model, input_tokens, output_tokens),
                timestamp=datetime.now(),
            )
        )

        raw_text = message.content[0].text.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            first_newline = raw_text.index("\n")
            raw_text = raw_text[first_newline + 1 :]
            if raw_text.endswith("```"):
                raw_text = raw_text[: -len("```")].strip()

        parsed: dict[str, Any] = json.loads(raw_text)

        # Force correct ticker and direction in case the model hallucinated
        parsed["ticker"] = briefing.ticker
        parsed["direction"] = "SHORT"

        return AntithesisOutput.model_validate(parsed)

    except Exception as exc:
        logger.warning(
            "antithesis agent fell back to mock for %s: LLM call failed (%s)",
            briefing.ticker,
            exc,
        )
        return None


# ------------------------------------------------------------------
# Mock fallback
# ------------------------------------------------------------------


def _mock_antithesis(briefing: TickerBriefing) -> AntithesisOutput:
    """Deterministic fallback when the LLM is unavailable."""
    return AntithesisOutput(
        ticker=briefing.ticker,
        direction="SHORT",
        overvaluation_summary="Mock: Unable to assess without LLM.",
        deterioration_present=not briefing.price.macd_above_signal,
        deterioration_detail=f"RSI at {briefing.price.rsi_14:.1f}.",
        risk_catalysts=[
            Catalyst(
                event="N/A",
                mechanism="Mock mode",
                magnitude_estimate="N/A",
            ),
        ],
        crowding_fragility=[],
        must_be_true=[
            MustBeTrue(
                condition="Price breaks below SMA50",
                probability=0.4,
                evidence="Current trend",
                falsifiable_by="Price holds above SMA50",
            ),
            MustBeTrue(
                condition="Macro headwinds persist",
                probability=0.5,
                evidence="Rate environment",
                falsifiable_by="Fed pivots dovish",
            ),
            MustBeTrue(
                condition="No positive earnings surprise",
                probability=0.5,
                evidence="Consensus estimates",
                falsifiable_by="Earnings beat",
            ),
        ],
        weakest_link="Mock output — no real analysis.",
        confidence_rationale="Mock mode.",
        confidence_score=25,
        used_mock=True,
    )


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def run_antithesis_agent(briefing: TickerBriefing) -> AntithesisOutput:
    """Construct the strongest downside case for the given ticker.

    Uses the antithesis model configured in runtime config. Falls back
    to a deterministic mock when the LLM is unavailable or the configured
    budget has been exceeded.
    """
    try:
        get_cost_tracker().check_budget(briefing.ticker)
    except BudgetExceededError as budget_err:
        logger.warning(
            "antithesis agent fell back to mock for %s: %s",
            briefing.ticker,
            budget_err,
        )
        return _mock_antithesis(briefing)

    result = _call_llm(briefing)
    if result is not None:
        return result
    return _mock_antithesis(briefing)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/Users/fongyeungwong/Documents/Trading-Agent/TradingAgents")
    from tradingagents.data.materializer import materialize_briefing

    os.environ.pop("ANTHROPIC_API_KEY", None)
    briefing = materialize_briefing("AAPL", "2026-04-05")
    result = run_antithesis_agent(briefing)
    assert isinstance(result, AntithesisOutput)
    assert result.ticker == "AAPL"
    assert result.direction == "SHORT"
    assert len(result.must_be_true) >= 3
    assert 0 <= result.confidence_score <= 100
    print(f"Test 1 PASSED: Mock mode (confidence={result.confidence_score})")

    assert isinstance(result.risk_catalysts, list)
    assert all(isinstance(m, MustBeTrue) for m in result.must_be_true)
    print("Test 2 PASSED: Schema compliance")

    if os.environ.get("ANTHROPIC_API_KEY"):
        real = run_antithesis_agent(briefing)
        assert isinstance(real, AntithesisOutput)
        assert real.confidence_score > 0
        print(f"Test 3 PASSED: Real LLM (confidence={real.confidence_score})")
    else:
        print("Test 3 SKIPPED: No API key")

    print("\nAll tests PASSED")
