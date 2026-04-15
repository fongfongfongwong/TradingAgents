"""F5: Thesis Agent -- Upside Catalyst Identification.

Constructs the strongest possible upside case for a ticker using
the Anthropic API (Claude Sonnet 4.6). Falls back to a deterministic
mock when the API is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from tradingagents.gateway.cost_tracker import (
    BudgetExceededError,
    CostEntry,
    compute_cost,
    get_cost_tracker,
)
from tradingagents.schemas.v3 import (
    Catalyst,
    MustBeTrue,
    ThesisOutput,
    TickerBriefing,
)

logger = logging.getLogger(__name__)

_MAX_TOKENS = 2000
_PROMPT_VERSION = 1


def _get_model() -> str:
    """Return the thesis model configured in runtime config (lazy lookup)."""
    from tradingagents.api.routes.config import get_runtime_config

    return get_runtime_config().thesis_model


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
    """Convert a TickerBriefing into a structured text block for the LLM."""

    sections: list[str] = []

    # -- Price / Technical --
    p = briefing.price
    sections.append(
        f"[PRICE / TECHNICAL]  (data age: {p.data_age_seconds}s)\n"
        f"  Price: {p.price:.2f}  |  1d: {p.change_1d_pct:+.2f}%  "
        f"5d: {p.change_5d_pct:+.2f}%  20d: {p.change_20d_pct:+.2f}%\n"
        f"  SMA20: {p.sma_20:.2f}  SMA50: {p.sma_50:.2f}  SMA200: {p.sma_200:.2f}\n"
        f"  RSI14: {p.rsi_14:.1f}  MACD>Signal: {p.macd_above_signal}  "
        f"Crossover days: {p.macd_crossover_days}\n"
        f"  Bollinger: {p.bollinger_position}  "
        f"Vol vs 20d avg: {p.volume_vs_avg_20d:.2f}x  ATR14: {p.atr_14:.2f}"
    )

    # -- Fundamentals --
    if briefing.fundamentals:
        f = briefing.fundamentals
        fund_lines = [f"[FUNDAMENTALS]  (data age: {f.data_age_seconds}s)"]
        if f.market_cap is not None:
            fund_lines.append(f"  Market Cap: ${f.market_cap / 1e9:.1f}B")
        if f.pe_ratio is not None:
            fund_lines.append(f"  P/E (TTM): {f.pe_ratio:.1f}")
        if f.forward_pe is not None:
            fund_lines.append(f"  Forward P/E: {f.forward_pe:.1f}")
        if f.eps_ttm is not None:
            fund_lines.append(f"  EPS (TTM): ${f.eps_ttm:.2f}")
        if f.revenue_ttm is not None:
            fund_lines.append(f"  Revenue (TTM): ${f.revenue_ttm / 1e9:.2f}B")
        if f.profit_margin is not None:
            fund_lines.append(f"  Profit Margin: {f.profit_margin * 100:.1f}%")
        if f.debt_to_equity is not None:
            fund_lines.append(f"  Debt/Equity: {f.debt_to_equity:.1f}")
        if f.dividend_yield is not None:
            fund_lines.append(f"  Dividend Yield: {f.dividend_yield * 100:.2f}%")
        if f.sector:
            fund_lines.append(f"  Sector: {f.sector} / {f.industry or 'N/A'}")
        sections.append("\n".join(fund_lines))

    # -- Options --
    o = briefing.options
    parts = [f"[OPTIONS]  (data age: {o.data_age_seconds}s)"]
    if o.put_call_ratio is not None:
        parts.append(f"  P/C Ratio: {o.put_call_ratio:.2f}")
    if o.iv_rank_percentile is not None:
        parts.append(f"  IV Rank: {o.iv_rank_percentile:.1f}%")
    if o.iv_skew_25d is not None:
        parts.append(f"  IV Skew 25d: {o.iv_skew_25d:.2f}")
    if o.max_pain_price is not None:
        parts.append(f"  Max Pain: {o.max_pain_price:.2f}")
    if o.unusual_activity_summary:
        parts.append(f"  Unusual activity: {o.unusual_activity_summary}")
    sections.append("\n".join(parts))

    # -- News --
    n = briefing.news
    news_lines = [f"[NEWS]  (data age: {n.data_age_seconds}s)"]
    for i, h in enumerate(n.top_headlines, 1):
        news_lines.append(f"  {i}. {h}")
    news_lines.append(f"  Avg sentiment: {n.headline_sentiment_avg:+.2f}")
    if n.event_flags:
        news_lines.append(f"  Event flags: {', '.join(n.event_flags)}")
    sections.append("\n".join(news_lines))

    # -- Social --
    s = briefing.social
    sections.append(
        f"[SOCIAL]  (data age: {s.data_age_seconds}s)\n"
        f"  Mention vol vs avg: {s.mention_volume_vs_avg:.2f}x  "
        f"Sentiment: {s.sentiment_score:+.2f}\n"
        f"  Narratives: {', '.join(s.trending_narratives) if s.trending_narratives else 'none'}"
    )

    # -- Institutional (Quiver) --
    sections.append(_format_institutional_block(briefing))

    # -- Macro --
    m = briefing.macro
    macro_lines = [f"[MACRO]  (data age: {m.data_age_seconds}s)"]
    macro_lines.append(f"  Regime: {m.regime.value}")
    if m.fed_funds_rate is not None:
        macro_lines.append(f"  Fed Funds: {m.fed_funds_rate:.2f}%")
    if m.vix_level is not None:
        macro_lines.append(f"  VIX: {m.vix_level:.1f}")
    if m.yield_curve_2y10y_bps is not None:
        macro_lines.append(f"  2y10y: {m.yield_curve_2y10y_bps}bps")
    if m.sector_etf_5d_pct is not None:
        macro_lines.append(
            f"  Sector ETF 5d: {m.sector_etf_5d_pct:+.2f}%  "
            f"20d: {m.sector_etf_20d_pct:+.2f}%" if m.sector_etf_20d_pct is not None
            else f"  Sector ETF 5d: {m.sector_etf_5d_pct:+.2f}%"
        )
    sections.append("\n".join(macro_lines))

    # -- Events --
    e = briefing.events
    event_lines = ["[EVENTS]"]
    if e.next_earnings_days is not None:
        event_lines.append(f"  Next earnings in: {e.next_earnings_days} days")
    event_lines.append(f"  Ex-div within 30d: {e.ex_dividend_within_30d}")
    event_lines.append(f"  Fed meeting within 30d: {e.fed_meeting_within_30d}")
    if e.known_catalysts:
        event_lines.append(f"  Known catalysts: {', '.join(e.known_catalysts)}")
    sections.append("\n".join(event_lines))

    # -- Data gaps --
    if briefing.data_gaps:
        sections.append(f"[DATA GAPS]  {', '.join(briefing.data_gaps)}")

    return "\n\n".join(sections)


def _build_prompt(briefing: TickerBriefing) -> str:
    """Build the full analysis prompt for the LLM."""

    formatted = _format_briefing(briefing)

    return (
        f"You construct the strongest possible case that {briefing.ticker} will "
        f"increase in price over the next 30 trading days.\n"
        f"\n"
        f"You are not pretending to be optimistic. You are applying Upside Catalyst "
        f"Identification methodology to find genuine upside drivers in the data.\n"
        f"\n"
        f"=== DATA BRIEFING ===\n"
        f"{formatted}\n"
        f"\n"
        f"=== ANALYTICAL METHOD ===\n"
        f"Step 1: Valuation Gap Analysis -- Is the stock cheap vs sector on any metric?\n"
        f"Step 2: Momentum Alignment -- Price above SMA50? RSI 40-65? MACD bullish?\n"
        f"Step 3: Catalyst Identification -- What specific events could move price up?\n"
        f"Step 4: Contrarian Signals -- High put/call? High short interest?\n"
        f"Step 5: Must-Be-True Conditions -- List exactly 3 falsifiable conditions.\n"
        f"Step 6: Confidence -- Rate 0-100. Identify your weakest link.\n"
        f"\n"
        f"=== ANTI-SYCOPHANCY RULES ===\n"
        f"- If the data does not support a bullish case, say so explicitly.\n"
        f"- Your confidence score MUST reflect the actual strength of evidence.\n"
        f"- Do not manufacture arguments without data support.\n"
        f"\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f'  "ticker": "{briefing.ticker}",\n'
        f'  "direction": "BUY",\n'
        f'  "valuation_gap_summary": "string",\n'
        f'  "momentum_aligned": true/false,\n'
        f'  "momentum_detail": "string",\n'
        f'  "catalysts": [{{"event": "string", "mechanism": "string", "magnitude_estimate": "string"}}],\n'
        f'  "contrarian_signals": ["string"],\n'
        f'  "must_be_true": [{{"condition": "string", "probability": 0.0-1.0, '
        f'"evidence": "string", "falsifiable_by": "string"}}],\n'
        f'  "weakest_link": "string",\n'
        f'  "confidence_rationale": "string",\n'
        f'  "confidence_score": 0-100\n'
        f"}}\n"
        f"\n"
        f"Requirements:\n"
        f"- must_be_true must have exactly 3 items.\n"
        f"- catalysts must have at least 1 item.\n"
        f"- confidence_score is an integer 0-100.\n"
        f"- probability values are floats 0.0-1.0.\n"
    )


def _build_retry_prompt(briefing: TickerBriefing, error_msg: str) -> str:
    """Build a simplified retry prompt after a parse failure."""

    return (
        f"Your previous response for {briefing.ticker} was not valid JSON. "
        f"Error: {error_msg}\n\n"
        f"Output ONLY raw JSON (no markdown, no commentary) for a bullish thesis:\n"
        f'{{"ticker": "{briefing.ticker}", "direction": "BUY", '
        f'"valuation_gap_summary": "...", "momentum_aligned": true/false, '
        f'"momentum_detail": "...", '
        f'"catalysts": [{{"event": "...", "mechanism": "...", "magnitude_estimate": "..."}}], '
        f'"contrarian_signals": ["..."], '
        f'"must_be_true": ['
        f'{{"condition": "...", "probability": 0.5, "evidence": "...", "falsifiable_by": "..."}}, '
        f'{{"condition": "...", "probability": 0.5, "evidence": "...", "falsifiable_by": "..."}}, '
        f'{{"condition": "...", "probability": 0.5, "evidence": "...", "falsifiable_by": "..."}}], '
        f'"weakest_link": "...", "confidence_rationale": "...", "confidence_score": 50}}'
    )


# ------------------------------------------------------------------
# Response parsing
# ------------------------------------------------------------------


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response text.

    Handles responses wrapped in ```json``` code blocks,
    responses with leading/trailing text, and raw JSON.
    """

    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned.strip())

    # Try parsing the cleaned text directly
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find a JSON object with regex
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from response (length={len(text)})")


# ------------------------------------------------------------------
# Mock fallback
# ------------------------------------------------------------------


def _mock_thesis(briefing: TickerBriefing) -> ThesisOutput:
    """Return a deterministic mock ThesisOutput when the LLM is unavailable."""

    return ThesisOutput(
        ticker=briefing.ticker,
        direction="BUY",
        valuation_gap_summary="Mock: Unable to assess without LLM.",
        momentum_aligned=briefing.price.macd_above_signal,
        momentum_detail=(
            f"RSI at {briefing.price.rsi_14:.1f}, MACD "
            f"{'above' if briefing.price.macd_above_signal else 'below'} signal."
        ),
        catalysts=[
            Catalyst(
                event="N/A",
                mechanism="Mock mode",
                magnitude_estimate="N/A",
            )
        ],
        contrarian_signals=[],
        must_be_true=[
            MustBeTrue(
                condition="Price stays above SMA50",
                probability=0.5,
                evidence="Current price vs SMA50",
                falsifiable_by="Price drops below SMA50",
            ),
            MustBeTrue(
                condition="No negative earnings surprise",
                probability=0.6,
                evidence="Historical earnings",
                falsifiable_by="Earnings miss",
            ),
            MustBeTrue(
                condition="Macro regime stays stable",
                probability=0.5,
                evidence="Current VIX level",
                falsifiable_by="VIX spikes above 30",
            ),
        ],
        weakest_link="This is mock output -- no real analysis performed.",
        confidence_rationale="Mock mode -- no LLM analysis available.",
        confidence_score=25,
        used_mock=True,
    )


# ------------------------------------------------------------------
# API call
# ------------------------------------------------------------------


def _call_anthropic(prompt: str, ticker: str) -> str:
    """Call the Anthropic messages API and return the text response.

    Raises if the anthropic package is missing, the key is absent,
    or the API call fails. Records per-call cost into the module cost
    tracker for budget enforcement.
    """

    try:
        import anthropic  # noqa: WPS433 (runtime import for graceful fallback)
    except ImportError as exc:
        raise RuntimeError("anthropic package not installed") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    model = _get_model()
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    # -- Record cost from response.usage (tolerant of missing fields) --
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cost_usd = compute_cost(model, input_tokens, output_tokens)
    get_cost_tracker().record(
        CostEntry(
            ticker=ticker,
            agent_name="thesis",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            timestamp=datetime.now(),
        )
    )

    # Extract text from the first content block
    if response.content and len(response.content) > 0:
        return response.content[0].text

    raise RuntimeError("Empty response from Anthropic API")


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------


def run_thesis_agent(briefing: TickerBriefing) -> ThesisOutput:
    """Construct the strongest upside case for the given ticker.

    Calls Claude via the Anthropic API using the configured thesis model.
    Falls back to a deterministic mock when the API key is missing, the
    anthropic package is not installed, the API call fails, or the
    configured budget has been exceeded.
    """

    ticker = briefing.ticker

    # -- Budget gate --
    try:
        get_cost_tracker().check_budget(ticker)
    except BudgetExceededError as budget_err:
        logger.warning(
            "thesis agent fell back to mock for %s: %s",
            ticker,
            budget_err,
        )
        return _mock_thesis(briefing)

    # -- Guard: try the LLM path --
    try:
        prompt = _build_prompt(briefing)
        raw_text = _call_anthropic(prompt, ticker)

        try:
            parsed = _extract_json_from_text(raw_text)
            return ThesisOutput.model_validate(parsed)
        except (ValueError, Exception) as parse_err:
            logger.warning(
                "First parse attempt failed for %s: %s. Retrying...",
                ticker,
                parse_err,
            )

            # -- Retry once with a simpler prompt --
            retry_prompt = _build_retry_prompt(briefing, str(parse_err))
            retry_text = _call_anthropic(retry_prompt, ticker)

            try:
                parsed_retry = _extract_json_from_text(retry_text)
                return ThesisOutput.model_validate(parsed_retry)
            except (ValueError, Exception) as retry_err:
                logger.warning(
                    "thesis agent fell back to mock for %s: retry parse failed (%s)",
                    ticker,
                    retry_err,
                )
                return _mock_thesis(briefing)

    except RuntimeError as api_err:
        logger.warning(
            "thesis agent fell back to mock for %s: LLM unavailable (%s)",
            ticker,
            api_err,
        )
        return _mock_thesis(briefing)
    except Exception as unexpected_err:
        logger.warning(
            "thesis agent fell back to mock for %s: unexpected error (%s)",
            ticker,
            unexpected_err,
        )
        return _mock_thesis(briefing)


# ------------------------------------------------------------------
# Self-test
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/Users/fongyeungwong/Documents/Trading-Agent/TradingAgents")
    from tradingagents.data.materializer import materialize_briefing

    # Test 1: Mock mode (no API key needed)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    briefing = materialize_briefing("AAPL", "2026-04-05")
    result = run_thesis_agent(briefing)
    assert isinstance(result, ThesisOutput)
    assert result.ticker == "AAPL"
    assert result.direction == "BUY"
    assert len(result.must_be_true) >= 3
    assert 0 <= result.confidence_score <= 100
    print(f"Test 1 PASSED: Mock mode (confidence={result.confidence_score})")

    # Test 2: Schema compliance
    assert isinstance(result.catalysts, list)
    assert all(isinstance(c, Catalyst) for c in result.catalysts)
    assert all(isinstance(m, MustBeTrue) for m in result.must_be_true)
    print("Test 2 PASSED: Schema compliance")

    # Test 3: If API key exists, test real call
    if os.environ.get("ANTHROPIC_API_KEY"):
        real_result = run_thesis_agent(briefing)
        assert isinstance(real_result, ThesisOutput)
        assert real_result.confidence_score > 0
        assert len(real_result.catalysts) > 0
        print(f"Test 3 PASSED: Real LLM call (confidence={real_result.confidence_score})")
    else:
        print("Test 3 SKIPPED: No ANTHROPIC_API_KEY")

    print("\nAll tests PASSED")
