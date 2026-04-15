"""Divergence analysis routes.

Computes a 5-dimensional divergence score directly from the v3 TickerBriefing,
using the same data sources (Polygon/Finnhub/Quiver/CBOE/Fear&Greed/ApeWisdom)
that feed the debate agents. Values are in ``[-1, +1]`` where negative = bearish
divergence (price holding up vs deteriorating signals) and positive = bullish
divergence (price lagging vs improving signals).

Dimensions:
  - institutional: congressional net + insider net + lobbying signal (Quiver)
  - options: IV skew + put/call ratio + unusual activity (CBOE/yfinance)
  - price_action: momentum vs SMA + RSI extremes (Polygon/yfinance)
  - news: sentiment + event_flags (Finnhub)
  - retail: social sentiment + fear_greed + trending (Fear&Greed + ApeWisdom)

Composite is the DEFAULT_WEIGHTS-weighted sum, regime-modulated.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from ..models.responses import DivergenceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["divergence"])


# Weights summing to 1.0 (mirror DivergenceAggregator.DEFAULT_WEIGHTS)
_WEIGHTS: dict[str, float] = {
    "institutional": 0.35,
    "options": 0.25,
    "price_action": 0.20,
    "news": 0.15,
    "retail": 0.05,
}


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _compute_institutional(institutional: Any) -> dict[str, Any]:
    """Score from Quiver InstitutionalContext. Positive = bullish institutional signal."""
    if not institutional or not getattr(institutional, "fetched_ok", False):
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}
    congress_net = float(getattr(institutional, "congressional_net_buys_30d", 0))
    insider_net = float(getattr(institutional, "insider_net_txns_90d", 0))
    lobbying = float(getattr(institutional, "lobbying_usd_last_quarter", 0.0))
    # Normalize to roughly [-1, 1]
    congress_score = _clamp(congress_net / 5.0)        # 5+ net buys = max bullish
    insider_score = _clamp(insider_net / 10.0)         # 10+ insider buys = max bullish
    # Lobbying alone doesn't signal direction; use as confidence booster only
    value = 0.6 * congress_score + 0.4 * insider_score
    return {
        "value": round(_clamp(value), 4),
        "confidence": 0.8,
        "sources": ["quiver_congress", "quiver_insiders", "quiver_lobbying"],
        "raw_data": {
            "congress_net_30d": congress_net,
            "insider_net_90d": insider_net,
            "lobbying_usd_q": lobbying,
        },
    }


def _compute_options(options: Any) -> dict[str, Any]:
    """Score from OptionsContext using shared helper.

    Delegates to :func:`tradingagents.signals.options_signal.compute_options_value`
    so runner.py and divergence.py stay in lockstep.
    """
    from tradingagents.signals.options_signal import compute_options_value

    if options is None:
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}

    value, confidence = compute_options_value(options)

    return {
        "value": round(value, 4),
        "confidence": round(confidence, 4),
        "sources": ["polygon_options", "yfinance_options"],
        "raw_data": {
            "put_call_ratio": getattr(options, "put_call_ratio", None),
            "iv_skew_25d": getattr(options, "iv_skew_25d", None),
            "iv_rank_pct": getattr(options, "iv_rank_percentile", None),
        },
    }


def _compute_price_action(price: Any) -> dict[str, Any]:
    """Score from PriceContext. Uses multi-timeframe momentum + RSI."""
    if price is None:
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}
    change_20d = getattr(price, "change_20d_pct", None)
    rsi = getattr(price, "rsi_14", None)
    macd_above = getattr(price, "macd_above_signal", None)
    sma_20 = getattr(price, "sma_20", None)
    px = getattr(price, "price", None)
    if change_20d is None and rsi is None:
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}
    # 20-day return: -10% to +10% maps to -1 to +1
    momentum_score = 0.0
    if change_20d is not None:
        momentum_score = _clamp(float(change_20d) / 10.0)
    # RSI: 30-70 maps to -1 to +1 (centered at 50)
    rsi_score = 0.0
    if rsi is not None:
        rsi_score = _clamp((float(rsi) - 50.0) / 20.0)
    # MACD bonus
    macd_score = 0.0
    if macd_above is not None:
        macd_score = 0.3 if macd_above else -0.3
    # SMA relation
    sma_score = 0.0
    if sma_20 is not None and px is not None and sma_20 > 0:
        sma_score = _clamp((float(px) - float(sma_20)) / float(sma_20) * 5.0)
    value = 0.4 * momentum_score + 0.3 * rsi_score + 0.15 * macd_score + 0.15 * sma_score
    return {
        "value": round(_clamp(value), 4),
        "confidence": 0.9,
        "sources": ["polygon_aggregates", "yfinance_history"],
        "raw_data": {
            "change_20d_pct": change_20d,
            "rsi_14": rsi,
            "macd_above_signal": macd_above,
            "price": px,
            "sma_20": sma_20,
        },
    }


def _compute_news(news: Any) -> dict[str, Any]:
    """Score from NewsContext. Sentiment + event_flags lean."""
    if news is None:
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}
    sentiment = getattr(news, "headline_sentiment_avg", None)
    flags = list(getattr(news, "event_flags", []) or [])
    headlines_count = len(getattr(news, "top_headlines", []) or [])
    if sentiment is None and not flags:
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}
    sentiment_score = float(sentiment) if sentiment is not None else 0.0
    # Event flags: upgrade/beat = +0.3 each; downgrade/miss = -0.3 each
    positive_flags = {"upgrade", "earnings_beat", "guidance_raise", "buyback",
                      "dividend_raise", "m&a", "fda_approval", "contract_win"}
    negative_flags = {"downgrade", "earnings_miss", "guidance_cut", "lawsuit",
                      "sec_investigation", "recall", "dividend_cut", "fda_rejection"}
    flag_score = 0.0
    for f in flags:
        if f in positive_flags:
            flag_score += 0.3
        elif f in negative_flags:
            flag_score -= 0.3
    flag_score = _clamp(flag_score)
    value = 0.6 * _clamp(sentiment_score) + 0.4 * flag_score
    confidence = 0.5 + min(0.4, headlines_count * 0.08)
    return {
        "value": round(_clamp(value), 4),
        "confidence": round(confidence, 2),
        "sources": ["finnhub_news", "yfinance_news"],
        "raw_data": {
            "sentiment_avg": sentiment,
            "event_flags": flags,
            "headlines_count": headlines_count,
        },
    }


def _compute_retail(social: Any) -> dict[str, Any]:
    """Score from SocialContext (Fear&Greed + ApeWisdom)."""
    if social is None:
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}
    sentiment = getattr(social, "sentiment_score", None)
    mention_vol = getattr(social, "mention_volume_vs_avg", None)
    narratives = list(getattr(social, "trending_narratives", []) or [])
    if sentiment is None:
        return {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}}
    value = _clamp(float(sentiment))
    confidence = 0.4 + min(0.4, (float(mention_vol or 1.0) - 1.0) * 0.3)
    return {
        "value": round(value, 4),
        "confidence": round(_clamp(confidence, 0.0, 1.0), 2),
        "sources": ["cnn_fear_greed", "apewisdom"],
        "raw_data": {
            "sentiment_score": sentiment,
            "mention_volume_vs_avg": mention_vol,
            "narratives": narratives,
        },
    }


def _regime_from_briefing(briefing: Any) -> str:
    """Return the briefing's pre-computed macro regime."""
    macro = getattr(briefing, "macro", None)
    if macro is None:
        return "TRANSITIONING"
    regime = getattr(macro, "regime", None)
    if regime is None:
        return "TRANSITIONING"
    return getattr(regime, "value", str(regime))


@router.get("/divergence/{ticker}", response_model=DivergenceResponse)
async def get_divergence(ticker: str) -> DivergenceResponse:
    """Compute 5-dimensional divergence score from a fresh TickerBriefing.

    Reuses the v3 materializer path so the divergence panel sees the same
    real data (Polygon/Finnhub/Quiver/CBOE/Fear&Greed) the debate agents use.
    """
    ticker = ticker.upper()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from tradingagents.data.materializer import materialize_briefing

    try:
        briefing = await asyncio.to_thread(materialize_briefing, ticker, date)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to materialize briefing for %s", ticker)
        return DivergenceResponse(
            ticker=ticker,
            regime="TRANSITIONING",
            composite_score=0.0,
            dimensions={
                "institutional": {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {"error": str(exc)[:160]}},
                "options": {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}},
                "price_action": {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}},
                "news": {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}},
                "retail": {"value": 0.0, "confidence": 0.0, "sources": [], "raw_data": {}},
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    dims: dict[str, dict[str, Any]] = {
        "institutional": _compute_institutional(getattr(briefing, "institutional", None)),
        "options": _compute_options(getattr(briefing, "options", None)),
        "price_action": _compute_price_action(getattr(briefing, "price", None)),
        "news": _compute_news(getattr(briefing, "news", None)),
        "retail": _compute_retail(getattr(briefing, "social", None)),
    }

    composite = sum(dims[k]["value"] * _WEIGHTS[k] for k in _WEIGHTS)
    composite = round(_clamp(composite), 4)

    return DivergenceResponse(
        ticker=ticker,
        regime=_regime_from_briefing(briefing),
        composite_score=composite,
        dimensions=dims,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
