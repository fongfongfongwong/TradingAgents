"""Claude-powered filter for the volatility screener shortlist.

Takes a quant-ranked shortlist of ``VolRank`` candidates for one group
("US equities" or "US ETFs") and asks Claude Sonnet 4.5 to return a cleaned,
ordered top-N list of genuinely tradeable names, pruning:

* Recently IPO'd tickers (< 90 days of trading history)
* Delisted or soon-to-be-delisted tickers
* Already-filtered illiquid names (defence in depth)
* One-off corporate-action anomalies disguised as volatility

Failures (no API key, network error, parse error) always degrade gracefully
to the pure-quant top-N with ``kept_by_llm=False`` and ``llm_reason=None``.

Cost is recorded via :func:`tradingagents.gateway.cost_tracker.get_cost_tracker`
under ``ticker="SCREENER", agent_name="screener_filter"`` so this step shows
up alongside the rest of the v3 LLM spend.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from tradingagents.gateway.cost_tracker import CostEntry, compute_cost, get_cost_tracker

from .volatility_screener import VolRank

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"
_MAX_OUTPUT_TOKENS = 1500


def _format_candidate_line(r: VolRank) -> str:
    """One-line brief for a single candidate fed into the LLM prompt."""
    def _pct(v: float | None) -> str:
        return f"{v:.1%}" if v is not None else "n/a"

    return (
        f"- {r.ticker}: vol_20d={_pct(r.realized_vol_20d)}, "
        f"atr_pct={_pct(r.atr_pct)}, range={_pct(r.range_20d_pct)}, "
        f"score={r.composite_score:.2f}"
    )


def _build_user_prompt(
    candidates: list[VolRank], group_label: str, top_n: int
) -> str:
    """Build the user-side prompt body."""
    header = (
        f"Here are {len(candidates)} {group_label} on a volatility shortlist. "
        f"For each, a brief:"
    )
    lines = [_format_candidate_line(r) for r in candidates]
    instruction = (
        f"\n\nReturn a JSON array of exactly {top_n} objects: "
        f'[{{"ticker": "XXX", "reason": "..."}}]. '
        f"Order by your conviction (best first). Reasons should be 1 sentence max. "
        f"Only include tickers that appear in the list above. "
        f"Output ONLY the JSON array, no prose."
    )
    return header + "\n" + "\n".join(lines) + instruction


_SYSTEM_PROMPT = (
    "You are a quant analyst filtering a list of high-volatility tickers. "
    "Remove any that are: (a) recently IPO'd (< 90 days), (b) delisted or "
    "about to delist, (c) illiquid (< $10M avg daily dollar volume, already "
    "pre-filtered upstream so be lenient here), (d) anomaly spikes from "
    "one-off corporate actions rather than real volatility. Keep the top N "
    "genuinely tradeable names. Return JSON only."
)


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Pull the first JSON array out of an LLM response.

    Handles responses with a markdown code fence around the JSON.
    """
    # Try direct parse first.
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Then try to find a ```json fenced block or a raw [...] slice.
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        try:
            parsed = json.loads(fence.group(1))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    bracket = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket:
        try:
            parsed = json.loads(bracket.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError("could not parse JSON array from LLM response")


def _record_cost(input_tokens: int, output_tokens: int) -> None:
    """Log this LLM call against the module-level cost tracker."""
    try:
        cost = compute_cost(_MODEL, input_tokens, output_tokens)
        get_cost_tracker().record(
            CostEntry(
                ticker="SCREENER",
                agent_name="screener_filter",
                model=_MODEL,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                timestamp=datetime.now(timezone.utc),
            )
        )
    except Exception as exc:  # noqa: BLE001 -- cost logging must never break the flow
        logger.debug("cost tracker record failed: %s", exc)


def llm_filter_shortlist(
    candidates: list[VolRank],
    group_label: str,
    top_n: int = 20,
) -> list[VolRank]:
    """Filter ``candidates`` via Claude, returning the cleaned top-N.

    Args:
        candidates: Pre-ranked shortlist produced by the quant stage.
        group_label: Human-readable group name, e.g. ``"US equities"``.
        top_n: Final number of names to return.

    Returns:
        A list of up to ``top_n`` :class:`VolRank` objects. Every element that
        the LLM kept has ``kept_by_llm=True`` and a non-empty ``llm_reason``;
        if the LLM call fails the function degrades to ``candidates[:top_n]``
        with ``kept_by_llm=False``.
    """
    if not candidates:
        return []

    fallback: list[VolRank] = [
        replace(r, kept_by_llm=False, llm_reason=None) for r in candidates[:top_n]
    ]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("llm_filter: ANTHROPIC_API_KEY not set -- falling back to quant")
        return fallback

    try:
        import anthropic  # Lazy import so tests can run without the SDK loaded.
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_filter: anthropic SDK import failed: %s", exc)
        return fallback

    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_filter: anthropic client init failed: %s", exc)
        return fallback

    prompt = _build_user_prompt(candidates, group_label, top_n)

    try:
        resp = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_OUTPUT_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_filter: anthropic call failed: %s", exc)
        return fallback

    # Usage accounting -- best effort.
    try:
        usage = getattr(resp, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        _record_cost(in_tok, out_tok)
    except Exception as exc:  # noqa: BLE001
        logger.debug("llm_filter: usage extraction failed: %s", exc)

    # Extract the JSON.
    try:
        content_blocks = resp.content
        text_parts: list[str] = []
        for block in content_blocks:
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)
        raw = "\n".join(text_parts)
        parsed = _extract_json_array(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_filter: response parse failed: %s", exc)
        return fallback

    by_ticker: dict[str, VolRank] = {r.ticker.upper(): r for r in candidates}
    kept: list[VolRank] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker")
        reason = item.get("reason")
        if not isinstance(ticker, str):
            continue
        base = by_ticker.get(ticker.upper())
        if base is None:
            continue
        kept.append(
            replace(
                base,
                kept_by_llm=True,
                llm_reason=reason if isinstance(reason, str) else None,
            )
        )
        if len(kept) >= top_n:
            break

    if not kept:
        logger.info("llm_filter: LLM returned nothing usable -- falling back")
        return fallback
    return kept
