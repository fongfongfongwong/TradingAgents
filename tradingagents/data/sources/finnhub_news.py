"""Finnhub news source for the TickerBriefing materializer.

Fetches company news from Finnhub for the 7 days ending on ``as_of_date``,
derives structured ``event_flags`` via regex classification, and computes
an aggregate sentiment score.

All functions are safe to call without a ``FINNHUB_API_KEY``: in that case
(or on any connector error), a ``FinnhubNewsResult`` with ``fetched_ok=False``
and an informative ``error`` message is returned so the caller can fall back
to another data source.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinnhubNewsResult:
    """Immutable result of a Finnhub news fetch + event classification."""

    headlines: list[str] = field(default_factory=list)
    sentiment_avg: float = 0.0
    event_flags: list[str] = field(default_factory=list)
    fetched_ok: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Event flag regex patterns (module-level, compiled once)
# ---------------------------------------------------------------------------


_EVENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "upgrade",
        re.compile(r"\b(upgrade[ds]?|raised?\s+(rating|target|pt))\b", re.IGNORECASE),
    ),
    (
        "downgrade",
        re.compile(
            r"\b(downgrade[ds]?|cut\s+(rating|target|pt)|lowered\s+target)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "earnings_beat",
        re.compile(
            r"\b(beat(s|en)?(\s+\S+){0,3}\s+(estimate|expectation|forecast)s?|"
            r"tops?\s+(\S+\s+){0,2}estimate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "earnings_miss",
        re.compile(
            r"\b(miss(es|ed)?(\s+\S+){0,3}\s+(estimate|expectation|forecast)s?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "guidance_raise",
        re.compile(
            r"\b(raise[sd]?\s+guidance|guidance\s+rais|upgraded\s+outlook)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "guidance_cut",
        re.compile(
            r"\b(cut[s]?\s+guidance|lowered\s+guidance|guidance\s+cut)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "m&a",
        re.compile(
            r"\b(acquire[sd]?|acquisition|merger|merges?|buyout|takeover)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "lawsuit",
        re.compile(r"\b(lawsuit|sued?|class\s+action|settlement)\b", re.IGNORECASE),
    ),
    (
        "recall",
        re.compile(r"\b(recall[s]?|faulty)\b", re.IGNORECASE),
    ),
    (
        "insider_buy",
        re.compile(
            r"\b(insider\s+(buy|purchase)|bought\s+shares)\b",
            re.IGNORECASE,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Keyword sentiment tables (fallback when Finnhub sentiment API unavailable)
# ---------------------------------------------------------------------------


_BULLISH_PATTERN = re.compile(
    r"\b(upgrade[ds]?|beat[s]?|raise[sd]?|surge[sd]?|rally|rallies|bullish|"
    r"outperform[s]?|record\s+high|strong\s+growth|tops\s+estimate|raises\s+guidance)\b",
    re.IGNORECASE,
)

_BEARISH_PATTERN = re.compile(
    r"\b(downgrade[ds]?|miss(es|ed)?|cut[s]?|plunge[sd]?|crash(es|ed)?|bearish|"
    r"underperform[s]?|recall[s]?|lawsuit|sued?|lowered\s+guidance|cuts\s+guidance)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_event_flags(texts: Iterable[str]) -> list[str]:
    """Run event-flag regexes over each text and return a sorted, deduped list.

    Up to 10 flags are returned.
    """
    flags: set[str] = set()
    for text in texts:
        if not text:
            continue
        for flag_name, pattern in _EVENT_PATTERNS:
            if pattern.search(text):
                flags.add(flag_name)
    return sorted(flags)[:10]


def _score_sentiment_from_texts(texts: Iterable[str]) -> float:
    """Compute a sentiment score in [-1.0, 1.0] from a list of texts.

    Each bullish keyword match contributes +0.5, each bearish match -0.5.
    The per-text score is clamped to [-1, 1], then averaged across texts.
    """
    per_text_scores: list[float] = []
    for text in texts:
        if not text:
            continue
        bullish_hits = len(_BULLISH_PATTERN.findall(text))
        bearish_hits = len(_BEARISH_PATTERN.findall(text))
        raw = 0.5 * bullish_hits - 0.5 * bearish_hits
        clamped = max(-1.0, min(1.0, raw))
        per_text_scores.append(clamped)

    if not per_text_scores:
        return 0.0
    return sum(per_text_scores) / len(per_text_scores)


def _parse_as_of_date(as_of_date: str) -> datetime:
    """Parse an ISO ``YYYY-MM-DD`` date string into a datetime.

    Falls back to today's UTC date on parse error (never raises).
    """
    try:
        return datetime.strptime(as_of_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.utcnow()


def _normalize_finnhub_sentiment(company_news_score: float | None) -> float | None:
    """Map Finnhub's ``companyNewsScore`` (in [0, 1]) into [-1, 1].

    Returns ``None`` if the input is ``None`` or cannot be coerced to float.
    """
    if company_news_score is None:
        return None
    try:
        value = float(company_news_score)
    except (TypeError, ValueError):
        return None
    # Finnhub returns 0..1 with 0.5 ~ neutral.
    normalized = (value - 0.5) * 2.0
    return max(-1.0, min(1.0, normalized))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_finnhub_news(ticker: str, as_of_date: str) -> FinnhubNewsResult:
    """Fetch news + compute event flags from Finnhub for the 7 days ending
    at ``as_of_date``.

    If ``FINNHUB_API_KEY`` is missing or any connector error occurs, returns a
    ``FinnhubNewsResult`` with ``fetched_ok=False`` and the reason in ``error``.
    The materializer is expected to fall back to another source in that case.
    """
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return FinnhubNewsResult(
            headlines=[],
            sentiment_avg=0.0,
            event_flags=[],
            fetched_ok=False,
            error="FINNHUB_API_KEY not set",
        )

    try:
        # Imported lazily so that importing this module does not require the
        # connectors package (and its HTTP dependencies) at import time.
        from tradingagents.dataflows.connectors.finnhub_connector import (
            FinnhubConnector,
        )
    except Exception as exc:  # pragma: no cover - import-time failures
        return FinnhubNewsResult(
            fetched_ok=False,
            error=f"finnhub connector import failed: {exc}",
        )

    end_dt = _parse_as_of_date(as_of_date)
    start_dt = end_dt - timedelta(days=7)

    connector = FinnhubConnector(api_key=api_key)
    try:
        connector.connect()
    except Exception as exc:
        return FinnhubNewsResult(fetched_ok=False, error=f"connect failed: {exc}")

    try:
        # Use the connector's private _get helper directly so we can pin the
        # date window to ``as_of_date`` (the public fetch uses "now" as end).
        company_news = connector._get(  # noqa: SLF001  (internal helper by design)
            "/company-news",
            {
                "symbol": ticker,
                "from": start_dt.strftime("%Y-%m-%d"),
                "to": end_dt.strftime("%Y-%m-%d"),
            },
        )
    except Exception as exc:
        return FinnhubNewsResult(
            fetched_ok=False,
            error=f"company-news fetch failed: {exc}",
        )

    if not isinstance(company_news, list):
        return FinnhubNewsResult(
            fetched_ok=False,
            error="unexpected company-news payload (not a list)",
        )

    # Sort most-recent-first by datetime field (seconds since epoch).
    try:
        company_news_sorted = sorted(
            company_news,
            key=lambda it: it.get("datetime", 0) if isinstance(it, dict) else 0,
            reverse=True,
        )
    except Exception:
        company_news_sorted = list(company_news)

    headlines: list[str] = []
    classify_texts: list[str] = []
    for item in company_news_sorted:
        if not isinstance(item, dict):
            continue
        headline = (item.get("headline") or "").strip()
        summary = (item.get("summary") or "").strip()
        if headline:
            if len(headlines) < 5:
                headlines.append(headline)
            classify_texts.append(f"{headline}\n{summary}")

    event_flags = _derive_event_flags(classify_texts)

    # Try Finnhub's dedicated sentiment endpoint first; fall back to keyword
    # scoring on the headline+summary corpus.
    sentiment_avg: float | None = None
    try:
        sentiment_payload = connector._get(  # noqa: SLF001
            "/news-sentiment", {"symbol": ticker}
        )
        if isinstance(sentiment_payload, dict):
            sentiment_avg = _normalize_finnhub_sentiment(
                sentiment_payload.get("companyNewsScore")
            )
    except Exception as exc:
        logger.debug("Finnhub news-sentiment endpoint failed: %s", exc)

    if sentiment_avg is None:
        sentiment_avg = _score_sentiment_from_texts(classify_texts)

    # Be a good citizen: close the HTTP session.
    try:
        connector.disconnect()
    except Exception:
        pass

    return FinnhubNewsResult(
        headlines=headlines,
        sentiment_avg=round(float(sentiment_avg), 4),
        event_flags=event_flags,
        fetched_ok=True,
        error=None,
    )
