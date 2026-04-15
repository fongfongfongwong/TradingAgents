"""F11: Analysis Pipeline Runner -- end-to-end orchestration.

Runs the complete v3 analysis pipeline for a single ticker:
  0. Materialize data (TickerBriefing)
  1. Screen ticker (tier classification)
  2. If Tier 3: return factor-only decision (no LLM)
  3. If Tier 1/2: run Thesis + Antithesis + Base Rate (parallel-ready)
  4. Synthesis (judge)
  5. Risk evaluation
  6. Assemble FinalDecision
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from tradingagents.gateway.cost_tracker import get_cost_tracker
from tradingagents.schemas.v3 import (
    AntithesisOutput,
    BaseRateOutput,
    FinalDecision,
    RiskOutput,
    ScreeningResult,
    Signal,
    SynthesisOutput,
    ThesisOutput,
    Tier,
    TickerBriefing,
)


def _resolve_model_versions() -> dict[str, str]:
    """Read model versions from RuntimeConfig, falling back to hardcoded defaults."""
    _FALLBACK = {
        "thesis": "claude-sonnet-4-5",
        "antithesis": "claude-sonnet-4-5",
        "base_rate": "claude-sonnet-4-5",
        "synthesis": "claude-sonnet-4-5",
    }
    try:
        from tradingagents.api.routes.config import get_runtime_config

        cfg = get_runtime_config()
        return {
            "thesis": cfg.thesis_model,
            "antithesis": cfg.antithesis_model,
            "base_rate": cfg.base_rate_model,
            "synthesis": cfg.synthesis_model,
        }
    except Exception:
        return _FALLBACK


_log = logging.getLogger(__name__)


def _resolve_pipeline_cost(ticker: str, date_str: str) -> float:
    """Read pipeline cost from cost tracker, falling back to 0.0."""
    try:
        from datetime import date as _date

        day = _date.fromisoformat(date_str)
        return get_cost_tracker().ticker_total_usd(ticker, day=day)
    except Exception:
        _log.warning(
            "Failed to resolve pipeline cost for %s on %s; defaulting to 0.0",
            ticker,
            date_str,
            exc_info=True,
        )
        return 0.0


def _extract_divergence_signals(briefing: TickerBriefing) -> dict[str, dict]:
    """Extract raw signal dicts from a TickerBriefing for the DivergenceEngine.

    Each dimension returns ``{"value": float, "sources": list[str]}``.
    Missing or unavailable dimensions are omitted so the engine applies
    its graceful-degradation (zero-fill) logic.
    """
    signals: dict[str, dict] = {}

    # -- institutional --
    inst = getattr(briefing, "institutional", None)
    if inst is not None and getattr(inst, "fetched_ok", False):
        # Positive net buys -> bullish signal; normalize loosely
        net = getattr(inst, "congressional_net_buys_30d", 0) + getattr(
            inst, "insider_net_txns_90d", 0
        )
        value = max(-1.0, min(1.0, net / 10.0))
        sources = []
        if getattr(inst, "congressional_net_buys_30d", 0) != 0:
            sources.append("congressional")
        if getattr(inst, "insider_net_txns_90d", 0) != 0:
            sources.append("insider_form4")
        if getattr(inst, "govt_contracts_count_90d", 0) > 0:
            sources.append("govt_contracts")
        signals["institutional"] = {"value": value, "sources": sources}

    # -- options --
    opts = getattr(briefing, "options", None)
    if opts is not None:
        pcr = getattr(opts, "put_call_ratio", None)
        if pcr is not None:
            # Elevated P/C ratio -> bearish (inverted); neutral around 0.7
            value = max(-1.0, min(1.0, -(pcr - 0.7) / 0.5))
            sources = ["put_call_ratio"]
            if getattr(opts, "iv_rank_percentile", None) is not None:
                sources.append("iv_rank")
            signals["options"] = {"value": value, "sources": sources}

    # -- price_action --
    price = getattr(briefing, "price", None)
    if price is not None:
        rsi = getattr(price, "rsi_14", 50.0)
        # RSI rescaled: 50 -> 0, 70 -> +1, 30 -> -1
        value = max(-1.0, min(1.0, (rsi - 50.0) / 20.0))
        sources = ["rsi_14"]
        if getattr(price, "macd_above_signal", None) is not None:
            sources.append("macd")
        if getattr(price, "volume_vs_avg_20d", None) is not None:
            sources.append("volume")
        signals["price_action"] = {"value": value, "sources": sources}

    # -- news --
    news = getattr(briefing, "news", None)
    if news is not None:
        sent = getattr(news, "headline_sentiment_avg", 0.0)
        value = max(-1.0, min(1.0, sent))
        sources = ["headline_sentiment"]
        if getattr(news, "top_headlines", None):
            sources.append("headlines")
        signals["news"] = {"value": value, "sources": sources}

    # -- retail (social) --
    social = getattr(briefing, "social", None)
    if social is not None:
        sent = getattr(social, "sentiment_score", 0.0)
        vol_ratio = getattr(social, "mention_volume_vs_avg", 1.0)
        # Scale sentiment by volume spike (capped at 2x)
        value = max(-1.0, min(1.0, sent * min(vol_ratio, 2.0)))
        sources = ["social_sentiment"]
        if vol_ratio > 1.5:
            sources.append("mention_spike")
        signals["retail"] = {"value": value, "sources": sources}

    return signals


def _compute_divergence_from_briefing(
    briefing: TickerBriefing,
) -> tuple[float | None, str | None]:
    """Run the DivergenceEngine against a TickerBriefing.

    Returns (composite_score, human_summary) or (None, None) on failure.
    """
    try:
        from tradingagents.divergence.engine import DivergenceEngine
        from tradingagents.divergence.regime import RegimeDetector

        raw_signals = _extract_divergence_signals(briefing)
        # Detect regime from macro context
        macro = getattr(briefing, "macro", None)
        vix = getattr(macro, "vix_level", None) if macro else None
        opts = getattr(briefing, "options", None)
        pcr = getattr(opts, "put_call_ratio", None) if opts else None
        regime = RegimeDetector().detect(vix=vix, put_call_ratio=pcr)

        engine = DivergenceEngine()
        vector = engine.compute(briefing.ticker, raw_signals, regime=regime)
        return vector.composite_score, vector.to_agent_summary()
    except Exception:
        _log.debug("Divergence computation failed (non-fatal)", exc_info=True)
        return None, None


def _derive_options_signal(
    briefing: TickerBriefing,
) -> tuple[str | None, int | None]:
    """Derive a (direction, impact) pair from the briefing's OptionsContext.

    Thin wrapper around the shared helper in
    :mod:`tradingagents.signals.options_signal` so runner and divergence
    route stay in lockstep. Uses widened +/-0.25 thresholds with optional
    hysteresis (previous_direction is None here; could be threaded from
    cache in the future).
    """
    from tradingagents.signals.options_signal import derive_options_signal

    options = getattr(briefing, "options", None)
    return derive_options_signal(options, previous_direction=None)


_MODULE_CACHE: dict[str, types.ModuleType] = {}
_MODULE_CACHE_LOCK = threading.Lock()


def _load_agent_module(filename: str) -> types.ModuleType:
    """Load an agent module via importlib to avoid langchain __init__ side-effects.

    Returns the loaded module so callers can access the entry function and
    module-level constants like ``_PROMPT_VERSION``.

    Modules are cached so top-level code only runs once.
    """
    import os

    base = os.path.join(
        os.path.dirname(__file__), os.pardir, "agents", "v3", filename
    )
    path = os.path.normpath(base)

    with _MODULE_CACHE_LOCK:
        if path in _MODULE_CACHE:
            return _MODULE_CACHE[path]

        spec = importlib.util.spec_from_file_location(filename, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULE_CACHE[path] = mod
        return mod


def _load_agent(filename: str, funcname: str):
    """Backward-compatible helper returning the entry function only."""
    return getattr(_load_agent_module(filename), funcname)


def run_analysis(
    ticker: str,
    date: str | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> FinalDecision:
    """Run the complete v3 analysis pipeline for a single ticker.

    Stages:
      0. Materialize data (TickerBriefing)
      1. Screen ticker (tier classification)
      2. If Tier 3: return factor-only decision (no LLM)
      3. If Tier 1/2: run Thesis + Antithesis + Base Rate (parallel-ready)
      4. Synthesis (judge)
      5. Risk evaluation
      6. Assemble FinalDecision

    on_event: optional callback for SSE streaming.
      Called with (event_type, data_dict) at each stage completion.
      Event types: "materialized", "screened", "thesis_complete",
                   "antithesis_complete", "base_rate_complete",
                   "synthesis_complete", "risk_complete", "pipeline_complete"

    date: defaults to today if None.
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    start = time.time()

    def emit(event_type: str, data: dict) -> None:
        if on_event is not None:
            on_event(event_type, data)

    # ── Stage 0: Materialize ────────────────────────────────────────
    from tradingagents.data.materializer import materialize_briefing

    briefing = materialize_briefing(ticker, date)
    emit("materialized", {"ticker": ticker, "snapshot_id": briefing.snapshot_id})

    # ── Stage 1: Screen ─────────────────────────────────────────────
    from tradingagents.data.screener import screen_ticker

    screening = screen_ticker(briefing)
    emit(
        "screened",
        {
            "ticker": ticker,
            "tier": screening.tier.value,
            "reasons": screening.trigger_reasons,
        },
    )

    # ── Stage 2: Factor baseline (always computed) ──────────────────
    from tradingagents.signals.factor_baseline import compute_factor_score

    factor = compute_factor_score(briefing)

    # Second-dimension briefing-derived signals for the signals table.
    options_direction, options_impact = _derive_options_signal(briefing)
    price_ctx = getattr(briefing, "price", None)
    realized_vol_20d_pct = getattr(price_ctx, "realized_vol_20d_pct", None)
    atr_pct_of_price = getattr(price_ctx, "atr_pct_of_price", None)

    # ── Stage 3: If Tier 3, return factor-only decision ─────────────
    if screening.tier == Tier.SCREEN:
        elapsed = int((time.time() - start) * 1000)
        decision = FinalDecision(
            ticker=ticker,
            date=date,
            snapshot_id=briefing.snapshot_id,
            tier=screening.tier,
            screening=screening,
            factor_baseline_score=factor["composite_score"],
            signal=factor["signal"],
            conviction=int(abs(factor["composite_score"]) * 100),
            pipeline_cost_usd=_resolve_pipeline_cost(ticker, date),
            pipeline_latency_ms=elapsed,
            data_gaps=list(briefing.data_gaps),
            options_direction=options_direction,
            options_impact=options_impact,
            realized_vol_20d_pct=realized_vol_20d_pct,
            atr_pct_of_price=atr_pct_of_price,
            volatility=getattr(briefing, "volatility", None),
        )
        emit(
            "pipeline_complete",
            {
                "ticker": ticker,
                "signal": decision.signal.value,
                "conviction": decision.conviction,
                "shares": decision.final_shares,
                "latency_ms": elapsed,
            },
        )
        return decision

    # ── Stage 4: Run 3 agents in parallel ────────────────────────────
    thesis_mod = _load_agent_module("thesis_agent.py")
    antithesis_mod = _load_agent_module("antithesis_agent.py")
    base_rate_mod = _load_agent_module("base_rate_agent.py")
    run_thesis = getattr(thesis_mod, "run_thesis_agent")
    run_antithesis = getattr(antithesis_mod, "run_antithesis_agent")
    run_base_rate = getattr(base_rate_mod, "run_base_rate_agent")

    # Mock factory functions -- called directly when the real agent fails,
    # avoiding the old os.environ mutation which was a race condition.
    _mock_fns: dict[str, Callable] = {
        "thesis": getattr(thesis_mod, "_mock_thesis"),
        "antithesis": getattr(antithesis_mod, "_mock_antithesis"),
        "base_rate": getattr(base_rate_mod, "_mock_base_rate"),
    }

    _emit_map: dict[str, Callable] = {
        "thesis": lambda r: emit(
            "thesis_complete",
            {"ticker": ticker, "confidence": r.confidence_score},
        ),
        "antithesis": lambda r: emit(
            "antithesis_complete",
            {"ticker": ticker, "confidence": r.confidence_score},
        ),
        "base_rate": lambda r: emit(
            "base_rate_complete",
            {"ticker": ticker, "prob_up": r.base_rate_probability_up},
        ),
    }

    agent_results: dict[str, ThesisOutput | AntithesisOutput | BaseRateOutput] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(run_thesis, briefing): "thesis",
            pool.submit(run_antithesis, briefing): "antithesis",
            pool.submit(run_base_rate, briefing): "base_rate",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                agent_results[name] = future.result()
            except Exception:
                _log.warning(
                    "Agent %s failed; falling back to mock", name, exc_info=True
                )
                agent_results[name] = _mock_fns[name](briefing)
            _emit_map[name](agent_results[name])

    thesis: ThesisOutput = agent_results["thesis"]  # type: ignore[assignment]
    antithesis: AntithesisOutput = agent_results["antithesis"]  # type: ignore[assignment]
    base_rate: BaseRateOutput = agent_results["base_rate"]  # type: ignore[assignment]

    # ── Stage 4b: Divergence Engine ─────────────────────────────────
    divergence_score, divergence_summary = _compute_divergence_from_briefing(briefing)
    if divergence_score is not None:
        emit(
            "divergence_complete",
            {"ticker": ticker, "score": divergence_score},
        )

    # ── Stage 5: Synthesis ──────────────────────────────────────────
    synthesis_mod = _load_agent_module("synthesis_agent.py")
    run_synth = getattr(synthesis_mod, "run_synthesis_agent")
    synthesis: SynthesisOutput = run_synth(
        thesis, antithesis, base_rate, divergence_context=divergence_summary,
    )
    emit(
        "synthesis_complete",
        {
            "ticker": ticker,
            "signal": synthesis.signal.value,
            "conviction": synthesis.conviction,
        },
    )

    # ── Stage 6: Risk ───────────────────────────────────────────────
    from tradingagents.risk.deterministic import evaluate_risk

    risk: RiskOutput = evaluate_risk(synthesis, portfolio_nav=100_000)
    emit(
        "risk_complete",
        {
            "ticker": ticker,
            "shares": risk.final_shares,
            "rating": risk.risk_rating,
        },
    )

    # ── Stage 7: Store snapshot ─────────────────────────────────────
    from tradingagents.data.snapshot import init_db, store_snapshot

    init_db()
    store_snapshot(briefing)

    # ── Assemble FinalDecision ──────────────────────────────────────
    elapsed = int((time.time() - start) * 1000)

    decision = FinalDecision(
        ticker=ticker,
        date=date,
        snapshot_id=briefing.snapshot_id,
        tier=screening.tier,
        screening=screening,
        thesis=thesis,
        antithesis=antithesis,
        base_rate=base_rate,
        synthesis=synthesis,
        risk=risk,
        factor_baseline_score=factor["composite_score"],
        signal=synthesis.signal,
        conviction=synthesis.conviction,
        final_shares=risk.final_shares,
        model_versions=_resolve_model_versions(),
        prompt_versions={
            "thesis": getattr(thesis_mod, "_PROMPT_VERSION", 0),
            "antithesis": getattr(antithesis_mod, "_PROMPT_VERSION", 0),
            "base_rate": getattr(base_rate_mod, "_PROMPT_VERSION", 0),
            "synthesis": getattr(synthesis_mod, "_PROMPT_VERSION", 0),
        },
        any_agent_used_mock=any(
            [
                getattr(thesis, "used_mock", False),
                getattr(antithesis, "used_mock", False),
                getattr(base_rate, "used_mock", False),
                getattr(synthesis, "used_mock", False),
            ]
        ),
        pipeline_cost_usd=_resolve_pipeline_cost(ticker, date),
        pipeline_latency_ms=elapsed,
        data_gaps=list(briefing.data_gaps),
        options_direction=options_direction,
        options_impact=options_impact,
        realized_vol_20d_pct=realized_vol_20d_pct,
        atr_pct_of_price=atr_pct_of_price,
        volatility=getattr(briefing, "volatility", None),
        divergence_score=divergence_score,
        divergence_summary=divergence_summary,
    )
    emit(
        "pipeline_complete",
        {
            "ticker": ticker,
            "signal": decision.signal.value,
            "conviction": decision.conviction,
            "shares": decision.final_shares,
            "latency_ms": elapsed,
        },
    )

    return decision


# ── Inline tests ────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import sys

    _project_root = str(Path(__file__).resolve().parents[2])
    sys.path.insert(0, _project_root)
    os.chdir(_project_root)

    events: list[tuple[str, dict]] = []

    def capture(event_type: str, data: dict) -> None:
        events.append((event_type, data))
        print(f"  [{event_type}] {data}")

    # Test 1: Full pipeline (mock mode -- no API key)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    result = run_analysis("AAPL", on_event=capture)
    assert isinstance(result, FinalDecision)
    assert result.ticker == "AAPL"
    assert result.signal in [Signal.BUY, Signal.SHORT, Signal.HOLD]
    assert len(events) > 0
    print(
        f"\nTest 1 PASSED: Mock pipeline -> {result.signal.value}, "
        f"conv={result.conviction}, {result.pipeline_latency_ms}ms"
    )

    # Test 2: Events fired
    event_types = [e[0] for e in events]
    assert "materialized" in event_types
    assert "screened" in event_types
    print(f"Test 2 PASSED: {len(events)} events fired")

    # Test 3: Real API pipeline
    if os.environ.get("ANTHROPIC_API_KEY"):
        events2: list[tuple[str, dict]] = []
        real = run_analysis(
            "TSLA", on_event=lambda t, d: events2.append((t, d))
        )
        assert isinstance(real, FinalDecision)
        print(
            f"\nTest 3 PASSED: Real pipeline -> {real.signal.value}, "
            f"conv={real.conviction}"
        )
    else:
        print("Test 3 SKIPPED: No API key")

    print("\nAll tests PASSED")
