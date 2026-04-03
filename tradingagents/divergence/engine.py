"""Divergence Engine -- computes 5-dimension divergence vectors."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .schemas import (
    DIMENSIONS,
    DimensionScore,
    DivergenceVector,
    RegimeState,
)

logger = logging.getLogger(__name__)

# Literature-based default weights (institutional flow is strongest alpha).
DEFAULT_WEIGHTS: dict[str, float] = {
    "institutional": 0.35,
    "options": 0.25,
    "price_action": 0.20,
    "news": 0.15,
    "retail": 0.05,
}

# Expected source counts per dimension (for confidence calculation).
_EXPECTED_SOURCES: dict[str, int] = {
    "institutional": 3,
    "options": 2,
    "price_action": 3,
    "news": 2,
    "retail": 2,
}


class DivergenceEngine:
    """Core engine that fuses multi-source signals into a DivergenceVector."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        raw = weights or dict(DEFAULT_WEIGHTS)
        # Normalize so weights always sum to 1.
        total = sum(raw.values())
        if total == 0:
            raise ValueError("Weights must not all be zero")
        self.weights: dict[str, float] = {k: v / total for k, v in raw.items()}

    # -- public API -----------------------------------------------------------

    def compute(
        self,
        ticker: str,
        raw_signals: dict[str, dict],
        regime: RegimeState | None = None,
    ) -> DivergenceVector:
        """Compute a full DivergenceVector from raw signal dicts.

        Parameters
        ----------
        ticker:
            Equity ticker symbol.
        raw_signals:
            Mapping of dimension name -> arbitrary raw data dict.  Each dict
            should contain at least ``"value"`` (float) and optionally
            ``"sources"`` (list[str]).  Missing dimensions are gracefully
            handled with zero value and low confidence.
        regime:
            Market regime override.  If *None*, defaults to RISK_ON.
        """
        if regime is None:
            regime = RegimeState.RISK_ON

        dimensions: dict[str, DimensionScore] = {}
        for dim in DIMENSIONS:
            if dim in raw_signals and raw_signals[dim] is not None:
                raw = raw_signals[dim]
                value = self._normalize_score(raw.get("value", 0.0), dim)
                sources = raw.get("sources", [])
                confidence = self._compute_confidence(
                    len(sources), _EXPECTED_SOURCES.get(dim, 2)
                )
                dimensions[dim] = DimensionScore(
                    dimension=dim,
                    value=value,
                    confidence=confidence,
                    sources=sources,
                    raw_data=raw,
                )
            else:
                # Graceful degradation: missing dimension gets 0 score, 0 confidence.
                dimensions[dim] = DimensionScore(
                    dimension=dim,
                    value=0.0,
                    confidence=0.0,
                    sources=[],
                    raw_data={},
                )
                logger.debug("Dimension '%s' missing for %s -- using zero fill", dim, ticker)

        composite = self._compute_composite(dimensions, regime)

        return DivergenceVector(
            ticker=ticker,
            timestamp=datetime.now(timezone.utc),
            regime=regime,
            dimensions=dimensions,
            composite_score=composite,
            weights=dict(self.weights),
        )

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _normalize_score(raw_value: float, dimension: str) -> float:  # noqa: ARG004
        """Clamp *raw_value* to [-1, +1]."""
        return max(-1.0, min(1.0, float(raw_value)))

    def _compute_composite(
        self,
        dimensions: dict[str, DimensionScore],
        regime: RegimeState,
    ) -> float:
        """Weighted average with regime-aware sign adjustment.

        In RISK_OFF regime the composite sign is flipped to reflect
        contrarian interpretation per academic literature (retail bearishness
        and negative sentiment become bullish signals).
        """
        weighted_sum = 0.0
        weight_sum = 0.0
        for dim_name, score in dimensions.items():
            w = self.weights.get(dim_name, 0.0)
            # Weight by both the dimension weight and its confidence.
            effective_w = w * score.confidence
            weighted_sum += score.value * effective_w
            weight_sum += effective_w

        if weight_sum == 0.0:
            composite = 0.0
        else:
            composite = weighted_sum / weight_sum

        # Regime adjustment: flip sign under RISK_OFF for contrarian read.
        if regime == RegimeState.RISK_OFF:
            composite = -composite

        # Clamp to valid range.
        return max(-1.0, min(1.0, composite))

    @staticmethod
    def _compute_confidence(sources_available: int, total_sources: int) -> float:
        """Confidence = fraction of expected data sources present, capped at 1."""
        if total_sources <= 0:
            return 0.0
        return min(1.0, sources_available / total_sources)
