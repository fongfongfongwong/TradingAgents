"""V3 scored news endpoint.

Fetches headlines via yfinance and runs them through
:mod:`tradingagents.data.sources.news_scorer` to produce impact-ranked output
for the terminal UI. Graceful on upstream failures — never raises 5xx.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from tradingagents.api.models.responses import ScoredHeadline
from tradingagents.data.sources.news_scorer import RawHeadline, score_headlines

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["news_v3"])


def _fetch_yfinance_news(ticker: str) -> list[dict[str, Any]]:
    """Blocking yfinance fetch. Returns [] on any failure."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        raw = t.news or []
        return list(raw)
    except Exception as exc:  # pragma: no cover - network path
        logger.warning("yfinance news fetch failed for %s: %s", ticker, exc)
        return []


def _parse_published_at(content: dict[str, Any], article: dict[str, Any]) -> datetime | None:
    """Extract a timezone-aware ``datetime`` from a yfinance news item."""
    # yfinance v2 shape: pubDate/displayTime are ISO strings inside content.
    iso_value = content.get("pubDate") or content.get("displayTime")
    if isinstance(iso_value, str) and iso_value:
        try:
            # ``fromisoformat`` accepts the +00:00 and Z-less variants used by yfinance.
            cleaned = iso_value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

    ts = article.get("providerPublishTime")
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    return None


def _to_raw_headline(article: dict[str, Any]) -> RawHeadline | None:
    content = article.get("content", article) if isinstance(article, dict) else {}
    if not isinstance(content, dict):
        content = {}

    title = (content.get("title") or article.get("title") or "").strip()
    if not title:
        return None

    provider = content.get("provider", {})
    if isinstance(provider, dict):
        source = provider.get("displayName") or article.get("publisher") or None
    else:
        source = str(provider) if provider else article.get("publisher") or None

    canonical = content.get("canonicalUrl", {})
    url: str | None = None
    if isinstance(canonical, dict):
        url = canonical.get("url") or None
    if not url:
        url = article.get("link") or None

    summary = content.get("summary") or content.get("description") or None
    if isinstance(summary, str):
        summary = summary.strip() or None
    else:
        summary = None

    published_at = _parse_published_at(content, article)

    return RawHeadline(
        title=title,
        source=source,
        url=url,
        published_at=published_at,
        summary=summary,
    )


@router.get("/news/{ticker}/scored", response_model=list[ScoredHeadline])
async def get_scored_news(ticker: str, limit: int = 20) -> list[ScoredHeadline]:
    """Return prioritized headlines for ``ticker``, sorted by impact descending.

    Upstream (yfinance) failures degrade to an empty list — the endpoint
    never returns a 5xx so the UI can render a quiet empty state.
    """
    if limit <= 0:
        return []
    capped_limit = min(limit, 100)

    raw_articles = await asyncio.to_thread(_fetch_yfinance_news, ticker)
    if not raw_articles:
        return []

    raw_headlines: list[RawHeadline] = []
    for article in raw_articles:
        if not isinstance(article, dict):
            continue
        parsed = _to_raw_headline(article)
        if parsed is not None:
            raw_headlines.append(parsed)

    if not raw_headlines:
        return []

    scored = score_headlines(ticker.upper(), raw_headlines)
    return scored[:capped_limit]
