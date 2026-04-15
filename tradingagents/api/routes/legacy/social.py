"""Social sentiment routes."""

from __future__ import annotations

import json
import os
import random
from datetime import datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["social"])


def _mock_social(ticker: str) -> dict[str, Any]:
    """Realistic mock social sentiment data."""
    base_mentions = random.randint(100, 2000)
    sentiment = round(random.uniform(-0.5, 0.8), 2)
    fg_value = random.randint(15, 75)
    fg_label = (
        "Extreme Fear" if fg_value < 25
        else "Fear" if fg_value < 45
        else "Neutral" if fg_value < 55
        else "Greed" if fg_value < 75
        else "Extreme Greed"
    )
    return {
        "ticker": ticker,
        "reddit": {
            "mentions_24h": base_mentions,
            "mentions_7d": base_mentions * 6,
            "rank": random.randint(1, 50),
            "sentiment_score": sentiment,
            "top_subreddits": ["wallstreetbets", "stocks", "investing"],
        },
        "fear_greed": {
            "value": fg_value,
            "label": fg_label,
            "previous_close": fg_value + random.randint(-5, 5),
            "one_week_ago": fg_value + random.randint(-15, 15),
        },
        "aaii": {
            "bullish_pct": round(random.uniform(20, 45), 1),
            "bearish_pct": round(random.uniform(25, 50), 1),
            "neutral_pct": round(random.uniform(25, 40), 1),
            "survey_date": "2026-03-27",
        },
        "congressional": [
            {"politician": "Nancy Pelosi", "party": "D", "action": "buy",
             "ticker": ticker, "amount": "$250K-$500K", "date": "2026-03-15"},
            {"politician": "Tommy Tuberville", "party": "R", "action": "buy",
             "ticker": ticker, "amount": "$50K-$100K", "date": "2026-03-05"},
        ],
        "overall_sentiment": sentiment,
        "data_source": "mock",
    }


@router.get("/social/{ticker}")
async def get_social_sentiment(ticker: str) -> dict[str, Any]:
    """Aggregated social sentiment for a ticker."""
    # Try real sources first
    results: dict[str, Any] = {"ticker": ticker, "timestamp": datetime.now().isoformat()}

    # Try Finnhub social sentiment
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if finnhub_key:
        try:
            import requests as req
            resp = req.get(
                f"https://finnhub.io/api/v1/stock/social-sentiment?symbol={ticker}&from=2026-01-01",
                headers={"X-Finnhub-Token": finnhub_key},
                timeout=5,
            )
            if resp.ok:
                data = resp.json()
                results["finnhub"] = data
        except Exception:
            pass

    # If no real data, return mock
    if len(results) <= 2:
        return _mock_social(ticker)

    results["data_source"] = "live"
    return results


@router.get("/congressional/{ticker}")
async def get_congressional_trades(ticker: str) -> dict[str, Any]:
    """Congressional stock trades for a ticker."""
    quiver_key = os.environ.get("QUIVER_API_KEY", "")
    if quiver_key:
        try:
            import requests as req
            resp = req.get(
                f"https://api.quiverquant.com/beta/live/congresstrading/{ticker}",
                headers={"Authorization": f"Bearer {quiver_key}"},
                timeout=5,
            )
            if resp.ok:
                return {"ticker": ticker, "trades": resp.json()[:10], "data_source": "live"}
        except Exception:
            pass

    # Mock data
    return {
        "ticker": ticker,
        "trades": [
            {"politician": "Nancy Pelosi", "party": "D", "action": "buy",
             "amount": "$250K-$500K", "date": "2026-03-15", "disclosure_date": "2026-03-20"},
            {"politician": "Dan Crenshaw", "party": "R", "action": "sell",
             "amount": "$15K-$50K", "date": "2026-03-10", "disclosure_date": "2026-03-18"},
            {"politician": "Tommy Tuberville", "party": "R", "action": "buy",
             "amount": "$50K-$100K", "date": "2026-03-05", "disclosure_date": "2026-03-12"},
            {"politician": "Mark Warner", "party": "D", "action": "sell",
             "amount": "$100K-$250K", "date": "2026-02-28", "disclosure_date": "2026-03-08"},
        ],
        "data_source": "mock",
    }
