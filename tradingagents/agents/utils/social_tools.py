"""Social sentiment tools for the Social Media Analyst agent.

Provides tools that aggregate sentiment from multiple sources:
- ApeWisdom (Reddit mentions)
- Fear & Greed Index
- AAII Sentiment Survey
- Finnhub Social Sentiment
- Quiver Quant (congressional trades, lobbying)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _safe_fetch_connector(connector_name: str, ticker: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Try to fetch from a registered connector, return None on failure."""
    try:
        from tradingagents.dataflows.connectors.registry import ConnectorRegistry
        registry = ConnectorRegistry()
        connector = registry.get(connector_name)
        if connector:
            return connector.fetch(ticker, params)
    except Exception as e:
        logger.debug("Connector %s unavailable: %s", connector_name, e)
    return None


def _mock_social_sentiment(ticker: str) -> dict[str, Any]:
    """Return mock social sentiment data when no connectors available."""
    return {
        "ticker": ticker,
        "reddit": {
            "mentions_24h": 342,
            "mentions_7d": 2150,
            "rank": 5,
            "sentiment_score": 0.62,
            "top_subreddits": ["wallstreetbets", "stocks", "investing"],
        },
        "fear_greed": {
            "value": 38,
            "label": "Fear",
            "previous_close": 42,
            "one_week_ago": 55,
        },
        "aaii": {
            "bullish_pct": 28.4,
            "bearish_pct": 40.2,
            "neutral_pct": 31.4,
            "bull_bear_spread": -11.8,
            "survey_date": "2026-03-27",
        },
        "congressional": [
            {"politician": "Nancy Pelosi", "party": "D", "action": "buy", "ticker": ticker, "amount": "$250K-$500K", "date": "2026-03-15"},
            {"politician": "Dan Crenshaw", "party": "R", "action": "sell", "ticker": ticker, "amount": "$15K-$50K", "date": "2026-03-10"},
        ],
        "overall_sentiment": 0.35,
        "signal": "MIXED — retail cautious but institutional interest detected",
    }


@tool
def get_social_sentiment(ticker: str) -> str:
    """Get aggregated social media sentiment for a ticker from Reddit, Fear/Greed, AAII, and congressional trades.

    Args:
        ticker: Stock ticker symbol (e.g. 'AAPL')

    Returns:
        JSON string with sentiment data from multiple social sources.
    """
    result: dict[str, Any] = {"ticker": ticker, "timestamp": datetime.now().isoformat()}

    # 1. Try ApeWisdom for Reddit mentions
    ape_data = _safe_fetch_connector("apewisdom", ticker, {"data_type": "mentions"})
    if ape_data:
        result["reddit"] = ape_data
    else:
        # Try Quiver Quant
        quiver_data = _safe_fetch_connector("quiver", ticker, {"data_type": "reddit_sentiment"})
        if quiver_data:
            result["reddit"] = quiver_data

    # 2. Try Fear & Greed Index
    fg_data = _safe_fetch_connector("fear_greed", ticker, {"data_type": "current"})
    if fg_data:
        result["fear_greed"] = fg_data

    # 3. Try AAII Sentiment
    aaii_data = _safe_fetch_connector("aaii", ticker, {"data_type": "sentiment"})
    if aaii_data:
        result["aaii"] = aaii_data

    # 4. Try Finnhub social sentiment
    finnhub_data = _safe_fetch_connector("finnhub", ticker, {"data_type": "sentiment"})
    if finnhub_data:
        result["finnhub_sentiment"] = finnhub_data

    # 5. Try congressional trades
    cong_data = _safe_fetch_connector("quiver", ticker, {"data_type": "congressional_trades"})
    if cong_data:
        result["congressional"] = cong_data

    # If no real data from any source, use mock
    if len(result) <= 2:  # only ticker + timestamp
        mock = _mock_social_sentiment(ticker)
        result.update(mock)
        result["data_source"] = "mock"
    else:
        result["data_source"] = "live"

    return json.dumps(result, indent=2, default=str)


@tool
def get_fear_greed_index() -> str:
    """Get the current Fear & Greed Index value.

    Returns:
        JSON string with the current Fear & Greed Index value and label.
    """
    fg_data = _safe_fetch_connector("fear_greed", "", {"data_type": "current"})
    if fg_data:
        return json.dumps(fg_data, indent=2, default=str)

    # Mock data
    return json.dumps({
        "value": 38,
        "label": "Fear",
        "previous_close": 42,
        "one_week_ago": 55,
        "one_month_ago": 61,
        "description": "Market sentiment is in Fear territory, suggesting potential buying opportunity for contrarians.",
        "data_source": "mock",
    }, indent=2)


@tool
def get_congressional_trades(ticker: str) -> str:
    """Get recent congressional stock trades for a ticker.

    Args:
        ticker: Stock ticker symbol (e.g. 'AAPL')

    Returns:
        JSON string with recent congressional trades.
    """
    cong_data = _safe_fetch_connector("quiver", ticker, {"data_type": "congressional_trades"})
    if cong_data:
        return json.dumps(cong_data, indent=2, default=str)

    # Mock data
    return json.dumps({
        "ticker": ticker,
        "trades": [
            {"politician": "Nancy Pelosi", "party": "D", "action": "buy", "amount": "$250K-$500K", "date": "2026-03-15", "disclosure_date": "2026-03-20"},
            {"politician": "Dan Crenshaw", "party": "R", "action": "sell", "amount": "$15K-$50K", "date": "2026-03-10", "disclosure_date": "2026-03-18"},
            {"politician": "Tommy Tuberville", "party": "R", "action": "buy", "amount": "$50K-$100K", "date": "2026-03-05", "disclosure_date": "2026-03-12"},
        ],
        "summary": "Net congressional interest: BULLISH — more buy volume than sell in recent filings.",
        "data_source": "mock",
    }, indent=2)
