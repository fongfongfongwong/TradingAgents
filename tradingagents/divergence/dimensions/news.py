"""News sentiment divergence dimension.

Measures divergence in news sentiment using Finnhub-style data:
bullish/bearish percentages and a company-level news score.
"""

from __future__ import annotations

from typing import Any


class NewsDimension:
    """News-sentiment divergence calculator.

    Parameters
    ----------
    sentiment_weight : float
        Weight for the bull-bear spread component (default 0.7).
    news_score_weight : float
        Weight for the company news score component (default 0.3).
    """

    DIMENSION = "news"

    def __init__(
        self,
        sentiment_weight: float = 0.7,
        news_score_weight: float = 0.3,
    ) -> None:
        self.sentiment_weight = sentiment_weight
        self.news_score_weight = news_score_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        ticker: str,
        sentiment_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the news divergence score.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol.
        sentiment_data : dict | None
            Finnhub-style sentiment data with keys:
            ``bullish_percent``, ``bearish_percent``,
            ``company_news_score`` (optional, in [-1, +1]),
            ``articles_in_last_week`` (for confidence scaling).

        Returns
        -------
        dict
            ``{"value", "confidence", "sources", "raw_data"}``
        """
        spread_score = self._sentiment_spread(sentiment_data)
        news_score = self._company_news_score(sentiment_data)

        sources: list[str] = []
        raw: dict[str, Any] = {}

        have_spread = spread_score is not None
        have_news = news_score is not None

        if have_spread:
            sources.append("news_sentiment")
            raw["sentiment_spread"] = spread_score
        if have_news:
            sources.append("company_news_score")
            raw["company_news_score"] = news_score

        if have_spread and have_news:
            total_w = self.sentiment_weight + self.news_score_weight
            value = (
                self.sentiment_weight * spread_score
                + self.news_score_weight * news_score
            ) / total_w
            base_confidence = 0.7
        elif have_spread:
            value = spread_score
            base_confidence = 0.5
        elif have_news:
            value = news_score
            base_confidence = 0.4
        else:
            value = 0.0
            base_confidence = 0.0

        # Scale confidence by article count
        confidence = self._article_confidence(sentiment_data, base_confidence)

        value = max(-1.0, min(1.0, value))

        return {
            "value": round(value, 6),
            "confidence": round(confidence, 4),
            "sources": sources,
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _sentiment_spread(data: dict[str, Any] | None) -> float | None:
        """Compute bullish - bearish spread, normalised to [-1, +1].

        Expects percentages in [0, 1] range (e.g., 0.65 = 65%).
        """
        if data is None:
            return None

        bull = data.get("bullish_percent")
        bear = data.get("bearish_percent")

        if bull is None or bear is None:
            return None

        spread = bull - bear
        return max(-1.0, min(1.0, spread))

    @staticmethod
    def _company_news_score(data: dict[str, Any] | None) -> float | None:
        """Extract pre-computed company news score in [-1, +1]."""
        if data is None:
            return None

        score = data.get("company_news_score")
        if score is None:
            return None

        return max(-1.0, min(1.0, float(score)))

    @staticmethod
    def _article_confidence(
        data: dict[str, Any] | None,
        base_confidence: float,
    ) -> float:
        """Scale confidence by article volume.

        More articles in the last week -> higher confidence.
        0 articles -> confidence halved; 20+ articles -> full base confidence.
        """
        if data is None:
            return base_confidence

        articles = data.get("articles_in_last_week")
        if articles is None:
            return base_confidence

        # Scale factor: min(articles / 20, 1.0), floor at 0.5
        scale = max(0.5, min(1.0, articles / 20.0))
        return round(base_confidence * scale, 4)
