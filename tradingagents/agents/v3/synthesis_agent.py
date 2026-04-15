"""F8: Synthesis Agent (Judge) -- Blind Debate Evaluation.

Evaluates a structured debate between thesis (bullish) and antithesis
(bearish) agents, anchored by base rate statistical analysis, to produce
a final trading signal. Uses Anthropic API (Claude Opus) for deepest
reasoning. Falls back to a deterministic mock when the API is unavailable.
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
    AntithesisOutput,
    BaseRateOutput,
    FactualError,
    MustBeTrueResolved,
    Scenario,
    Signal,
    SynthesisOutput,
    ThesisOutput,
)

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4000
_PROMPT_VERSION = 1


def _get_primary_model() -> str:
    """Return the synthesis primary model from runtime config."""
    from tradingagents.api.routes.config import get_runtime_config

    return get_runtime_config().synthesis_model


def _get_fallback_model() -> str:
    """Return the synthesis fallback model from runtime config."""
    from tradingagents.api.routes.config import get_runtime_config

    return get_runtime_config().synthesis_fallback_model


# ------------------------------------------------------------------
# Prompt construction
# ------------------------------------------------------------------


def _build_prompt(
    thesis: ThesisOutput,
    antithesis: AntithesisOutput,
    base_rate: BaseRateOutput,
    divergence_context: str | None = None,
) -> str:
    """Build the full judge evaluation prompt for the LLM."""

    ticker = thesis.ticker
    thesis_json = thesis.model_dump_json(indent=2)
    antithesis_json = antithesis.model_dump_json(indent=2)
    base_rate_json = base_rate.model_dump_json(indent=2)

    divergence_block = ""
    if divergence_context:
        divergence_block = (
            f"\n=== DIVERGENCE ENGINE (Multi-Source Signal Fusion) ===\n"
            f"{divergence_context}\n"
        )

    return (
        f"You evaluate a structured debate between a thesis agent (bullish) and an "
        f"antithesis agent (bearish) for {ticker}, anchored by a base rate statistical analysis.\n"
        f"\n"
        f"You are not seeking consensus. You are determining which side presented stronger "
        f"DATA-SUPPORTED arguments. Defaulting to HOLD because \"both sides have merit\" is "
        f"a failure mode.\n"
        f"\n"
        f"=== THESIS (Bullish Case) ===\n"
        f"{thesis_json}\n"
        f"\n"
        f"=== ANTITHESIS (Bearish Case) ===\n"
        f"{antithesis_json}\n"
        f"\n"
        f"=== BASE RATE (Statistical Anchor) ===\n"
        f"{base_rate_json}\n"
        f"{divergence_block}"
        f"\n"
        f"=== EVALUATION METHOD ===\n"
        f"Step 1: Data Verification -- Flag any claims not supported by evidence.\n"
        f"Step 2: Must-Be-True Cross-Examination -- For each side's 3 conditions, "
        f"assess: met/not_met/indeterminate.\n"
        f"Step 3: Weakest Link Stress Test -- How damaging is each side's "
        f"self-identified weakness?\n"
        f"Step 4: Magnitude Asymmetry -- Compare upside % vs downside %, "
        f"weighted by confidence.\n"
        f"Step 5: Base Rate Integration -- Does the statistical anchor support "
        f"thesis or antithesis?\n"
        f"Step 6: Signal Decision -- BUY, SHORT, or HOLD.\n"
        f"\n"
        f"HOLD THRESHOLD: ONLY if ALL 3 conditions met:\n"
        f"  - Both sides have 2+ conditions \"indeterminate\"\n"
        f"  - Expected value between -2% and +2%\n"
        f"  - Both adjusted confidences below 40\n"
        f"\n"
        f"Output ONLY valid JSON matching this schema:\n"
        f"{{\n"
        f'  "ticker": "{ticker}",\n'
        f'  "date": "{datetime.now().strftime("%Y-%m-%d")}",\n'
        f'  "signal": "BUY" | "SHORT" | "HOLD",\n'
        f'  "conviction": 0-100,\n'
        f'  "scenarios": [{{"probability": 0.0-1.0, "target_price": 0.0, '
        f'"return_pct": 0.0, "rationale": "string"}}],\n'
        f'  "expected_value_pct": 0.0,\n'
        f'  "disagreement_score": 0.0-1.0,\n'
        f'  "data_audit": [{{"agent": "thesis"|"antithesis", "claim": "string", '
        f'"actual": "string"}}],\n'
        f'  "must_be_true_resolved": [{{"agent": "thesis"|"antithesis", '
        f'"condition": "string", "status": "met"|"not_met"|"indeterminate", '
        f'"challenged": true/false, "challenge_data_supported": true/false/null}}],\n'
        f'  "decision_rationale": "string",\n'
        f'  "key_evidence": ["string"],\n'
        f'  "hold_threshold_met": true/false\n'
        f"}}\n"
        f"\n"
        f"Requirements:\n"
        f"- scenarios must have at least 1 item.\n"
        f"- conviction is an integer 0-100.\n"
        f"- disagreement_score is a float 0.0-1.0.\n"
        f"- signal must be exactly BUY, SHORT, or HOLD.\n"
        f"- key_evidence must have at least 1 item.\n"
    )


def _build_retry_prompt(
    ticker: str,
    error_msg: str,
) -> str:
    """Build a simplified retry prompt after a parse failure."""

    return (
        f"Your previous response for {ticker} was not valid JSON. "
        f"Error: {error_msg}\n\n"
        f"Output ONLY raw JSON (no markdown, no commentary) for a synthesis judgment:\n"
        f'{{"ticker": "{ticker}", "date": "{datetime.now().strftime("%Y-%m-%d")}", '
        f'"signal": "HOLD", "conviction": 50, '
        f'"scenarios": [{{"probability": 0.5, "target_price": 0.0, '
        f'"return_pct": 0.0, "rationale": "Retry output"}}], '
        f'"expected_value_pct": 0.0, "disagreement_score": 0.5, '
        f'"data_audit": [], "must_be_true_resolved": [], '
        f'"decision_rationale": "Retry", "key_evidence": ["Retry"], '
        f'"hold_threshold_met": false}}'
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


def _mock_synthesis(
    thesis: ThesisOutput,
    antithesis: AntithesisOutput,
    base_rate: BaseRateOutput,
) -> SynthesisOutput:
    """Return a deterministic mock SynthesisOutput computed from input scores."""

    # Simple: higher confidence side wins
    if thesis.confidence_score > antithesis.confidence_score + 10:
        signal = Signal.BUY
    elif antithesis.confidence_score > thesis.confidence_score + 10:
        signal = Signal.SHORT
    else:
        signal = Signal.HOLD

    conviction = max(thesis.confidence_score, antithesis.confidence_score)
    disagreement = abs(thesis.confidence_score - antithesis.confidence_score) / 100.0
    ev = base_rate.expected_move_pct

    return SynthesisOutput(
        ticker=thesis.ticker,
        date=datetime.now().strftime("%Y-%m-%d"),
        signal=signal,
        conviction=conviction,
        scenarios=[
            Scenario(
                probability=base_rate.base_rate_probability_up,
                target_price=0.0,
                return_pct=base_rate.upside_pct,
                rationale="Mock: based on base rate upside estimate",
            ),
        ],
        expected_value_pct=ev,
        disagreement_score=disagreement,
        data_audit=[],
        must_be_true_resolved=[],
        decision_rationale="Mock: No LLM analysis available.",
        key_evidence=["Mock mode"],
        hold_threshold_met=(signal == Signal.HOLD),
        used_mock=True,
    )


# ------------------------------------------------------------------
# API call
# ------------------------------------------------------------------


def _call_anthropic(prompt: str, model: str, ticker: str) -> str:
    """Call the Anthropic messages API and return the text response.

    Raises if the anthropic package is missing, the key is absent,
    or the API call fails. Records cost (including any fallback retry)
    into the module cost tracker.
    """

    try:
        import anthropic  # noqa: WPS433 (runtime import for graceful fallback)
    except ImportError as exc:
        raise RuntimeError("anthropic package not installed") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    primary = _get_primary_model()
    fallback = _get_fallback_model()
    client = anthropic.Anthropic(api_key=api_key)

    used_model = model
    try:
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as model_err:
        # If primary model fails and we haven't tried fallback yet, try fallback
        if model == primary and fallback and fallback != primary:
            logger.warning(
                "Primary model %s failed: %s. Trying fallback %s.",
                model,
                model_err,
                fallback,
            )
            used_model = fallback
            response = client.messages.create(
                model=fallback,
                max_tokens=_MAX_TOKENS,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
        else:
            raise

    # -- Record cost --
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    get_cost_tracker().record(
        CostEntry(
            ticker=ticker,
            agent_name="synthesis",
            model=used_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost(used_model, input_tokens, output_tokens),
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


def run_synthesis_agent(
    thesis: ThesisOutput,
    antithesis: AntithesisOutput,
    base_rate: BaseRateOutput,
    divergence_context: str | None = None,
) -> SynthesisOutput:
    """Synthesize the blind debate and produce a final trading signal.

    Uses the synthesis primary/fallback models configured in runtime
    config. Falls back to a deterministic mock when the LLM is unavailable
    or the configured budget has been exceeded.

    Parameters
    ----------
    divergence_context:
        Optional human-readable divergence engine summary to include in the
        evaluation prompt.  When provided, the synthesis agent considers
        multi-source signal fusion alongside the debate.
    """

    ticker = thesis.ticker

    # -- Budget gate --
    try:
        get_cost_tracker().check_budget(ticker)
    except BudgetExceededError as budget_err:
        logger.warning(
            "synthesis agent fell back to mock for %s: %s",
            ticker,
            budget_err,
        )
        return _mock_synthesis(thesis, antithesis, base_rate)

    # -- Guard: try the LLM path --
    try:
        primary_model = _get_primary_model()
        prompt = _build_prompt(thesis, antithesis, base_rate, divergence_context)
        raw_text = _call_anthropic(prompt, primary_model, ticker)

        try:
            parsed = _extract_json_from_text(raw_text)
            return SynthesisOutput.model_validate(parsed)
        except (ValueError, Exception) as parse_err:
            logger.warning(
                "First parse attempt failed for %s: %s. Retrying...",
                ticker,
                parse_err,
            )

            # -- Retry once with a simpler prompt --
            retry_prompt = _build_retry_prompt(ticker, str(parse_err))
            retry_text = _call_anthropic(retry_prompt, primary_model, ticker)

            try:
                parsed_retry = _extract_json_from_text(retry_text)
                return SynthesisOutput.model_validate(parsed_retry)
            except (ValueError, Exception) as retry_err:
                logger.warning(
                    "synthesis agent fell back to mock for %s: retry parse failed (%s)",
                    ticker,
                    retry_err,
                )
                return _mock_synthesis(thesis, antithesis, base_rate)

    except RuntimeError as api_err:
        logger.warning(
            "synthesis agent fell back to mock for %s: LLM unavailable (%s)",
            ticker,
            api_err,
        )
        return _mock_synthesis(thesis, antithesis, base_rate)
    except Exception as unexpected_err:
        logger.warning(
            "synthesis agent fell back to mock for %s: unexpected error (%s)",
            ticker,
            unexpected_err,
        )
        return _mock_synthesis(thesis, antithesis, base_rate)


# ------------------------------------------------------------------
# Self-test
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.path.insert(0, "/Users/fongyeungwong/Documents/Trading-Agent/TradingAgents")
    from tradingagents.schemas.v3 import Catalyst, MustBeTrue, Regime

    # Build mock inputs
    thesis = ThesisOutput(
        ticker="AAPL",
        direction="BUY",
        valuation_gap_summary="Trades at discount",
        momentum_aligned=True,
        momentum_detail="RSI 62, MACD bullish",
        catalysts=[
            Catalyst(
                event="Earnings",
                mechanism="Revenue beat",
                magnitude_estimate="+5%",
            ),
        ],
        contrarian_signals=[],
        must_be_true=[
            MustBeTrue(
                condition="Earnings beat",
                probability=0.6,
                evidence="Historical",
                falsifiable_by="Earnings miss",
            ),
            MustBeTrue(
                condition="VIX below 25",
                probability=0.5,
                evidence="Current trend",
                falsifiable_by="VIX spike",
            ),
            MustBeTrue(
                condition="Holds SMA200",
                probability=0.7,
                evidence="Price trend",
                falsifiable_by="Breaks below",
            ),
        ],
        weakest_link="Macro uncertainty",
        confidence_rationale="Moderate",
        confidence_score=55,
    )
    antithesis = AntithesisOutput(
        ticker="AAPL",
        direction="SHORT",
        overvaluation_summary="P/E elevated",
        deterioration_present=False,
        deterioration_detail="Mild",
        risk_catalysts=[
            Catalyst(
                event="Rate hike",
                mechanism="Multiple compression",
                magnitude_estimate="-8%",
            ),
        ],
        crowding_fragility=[],
        must_be_true=[
            MustBeTrue(
                condition="Fed stays hawkish",
                probability=0.5,
                evidence="Dot plot",
                falsifiable_by="Fed pivots",
            ),
            MustBeTrue(
                condition="Revenue misses",
                probability=0.3,
                evidence="Estimates stretched",
                falsifiable_by="Revenue beat",
            ),
            MustBeTrue(
                condition="VIX stays elevated",
                probability=0.4,
                evidence="Current level",
                falsifiable_by="VIX drops",
            ),
        ],
        weakest_link="Revenue miss is low probability",
        confidence_rationale="Weak",
        confidence_score=30,
    )
    base_rate = BaseRateOutput(
        ticker="AAPL",
        expected_move_pct=2.0,
        upside_pct=8.0,
        downside_pct=-6.0,
        regime=Regime.TRANSITIONING,
        historical_analog="Q2 2018",
        base_rate_probability_up=0.58,
        volatility_forecast_20d=24.0,
    )

    # Test 1: Mock mode
    os.environ.pop("ANTHROPIC_API_KEY", None)
    result = run_synthesis_agent(thesis, antithesis, base_rate)
    assert isinstance(result, SynthesisOutput)
    assert result.signal in [Signal.BUY, Signal.SHORT, Signal.HOLD]
    assert 0 <= result.conviction <= 100
    assert 0.0 <= result.disagreement_score <= 1.0
    print(f"Test 1 PASSED: Mock ({result.signal.value}, conv={result.conviction})")

    # Test 2: With thesis winning by >10
    assert result.signal == Signal.BUY  # thesis 55 > antithesis 30 + 10
    print("Test 2 PASSED: Thesis wins when confidence higher")

    # Test 3: Real API
    if os.environ.get("ANTHROPIC_API_KEY"):
        real = run_synthesis_agent(thesis, antithesis, base_rate)
        assert isinstance(real, SynthesisOutput)
        print(f"Test 3 PASSED: Real LLM ({real.signal.value}, conv={real.conviction})")
    else:
        print("Test 3 SKIPPED: No API key")

    print("\nAll tests PASSED")
