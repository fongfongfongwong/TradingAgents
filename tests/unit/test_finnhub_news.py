"""Unit tests for the Finnhub news source and materializer integration."""

from __future__ import annotations

import pytest

from tradingagents.data.sources import finnhub_news as finnhub_news_source
from tradingagents.data.sources.finnhub_news import (
    FinnhubNewsResult,
    _derive_event_flags,
    _score_sentiment_from_texts,
    fetch_finnhub_news,
)


# ---------------------------------------------------------------------------
# fetch_finnhub_news: missing API key
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_finnhub_news_returns_error_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    result = fetch_finnhub_news("AAPL", "2026-04-05")

    assert isinstance(result, FinnhubNewsResult)
    assert result.fetched_ok is False
    assert result.error == "FINNHUB_API_KEY not set"
    assert result.headlines == []
    assert result.sentiment_avg == 0.0
    assert result.event_flags == []


# ---------------------------------------------------------------------------
# Event flag regex derivation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_derive_event_flags_from_mixed_headlines():
    texts = [
        "UBS upgrades AAPL to Buy, raises target to 250",
        "Company beats Q3 estimates, raises guidance",
        "SEC lawsuit filed against TSLA",
    ]

    flags = _derive_event_flags(texts)

    assert "upgrade" in flags
    assert "earnings_beat" in flags
    assert "guidance_raise" in flags
    assert "lawsuit" in flags
    # sorted + deduped
    assert flags == sorted(flags)
    assert len(flags) == len(set(flags))


@pytest.mark.unit
def test_derive_event_flags_dedupes_across_headlines():
    texts = [
        "Analyst upgrades AAPL",
        "Second firm upgrades AAPL as well",
        "Third bank upgrades rating on AAPL",
    ]
    flags = _derive_event_flags(texts)
    assert flags == ["upgrade"]


@pytest.mark.unit
def test_derive_event_flags_caps_at_ten():
    # Craft a text that matches all 10 supported flags at once.
    text = (
        "Analyst upgrades rating and downgrades peer; company beats estimates "
        "but another misses estimates; CEO raises guidance while rival cuts "
        "guidance; announces acquisition and merger; lawsuit filed over recall "
        "of faulty product; insider purchase reported."
    )
    flags = _derive_event_flags([text])
    assert len(flags) <= 10
    assert len(flags) >= 8  # sanity: we expect most to hit


# ---------------------------------------------------------------------------
# Sentiment keyword scoring
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sentiment_all_bullish_is_positive():
    texts = [
        "Stock surges after upgrade and strong growth",
        "Company beats estimates and raises guidance",
    ]
    score = _score_sentiment_from_texts(texts)
    assert score > 0.0
    assert -1.0 <= score <= 1.0


@pytest.mark.unit
def test_sentiment_all_bearish_is_negative():
    texts = [
        "Analyst downgrade after company misses estimates",
        "Shares plunge on lowered guidance and lawsuit",
    ]
    score = _score_sentiment_from_texts(texts)
    assert score < 0.0
    assert -1.0 <= score <= 1.0


@pytest.mark.unit
def test_sentiment_empty_is_zero():
    assert _score_sentiment_from_texts([]) == 0.0
    assert _score_sentiment_from_texts(["neutral factual statement"]) == 0.0


# ---------------------------------------------------------------------------
# Materializer integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_materializer_falls_back_when_finnhub_key_missing(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    from tradingagents.data import materializer as materializer_mod

    # Stub out the yfinance-dependent sub-builders we don't care about here,
    # so the test is fast and offline.
    class _FakeTicker:
        news = [{"title": "Fake headline for fallback test"}]
        options = ()
        calendar = None

        def history(self, period="1y"):  # noqa: ARG002
            import pandas as pd

            return pd.DataFrame()

    monkeypatch.setattr(materializer_mod.yf, "Ticker", lambda _t: _FakeTicker())

    data_gaps: list[str] = []
    news_ctx = materializer_mod._build_news_context(
        _FakeTicker(), "AAPL", "2026-04-05", data_gaps
    )

    # Fallback was used → data_gaps must contain the finnhub_fallback marker
    assert any(g.startswith("news:finnhub_fallback:") for g in data_gaps), data_gaps
    # yfinance fallback returns the stubbed headline
    assert news_ctx.top_headlines == ["Fake headline for fallback test"]
    # event_flags is still empty (yfinance doesn't classify)
    assert news_ctx.event_flags == []


@pytest.mark.unit
def test_materializer_uses_finnhub_event_flags_on_success(monkeypatch):
    from tradingagents.data import materializer as materializer_mod

    def _fake_fetch(ticker: str, as_of_date: str) -> FinnhubNewsResult:
        return FinnhubNewsResult(
            headlines=[
                "UBS upgrades AAPL to Buy, raises target to 250",
                "Apple beats Q3 estimates, raises guidance",
            ],
            sentiment_avg=0.75,
            event_flags=["earnings_beat", "guidance_raise", "upgrade"],
            fetched_ok=True,
            error=None,
        )

    monkeypatch.setattr(finnhub_news_source, "fetch_finnhub_news", _fake_fetch)

    class _FakeTicker:
        news = []
        options = ()
        calendar = None

        def history(self, period="1y"):  # noqa: ARG002
            import pandas as pd

            return pd.DataFrame()

    data_gaps: list[str] = []
    news_ctx = materializer_mod._build_news_context(
        _FakeTicker(), "AAPL", "2026-04-05", data_gaps
    )

    assert news_ctx.event_flags == ["earnings_beat", "guidance_raise", "upgrade"]
    assert news_ctx.top_headlines == [
        "UBS upgrades AAPL to Buy, raises target to 250",
        "Apple beats Q3 estimates, raises guidance",
    ]
    assert news_ctx.headline_sentiment_avg == pytest.approx(0.75, rel=1e-3)
    # No fallback marker because finnhub succeeded.
    assert not any(g.startswith("news:finnhub_fallback") for g in data_gaps)
