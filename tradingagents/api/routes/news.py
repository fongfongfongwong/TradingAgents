"""News routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["news"])


@router.get("/news/{ticker}")
async def get_news(ticker: str) -> list[dict[str, Any]]:
    """Return recent news items for a ticker (max 20)."""
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        raw_news = t.news
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"yfinance error: {exc}") from exc

    if not raw_news:
        return []

    items: list[dict[str, Any]] = []
    for article in raw_news[:20]:
        # yfinance v2 wraps data in a 'content' object
        content = article.get("content", article)
        provider = content.get("provider", {})

        title = content.get("title", "") or article.get("title", "")
        source = (
            provider.get("displayName", "")
            if isinstance(provider, dict)
            else str(provider)
        ) or article.get("publisher", "")
        url = ""
        canonical = content.get("canonicalUrl", {})
        if isinstance(canonical, dict):
            url = canonical.get("url", "")
        if not url:
            url = article.get("link", "")
        pub_date = (
            content.get("pubDate")
            or content.get("displayTime")
            or article.get("providerPublishTime")
        )
        summary = content.get("summary") or content.get("description") or None

        items.append(
            {
                "title": title,
                "source": source,
                "url": url,
                "published_at": pub_date,
                "sentiment": None,
                "relevance": None,
                "summary": summary[:200] if summary else None,
            }
        )

    return items
