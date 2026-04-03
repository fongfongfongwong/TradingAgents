"""Retail sentiment divergence dimension.

Measures retail investor sentiment from social media mentions,
Fear & Greed index, and AAII bull-bear spread.  Weakest signal
in the divergence engine (weight 0.05), so designed to degrade
gracefully when data is missing.
"""

from __future__ import annotations

from typing import Any


class RetailDimension:
    """Retail-sentiment divergence calculator.

    Parameters
    ----------
    social_weight : float
        Weight for ApeWisdom / social-mentions component (default 0.35).
    fear_greed_weight : float
        Weight for Fear & Greed index component (default 0.35).
    aaii_weight : float
        Weight for AAII bull-bear spread component (default 0.30).
    """

    DIMENSION = "retail"

    def __init__(
        self,
        social_weight: float = 0.35,
        fear_greed_weight: float = 0.35,
        aaii_weight: float = 0.30,
    ) -> None:
        self.social_weight = social_weight
        self.fear_greed_weight = fear_greed_weight
        self.aaii_weight = aaii_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        ticker: str,
        social_data: dict[str, Any] | None = None,
        fear_greed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the retail divergence score.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol.
        social_data : dict | None
            ApeWisdom-style data with keys:
            ``mentions`` (int), ``mentions_24h_ago`` (int for trend),
            ``rank`` (optional), ``upvotes`` (optional).
        fear_greed : dict | None
            Fear & Greed data with keys:
            ``value`` (0-100), ``aaii_bull_bear_spread`` (optional,
            already in percentage points, e.g. +15 means 15% more
            bulls than bears).

        Returns
        -------
        dict
            ``{"value", "confidence", "sources", "raw_data"}``
        """
        social_score = self._social_score(social_data)
        fg_score = self._fear_greed_score(fear_greed)
        aaii_score = self._aaii_score(fear_greed)

        scores: list[tuple[float, float]] = []  # (score, weight)
        sources: list[str] = []
        raw: dict[str, Any] = {}

        if social_score is not None:
            scores.append((social_score, self.social_weight))
            sources.append("social_mentions")
            raw["social_score"] = social_score
        if fg_score is not None:
            scores.append((fg_score, self.fear_greed_weight))
            sources.append("fear_greed_index")
            raw["fear_greed_score"] = fg_score
        if aaii_score is not None:
            scores.append((aaii_score, self.aaii_weight))
            sources.append("aaii_survey")
            raw["aaii_score"] = aaii_score

        if scores:
            total_w = sum(w for _, w in scores)
            value = sum(s * w for s, w in scores) / total_w
            # Confidence scales with number of available signals
            confidence = min(0.3 + 0.2 * len(scores), 0.8)
        else:
            value = 0.0
            confidence = 0.0

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
    def _social_score(data: dict[str, Any] | None) -> float | None:
        """Score social mentions with trend direction.

        High mentions + increasing trend -> bullish sentiment.
        High mentions + decreasing trend -> bearish (hype fading).
        Low mentions -> near zero (no retail signal).
        """
        if data is None:
            return None

        mentions = data.get("mentions")
        if mentions is None:
            return None

        prev_mentions = data.get("mentions_24h_ago", mentions)

        # Trend: positive means growing mentions
        if prev_mentions > 0:
            trend = (mentions - prev_mentions) / max(prev_mentions, 1)
        else:
            trend = 1.0 if mentions > 0 else 0.0

        # Volume factor: more mentions -> stronger signal
        # Normalize: 100 mentions = moderate, 500+ = high
        volume_factor = min(mentions / 500.0, 1.0)

        # Direction from trend, magnitude from volume
        if trend > 0:
            score = volume_factor * min(trend, 1.0)
        elif trend < 0:
            score = -volume_factor * min(abs(trend), 1.0)
        else:
            # Flat trend with mentions -> weakly bullish (retail is present)
            score = volume_factor * 0.2

        return max(-1.0, min(1.0, score))

    @staticmethod
    def _fear_greed_score(data: dict[str, Any] | None) -> float | None:
        """Contrarian interpretation of Fear & Greed index (0-100).

        > 75 -> extreme greed -> contrarian bearish
        < 25 -> extreme fear  -> contrarian bullish
        50   -> neutral

        Score = (50 - value) / 50, clamped to [-1, +1].
        """
        if data is None:
            return None

        value = data.get("value")
        if value is None:
            return None

        score = (50.0 - value) / 50.0
        return max(-1.0, min(1.0, score))

    @staticmethod
    def _aaii_score(data: dict[str, Any] | None) -> float | None:
        """Normalize AAII bull-bear spread to [-1, +1].

        The spread is typically in [-40, +40] percentage points.
        We normalize by dividing by 40 and clamping.
        """
        if data is None:
            return None

        spread = data.get("aaii_bull_bear_spread")
        if spread is None:
            return None

        score = spread / 40.0
        return max(-1.0, min(1.0, score))
