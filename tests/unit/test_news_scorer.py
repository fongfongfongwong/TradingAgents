"""Unit and integration tests for the v3 news scorer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from tradingagents.api.main import create_app
from tradingagents.data.sources.news_scorer import (
    HALF_LIFE_HOURS,
    RawHeadline,
    _TAG_DEFINITIONS,
    score_headlines,
)

NOW = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)


def _mk(title: str, *, source: str | None = None, hours_ago: float | None = 0.0) -> RawHeadline:
    published = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return RawHeadline(title=title, source=source, published_at=published)


# ---------------------------------------------------------------------------
# Tag pattern coverage (requirement 1)
# ---------------------------------------------------------------------------

_TAG_SAMPLE_TITLES: dict[str, str] = {
    "upgrade": "Analyst upgrades AAPL to Buy and raises price target",
    "downgrade": "Morgan Stanley downgrades AAPL and cuts price target",
    "earnings_beat": "AAPL beats estimates in Q3 earnings report",
    "earnings_miss": "AAPL misses estimates, shares slide",
    "guidance_raise": "AAPL raises guidance for next quarter",
    "guidance_cut": "AAPL cuts guidance amid weak demand",
    "m&a_target": "AAPL to be acquired by mystery buyer",
    "m&a_acquirer": "AAPL agrees to buy startup for $1B",
    "lawsuit": "AAPL faces class action lawsuit over product",
    "sec_investigation": "AAPL disclosed SEC probe into accounting",
    "recall": "AAPL issues product recall for faulty chargers",
    "buyback": "AAPL authorized repurchase of $90B in shares buyback",
    "dividend_raise": "AAPL announces dividend hike of 10%",
    "dividend_cut": "AAPL suspends dividend amid cash crunch",
    "insider_buy": "AAPL director bought shares this week",
    "insider_sell": "AAPL CFO files to sell shares",
    "ceo_departure": "AAPL CEO resigns after board clash",
    "ceo_appointment": "AAPL names new CEO to lead turnaround",
    "stock_gains": "AAPL surges on strong earnings momentum",
    "stock_drops": "AAPL drops sharply after trade war fears",
    "strong_demand": "AAPL reports strong demand for new iPhone",
    "weak_demand": "AAPL sees weak demand in China market",
    "price_target_raise": "Goldman raises target on AAPL to $250",
    "price_target_cut": "Citi cuts target on AAPL to $150",
    "growth": "AAPL revenue growth accelerates in Q4",
    "decline": "AAPL revenue decline worries investors",
    "on_track": "AAPL remains on track for record quarter",
    "delay": "AAPL product launch delayed due to supply issues",
    "partnership": "AAPL strategic alliance with major bank",
    "contract_win": "AAPL wins contract with Pentagon",
    "fda_approval": "AAPL drug wins FDA approval",
    "fda_rejection": "AAPL drug receives complete response letter from FDA",
}


@pytest.mark.parametrize("tag_def", _TAG_DEFINITIONS, ids=lambda td: td.tag)
def test_each_tag_pattern_matches(tag_def: Any) -> None:
    title = _TAG_SAMPLE_TITLES[tag_def.tag]
    result = score_headlines("AAPL", [_mk(title)], now=NOW)
    assert len(result) == 1
    assert tag_def.tag in result[0].tags, (
        f"{tag_def.tag} failed to match its sample title: {title!r}"
    )


def test_tag_pattern_does_not_match_unrelated_text() -> None:
    # A neutral "weather is nice" title should produce zero tags.
    result = score_headlines("AAPL", [_mk("AAPL has a quiet trading day")], now=NOW)
    assert result[0].tags == []


# ---------------------------------------------------------------------------
# Dedupe (requirement 2)
# ---------------------------------------------------------------------------


def test_dedupe_same_tag_only_once() -> None:
    title = "AAPL beats estimates and tops estimates again"
    result = score_headlines("AAPL", [_mk(title)], now=NOW)
    assert result[0].tags.count("earnings_beat") == 1


# ---------------------------------------------------------------------------
# Relevance (requirements 3, 4)
# ---------------------------------------------------------------------------


def test_relevance_floor_when_no_ticker_and_no_tags() -> None:
    result = score_headlines(
        "AAPL", [_mk("General market commentary for today")], now=NOW
    )
    assert result[0].relevance == pytest.approx(0.1)


def test_relevance_with_ticker_two_tags_and_quality_source() -> None:
    headline = _mk(
        "AAPL beats estimates and raises guidance",
        source="Bloomberg",
        hours_ago=0,
    )
    result = score_headlines("AAPL", [headline], now=NOW)
    # 0.6 (ticker) + 0.3 (2 tags * 0.15) + 0.1 (quality source) = 1.0 (clamped)
    assert result[0].relevance == pytest.approx(1.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Direction aggregation + confidence cap (requirements 5, 6)
# ---------------------------------------------------------------------------


def test_direction_long_with_offsetting_insider_sell() -> None:
    headline = _mk("AAPL upgraded while insider sells shares")
    result = score_headlines("AAPL", [headline], now=NOW)
    assert "upgrade" in result[0].tags
    assert "insider_sell" in result[0].tags
    assert result[0].direction == "LONG"
    assert result[0].confidence == pytest.approx(0.55, abs=1e-4)


def test_confidence_capped_at_one() -> None:
    # Stacked positive catalysts: upgrade (0.7) + earnings_beat (0.8) + guidance_raise (0.75) + fda_approval (0.7) = 2.95
    title = (
        "AAPL upgrade: beats estimates, raises guidance, wins FDA approval"
    )
    result = score_headlines("AAPL", [_mk(title)], now=NOW)
    assert result[0].direction == "LONG"
    assert result[0].confidence == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Recency decay (requirement 7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hours_ago,expected",
    [
        (0.0, 1.0),
        (HALF_LIFE_HOURS, 0.5),
        (HALF_LIFE_HOURS * 2, 0.25),
        (None, 0.6),
    ],
)
def test_recency_decay(hours_ago: float | None, expected: float) -> None:
    headline = _mk("AAPL upgrade", hours_ago=hours_ago)
    result = score_headlines("AAPL", [headline], now=NOW)
    # impact = relevance * confidence * 1.0 * decay
    # relevance = 0.6 (ticker) + 0.15 (1 tag) = 0.75
    # confidence = 0.70
    rel = 0.75
    conf = 0.70
    assert result[0].impact_score == pytest.approx(
        round(rel * conf * expected, 4), abs=1e-3
    )


# ---------------------------------------------------------------------------
# Impact ordering (requirement 8)
# ---------------------------------------------------------------------------


def test_impact_score_ordering() -> None:
    headlines = [
        _mk("AAPL beats estimates and raises guidance", source="Bloomberg", hours_ago=0),  # strongest
        _mk("AAPL upgrade", hours_ago=1),
        _mk("AAPL insider sells shares", hours_ago=2),
        _mk("Market summary for today", hours_ago=1),  # no ticker, no tag
        _mk("AAPL class action lawsuit filed", hours_ago=48),  # very old
    ]
    result = score_headlines("AAPL", headlines, now=NOW)
    scores = [r.impact_score for r in result]
    assert scores == sorted(scores, reverse=True)
    assert result[0].title.startswith("AAPL beats estimates")


# ---------------------------------------------------------------------------
# Rationale coverage (requirement 9)
# ---------------------------------------------------------------------------


def test_rationale_nonempty_and_bounded() -> None:
    headlines = [
        _mk("AAPL upgrade and earnings beat", hours_ago=0),  # multi-tag LONG
        _mk("AAPL upgrade", hours_ago=0),  # single positive LONG
        _mk("AAPL downgrade", hours_ago=0),  # single negative SHORT
        _mk("AAPL names new CEO", hours_ago=0),  # neutral with tag
        _mk("AAPL quiet session", hours_ago=0),  # neutral no tag low relevance
        _mk(
            "AAPL ticker makes headlines in broad market report",
            source="Bloomberg",
            hours_ago=0,
        ),  # neutral no tag high relevance
    ]
    result = score_headlines("AAPL", headlines, now=NOW)
    for item in result:
        assert item.rationale
        assert len(item.rationale) <= 120
        # Single sentence — at most one period, and not a multi-sentence block.
        assert item.rationale.count(". ") == 0


# ---------------------------------------------------------------------------
# Empty input (requirement 10)
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_list() -> None:
    assert score_headlines("AAPL", [], now=NOW) == []


# ---------------------------------------------------------------------------
# Negation handling (P0-8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headline,expected_tags,expected_direction",
    [
        # Canonical positive phrase stays unchanged.
        ("AAPL beats estimates in Q3 earnings report", ["earnings_beat"], "LONG"),
        # "fails to beat" inverts earnings_beat -> earnings_miss.
        ("AAPL fails to beat estimates in Q3", ["earnings_miss"], "SHORT"),
        # "unable to raise guidance" inverts guidance_raise -> guidance_cut.
        ("Company unable to raise guidance", ["guidance_cut"], "SHORT"),
        # Double negation: "did not miss" -> earnings_beat (bullish).
        ("Company did not miss estimates this quarter", ["earnings_beat"], "LONG"),
        # Canonical upgrade stays LONG.
        ("UBS upgrades AAPL to Buy", ["upgrade"], "LONG"),
        # Non-negation phrases must not affect tags.
        ("Lawsuit dismissed by court", ["lawsuit"], "SHORT"),
        # FDA approval canonical.
        ("Drug wins FDA approval today", ["fda_approval"], "LONG"),
        # "fails to win FDA approval" inverts fda_approval -> fda_rejection.
        ("Drug fails to win FDA approval", ["fda_rejection"], "SHORT"),
        # Negation of an inverse-less tag (contract_win) drops the tag entirely.
        ("Company fails to win contract with Pentagon", [], "NEUTRAL"),
        # Negation of buyback (no inverse) drops the tag entirely.
        ("Board unable to authorize repurchase program", [], "NEUTRAL"),
    ],
)
def test_negation_handling(
    headline: str, expected_tags: list[str], expected_direction: str
) -> None:
    result = score_headlines("AAPL", [_mk(headline)], now=NOW)
    assert len(result) == 1
    assert sorted(result[0].tags) == sorted(expected_tags)
    assert result[0].direction == expected_direction


def test_negation_preserves_positive_canonical_phrases() -> None:
    """Ensure the 22 canonical positive phrases are not affected by negation logic."""
    for tag, title in _TAG_SAMPLE_TITLES.items():
        result = score_headlines("AAPL", [_mk(title)], now=NOW)
        assert tag in result[0].tags, (
            f"Canonical title for {tag!r} regressed: {title!r} -> {result[0].tags}"
        )


# ---------------------------------------------------------------------------
# Endpoint integration (requirement 11)
# ---------------------------------------------------------------------------


def _fake_yfinance_payload() -> list[dict[str, Any]]:
    pub_ts = int((NOW - timedelta(hours=1)).timestamp())
    return [
        {
            "content": {
                "title": "AAPL beats estimates and raises guidance",
                "provider": {"displayName": "Bloomberg"},
                "canonicalUrl": {"url": "https://example.com/a"},
                "pubDate": (NOW - timedelta(hours=1)).isoformat(),
                "summary": "Strong quarter",
            },
            "providerPublishTime": pub_ts,
        },
        {
            "content": {
                "title": "AAPL downgraded by major bank",
                "provider": {"displayName": "Reuters"},
                "canonicalUrl": {"url": "https://example.com/b"},
                "pubDate": (NOW - timedelta(hours=3)).isoformat(),
            },
        },
        {
            "content": {
                "title": "AAPL wins contract with Pentagon",
                "provider": {"displayName": "WSJ"},
                "canonicalUrl": {"url": "https://example.com/c"},
                "pubDate": (NOW - timedelta(hours=6)).isoformat(),
            },
        },
    ]


def test_scored_news_endpoint_integration() -> None:
    app = create_app()

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.get("/api/v3/news/AAPL/scored?limit=5")

    with patch(
        "tradingagents.api.routes.news_v3._fetch_yfinance_news",
        return_value=_fake_yfinance_payload(),
    ):
        response = asyncio.run(_run())

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 3
    required_keys = {
        "title",
        "source",
        "url",
        "published_at",
        "relevance",
        "direction",
        "confidence",
        "impact_score",
        "tags",
        "rationale",
    }
    for item in payload:
        assert required_keys.issubset(item.keys())
        assert 0.0 <= item["relevance"] <= 1.0
        assert 0.0 <= item["confidence"] <= 1.0
        assert 0.0 <= item["impact_score"] <= 1.0
        assert item["direction"] in {"LONG", "SHORT", "NEUTRAL"}
        assert item["rationale"]
    # Sorted DESC by impact_score
    impacts = [item["impact_score"] for item in payload]
    assert impacts == sorted(impacts, reverse=True)


def test_scored_news_endpoint_empty_on_upstream_failure() -> None:
    app = create_app()

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.get("/api/v3/news/FAKE/scored?limit=5")

    with patch(
        "tradingagents.api.routes.news_v3._fetch_yfinance_news",
        return_value=[],
    ):
        response = asyncio.run(_run())

    assert response.status_code == 200
    assert response.json() == []
