"""Batch signals routes for factor-screened trading signals."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v3", tags=["signals"])

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level signal cache
# ---------------------------------------------------------------------------
_signal_cache: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Default universes
# ---------------------------------------------------------------------------
NDX100: list[str] = [
    "AAPL", "MSFT", "NVDA", "AVGO", "AMZN", "META", "GOOG", "GOOGL", "TSLA", "COST",
    "NFLX", "AMD", "ADBE", "CRM", "PEP", "CSCO", "INTC", "QCOM", "TXN", "AMGN",
    "ISRG", "AMAT", "BKNG", "LRCX", "REGN", "VRTX", "PANW", "KLAC", "SNPS", "CDNS",
    "GILD", "MELI", "SBUX", "MDLZ", "ADI", "PYPL", "ABNB", "MNST", "NXPI", "LULU",
]

TOP_ETFS: list[str] = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY", "XLI", "XLC",
    "XLP", "XLE", "XLU", "XLRE", "XLB", "TLT", "HYG", "GLD", "USO",
]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ScreenRequest(BaseModel):
    """Input model for the screening endpoint."""

    tickers: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _screen_ticker(ticker: str, today: str) -> dict[str, Any]:
    """Run factor screening on a single ticker.

    Uses importlib to lazily load the materializer, factor_baseline, and
    screener modules, avoiding langchain import issues at module load time.

    Signal logic uses momentum_score as the primary indicator (the composite
    score is too dampened for screening).  Conviction is the highest absolute
    sub-score * 100.  Threshold for BUY/SHORT is +/-0.1.
    """
    import importlib

    try:
        materializer = importlib.import_module("tradingagents.data.materializer")
        factor_mod = importlib.import_module("tradingagents.signals.factor_baseline")
        screener_mod = importlib.import_module("tradingagents.data.screener")

        briefing = materializer.materialize_briefing(ticker, today)
        result = factor_mod.compute_factor_score(briefing)
        screen = screener_mod.screen_ticker(briefing)

        # --- Extract price data from the briefing ---
        price = round(float(briefing.price.price), 2)
        change_pct = round(float(briefing.price.change_1d_pct), 2)

        # --- Use individual sub-scores for conviction & signal ---
        momentum = float(result.get("momentum_score", 0.0))
        quality = float(result.get("quality_score", 0.0))
        value = float(result.get("value_score", 0.0))

        # Conviction = highest absolute sub-score, scaled to 0-100
        conviction = int(max(abs(momentum), abs(quality), abs(value)) * 100)

        # Lower threshold (0.1) using momentum as primary signal
        if momentum > 0.1:
            signal = "BUY"
        elif momentum < -0.1:
            signal = "SHORT"
        else:
            signal = "HOLD"

        # EV approximation from momentum
        ev_pct = round(momentum * 5, 2)

        # Build a rich one-liner with real data
        macd_arrow = "MACD\u25B2" if briefing.price.macd_above_signal else "MACD\u25BC"
        one_liner = (
            f"{ticker} ${price:.2f} | "
            f"RSI {briefing.price.rsi_14:.0f} | "
            f"{macd_arrow} | "
            f"Tier {screen.tier.value}"
        )

        # Consensus: count how many sub-scores agree on direction
        pos_count = sum(1 for s in (momentum, quality, value) if s > 0.1)
        neg_count = sum(1 for s in (momentum, quality, value) if s < -0.1)
        consensus = f"{max(pos_count, neg_count)}/3"

        return {
            "ticker": ticker,
            "price": price,
            "change_pct": change_pct,
            "signal": signal,
            "conviction": conviction,
            "expected_value_pct": ev_pct,
            "consensus": consensus,
            "delta": 0,
            "one_liner": one_liner,
            "analyzed_at": datetime.now().isoformat(),
        }
    except Exception:
        logger.exception("Factor screening failed for %s", ticker)
        return {
            "ticker": ticker,
            "price": 0.0,
            "change_pct": 0.0,
            "signal": "HOLD",
            "conviction": 0,
            "expected_value_pct": 0.0,
            "consensus": "0/3",
            "delta": 0,
            "one_liner": f"Screening failed for {ticker}",
            "analyzed_at": datetime.now().isoformat(),
        }


def _build_summary(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate summary statistics from a list of signal dicts."""
    buy_count = sum(1 for s in signals if s["signal"] == "BUY")
    short_count = sum(1 for s in signals if s["signal"] == "SHORT")
    hold_count = sum(1 for s in signals if s["signal"] == "HOLD")
    total = len(signals)
    avg_conviction = (
        round(sum(s["conviction"] for s in signals) / total, 1)
        if total > 0
        else 0.0
    )
    return {
        "total": total,
        "buy_count": buy_count,
        "short_count": short_count,
        "hold_count": hold_count,
        "avg_conviction": avg_conviction,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/signals")
async def get_signals() -> dict[str, Any]:
    """Return the latest cached signals for all screened tickers."""
    signals = list(_signal_cache.values())
    return {
        "signals": signals,
        "summary": _build_summary(signals),
    }


@router.post("/signals/screen")
async def screen_tickers(request: ScreenRequest) -> dict[str, Any]:
    """Run factor screening on a list of tickers (no LLM required).

    For each ticker, materializes a briefing and computes a factor score.
    Results are stored in the module-level cache.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    results: list[dict[str, Any]] = []

    for ticker in request.tickers:
        upper_ticker = ticker.upper().strip()
        if not upper_ticker:
            continue

        # Detect changes against previous cache entry
        prev = _signal_cache.get(upper_ticker)
        entry = _screen_ticker(upper_ticker, today)

        if prev is not None and prev["signal"] != entry["signal"]:
            # Compute delta as conviction change (positive = stronger, negative = weaker)
            prev_conv = prev.get("conviction", 0)
            curr_conv = entry["conviction"]
            entry = {**entry, "delta": curr_conv - prev_conv}

        _signal_cache[upper_ticker] = entry
        results.append(entry)

    return {
        "signals": results,
        "summary": _build_summary(results),
    }


@router.get("/universe")
async def get_universe() -> dict[str, list[str]]:
    """Return the default ticker universes."""
    return {
        "ndx100": list(NDX100),
        "top_etfs": list(TOP_ETFS),
        "combined": sorted(set(NDX100 + TOP_ETFS)),
    }
