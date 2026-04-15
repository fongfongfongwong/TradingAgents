"""Unit tests for the social sentiment source and materializer integration.

Covers:

* Fear & Greed piecewise score mapping
* ApeWisdom mention-volume derivation
* Narrative derivation rules
* Graceful degradation when one or both upstreams fail
* Materializer integration populates a valid SocialContext
* Live smoke tests for AAPL and a made-up ticker (network-dependent, xfail
  cleanly if the network is unavailable)
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from tradingagents.data.sources import social_sentiment as social_source
from tradingagents.data.sources.social_sentiment import (
    SocialSentimentResult,
    _apewisdom_mention_volume,
    _ApeWisdomRow,
    _clear_cache,
    _derive_narratives,
    _fear_greed_to_score,
    fetch_social_sentiment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    """Requests-compatible session that serves canned JSON by URL substring."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: float | None = None, **_: Any) -> _FakeResponse:
        for key, payload in self.routes.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResponse(payload)
        raise AssertionError(f"Unexpected URL: {url}")

    def close(self) -> None:
        pass

    def update(self, *_: Any, **__: Any) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_cache():
    _clear_cache()
    yield
    _clear_cache()


# ---------------------------------------------------------------------------
# Fear & Greed score mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        (0, -1.0),
        (10, -1.0),
        (25, -1.0),
        (26, -0.5),
        (40, -0.5),
        (45, -0.5),
        (46, 0.0),
        (50, 0.0),
        (55, 0.0),
        (56, 0.5),
        (70, 0.5),
        (75, 0.5),
        (76, 1.0),
        (90, 1.0),
        (100, 1.0),
    ],
)
def test_fear_greed_score_piecewise(value: float, expected: float) -> None:
    assert _fear_greed_to_score(value) == expected


# ---------------------------------------------------------------------------
# ApeWisdom mention volume derivation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mention_volume_not_ranked_is_baseline() -> None:
    assert _apewisdom_mention_volume(None) == 1.0


@pytest.mark.unit
def test_mention_volume_top_rank_above_baseline() -> None:
    top = _apewisdom_mention_volume(1)
    bottom = _apewisdom_mention_volume(50)
    # Ranked tickers must be above the not-ranked baseline.
    assert top > 1.0
    assert bottom > 1.0
    # Higher rank-position (#1) must be louder than lower (#50).
    assert top > bottom


# ---------------------------------------------------------------------------
# Narrative derivation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_narrative_meme_momentum() -> None:
    narratives = _derive_narratives(
        fear_greed_value=50, rank=5, rank_24h_ago=10
    )
    assert "meme_momentum" in narratives


@pytest.mark.unit
def test_narrative_retail_surge() -> None:
    narratives = _derive_narratives(
        fear_greed_value=50, rank=5, rank_24h_ago=40
    )
    assert "retail_surge" in narratives


@pytest.mark.unit
def test_narrative_extreme_greed_environment() -> None:
    narratives = _derive_narratives(
        fear_greed_value=85, rank=None, rank_24h_ago=None
    )
    assert "extreme_greed_environment" in narratives


@pytest.mark.unit
def test_narrative_extreme_fear_environment() -> None:
    narratives = _derive_narratives(
        fear_greed_value=15, rank=None, rank_24h_ago=None
    )
    assert "extreme_fear_environment" in narratives


@pytest.mark.unit
def test_narrative_none_for_neutral_inputs() -> None:
    narratives = _derive_narratives(
        fear_greed_value=50, rank=None, rank_24h_ago=None
    )
    assert narratives == []


# ---------------------------------------------------------------------------
# fetch_social_sentiment with mocked HTTP
# ---------------------------------------------------------------------------


def _install_fake_session(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, Any]
) -> None:
    session = _FakeSession(routes)
    monkeypatch.setattr(
        social_source.requests, "Session", lambda: session
    )


@pytest.mark.unit
def test_fetch_maps_extreme_fear_to_negative_one(monkeypatch) -> None:
    _install_fake_session(
        monkeypatch,
        {
            "fearandgreed": {"fear_and_greed": {"score": 10}},
            "apewisdom": {"results": []},
        },
    )
    result = fetch_social_sentiment("AAPL")
    assert result.fetched_ok is True
    assert result.fear_greed_index == 10
    # combined = -1.0 * 0.4 + 0.0 * 0.6 = -0.4
    assert result.sentiment_score == pytest.approx(-0.4, abs=1e-6)
    assert "extreme_fear_environment" in result.trending_narratives


@pytest.mark.unit
def test_fetch_maps_extreme_greed_to_positive(monkeypatch) -> None:
    _install_fake_session(
        monkeypatch,
        {
            "fearandgreed": {"fear_and_greed": {"score": 90}},
            "apewisdom": {"results": []},
        },
    )
    result = fetch_social_sentiment("AAPL")
    assert result.fetched_ok is True
    assert result.fear_greed_index == 90
    assert result.sentiment_score == pytest.approx(0.4, abs=1e-6)
    assert "extreme_greed_environment" in result.trending_narratives


@pytest.mark.unit
def test_fetch_neutral_fear_greed_is_zero(monkeypatch) -> None:
    _install_fake_session(
        monkeypatch,
        {
            "fearandgreed": {"fear_and_greed": {"score": 50}},
            "apewisdom": {"results": []},
        },
    )
    result = fetch_social_sentiment("AAPL")
    assert result.fetched_ok is True
    assert result.sentiment_score == pytest.approx(0.0, abs=1e-6)
    assert result.trending_narratives == []


@pytest.mark.unit
def test_fetch_meme_ticker_ranked(monkeypatch) -> None:
    _install_fake_session(
        monkeypatch,
        {
            "fearandgreed": {"fear_and_greed": {"score": 60}},
            "apewisdom": {
                "results": [
                    {
                        "ticker": "GME",
                        "rank": 5,
                        "rank_24h_ago": 30,
                        "mentions": 500,
                    }
                ]
            },
        },
    )
    result = fetch_social_sentiment("GME")
    assert result.fetched_ok is True
    assert result.apewisdom_rank == 5
    assert result.apewisdom_mentions == 500
    assert result.mention_volume_vs_avg > 1.0
    assert "meme_momentum" in result.trending_narratives
    assert "retail_surge" in result.trending_narratives
    # Sentiment should be positive: greed (0.5*0.4=0.2) + bullish wsb (>0).
    assert result.sentiment_score > 0.2


@pytest.mark.unit
def test_fetch_clamps_to_unit_interval(monkeypatch) -> None:
    _install_fake_session(
        monkeypatch,
        {
            "fearandgreed": {"fear_and_greed": {"score": 95}},
            "apewisdom": {
                "results": [
                    {
                        "ticker": "TSLA",
                        "rank": 1,
                        "rank_24h_ago": 50,
                        "mentions": 9999,
                    }
                ]
            },
        },
    )
    result = fetch_social_sentiment("TSLA")
    assert -1.0 <= result.sentiment_score <= 1.0


@pytest.mark.unit
def test_fetch_total_failure_returns_neutral(monkeypatch) -> None:
    err = requests.ConnectionError("dns fail")
    _install_fake_session(
        monkeypatch,
        {
            "fearandgreed": err,
            "apewisdom": err,
        },
    )
    result = fetch_social_sentiment("AAPL")
    assert result.fetched_ok is False
    assert result.sentiment_score == 0.0
    assert result.mention_volume_vs_avg == 1.0
    assert result.error is not None


@pytest.mark.unit
def test_fetch_one_source_ok_still_counts(monkeypatch) -> None:
    _install_fake_session(
        monkeypatch,
        {
            "fearandgreed": {"fear_and_greed": {"score": 70}},
            "apewisdom": requests.ConnectionError("boom"),
        },
    )
    result = fetch_social_sentiment("ZZZZ")
    assert result.fetched_ok is True
    assert result.fear_greed_index == 70
    assert result.apewisdom_rank is None


@pytest.mark.unit
def test_fetch_caches_results(monkeypatch) -> None:
    calls = {"n": 0}

    class _CountingSession(_FakeSession):
        def get(self, url: str, timeout: float | None = None, **kw: Any):
            calls["n"] += 1
            return super().get(url, timeout=timeout, **kw)

    session = _CountingSession(
        {
            "fearandgreed": {"fear_and_greed": {"score": 50}},
            "apewisdom": {"results": []},
        }
    )
    monkeypatch.setattr(social_source.requests, "Session", lambda: session)

    _clear_cache()
    fetch_social_sentiment("AAPL")
    fetch_social_sentiment("AAPL")
    # Two endpoint calls the first time, none on the second (cached).
    assert calls["n"] == 2


@pytest.mark.unit
def test_invalid_ticker_returns_error() -> None:
    result = fetch_social_sentiment("")
    assert result.fetched_ok is False
    assert result.error == "invalid_ticker"


# ---------------------------------------------------------------------------
# Materializer integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_social_context_success(monkeypatch) -> None:
    from tradingagents.data import materializer

    def _fake(ticker: str) -> SocialSentimentResult:
        return SocialSentimentResult(
            mention_volume_vs_avg=1.8,
            sentiment_score=0.42,
            trending_narratives=["meme_momentum"],
            fear_greed_index=70,
            apewisdom_rank=3,
            apewisdom_mentions=500,
            fetched_ok=True,
            error=None,
        )

    monkeypatch.setattr(
        social_source, "fetch_social_sentiment", _fake
    )

    gaps: list[str] = []
    ctx = materializer._build_social_context("GME", gaps)

    assert ctx.mention_volume_vs_avg == pytest.approx(1.8)
    assert ctx.sentiment_score == pytest.approx(0.42)
    assert ctx.trending_narratives == ["meme_momentum"]
    assert ctx.data_age_seconds == 0
    assert gaps == []


@pytest.mark.unit
def test_build_social_context_failure_records_gap(monkeypatch) -> None:
    from tradingagents.data import materializer

    def _fake(ticker: str) -> SocialSentimentResult:
        return SocialSentimentResult(
            fetched_ok=False, error="fear_greed_http:boom; apewisdom_http:boom"
        )

    monkeypatch.setattr(
        social_source, "fetch_social_sentiment", _fake
    )

    gaps: list[str] = []
    ctx = materializer._build_social_context("AAPL", gaps)

    assert ctx.sentiment_score == 0.0
    assert ctx.mention_volume_vs_avg == 1.0
    assert ctx.trending_narratives == []
    assert ctx.data_age_seconds == 86400
    assert any(g.startswith("social:sentiment_fetch_failed:") for g in gaps)


@pytest.mark.unit
def test_build_social_context_unexpected_exception(monkeypatch) -> None:
    from tradingagents.data import materializer

    def _boom(ticker: str) -> SocialSentimentResult:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(social_source, "fetch_social_sentiment", _boom)

    gaps: list[str] = []
    ctx = materializer._build_social_context("AAPL", gaps)

    assert ctx.sentiment_score == 0.0
    assert ctx.data_age_seconds == 86400
    assert any(
        g.startswith("social:sentiment_fetch_failed:unexpected:") for g in gaps
    )


# ---------------------------------------------------------------------------
# Network smoke tests — xfail cleanly when offline
# ---------------------------------------------------------------------------


def _network_reachable() -> bool:
    try:
        requests.get("https://apewisdom.io/", timeout=5)
        return True
    except requests.RequestException:
        return False


@pytest.mark.unit
def test_live_fetch_aapl_smoke() -> None:
    if not _network_reachable():
        pytest.xfail("Network unavailable — skipping live Fear&Greed/ApeWisdom")
    _clear_cache()
    result = fetch_social_sentiment("AAPL")
    if not result.fetched_ok:
        pytest.xfail(f"Upstream unavailable: {result.error}")
    assert -1.0 <= result.sentiment_score <= 1.0
    assert result.mention_volume_vs_avg >= 1.0


@pytest.mark.unit
def test_live_fetch_unknown_ticker_still_gets_fear_greed() -> None:
    if not _network_reachable():
        pytest.xfail("Network unavailable — skipping live Fear&Greed/ApeWisdom")
    _clear_cache()
    result = fetch_social_sentiment("ZZZZZ999")
    if result.fear_greed_index is None:
        pytest.xfail("Fear & Greed unavailable")
    # ApeWisdom will not know this ticker, but Fear & Greed succeeded.
    assert result.fetched_ok is True
    assert result.apewisdom_rank is None
    assert -1.0 <= result.sentiment_score <= 1.0
