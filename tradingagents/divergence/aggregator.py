"""Divergence Aggregator -- top-level coordinator for multi-dimension divergence analysis.

Orchestrates all 5 dimension calculators, the regime detector, and produces
the final divergence result dict for a ticker.  This is the main entry point
that agents use.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .dimensions import (
    InstitutionalDimension,
    NewsDimension,
    OptionsDimension,
    PriceActionDimension,
    RetailDimension,
)
from .regime import RegimeDetector
from .schemas import DIMENSIONS, RegimeState

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS: dict[str, float] = {
    "institutional": 0.35,
    "options": 0.25,
    "price_action": 0.20,
    "news": 0.15,
    "retail": 0.05,
}

_REGIME_MULTIPLIERS: dict[RegimeState, float] = {
    RegimeState.RISK_ON: 1.0,
    RegimeState.RISK_OFF: -0.5,
    RegimeState.TRANSITIONING: 0.7,
}

class DivergenceAggregator:
    """Top-level aggregator that coordinates all divergence dimensions."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        use_connectors: bool = False,
    ) -> None:
        raw = weights or dict(DEFAULT_WEIGHTS)
        total = sum(raw.values())
        if total == 0:
            raise ValueError("Weights must not all be zero")
        self.weights: dict[str, float] = {k: v / total for k, v in raw.items()}
        self.use_connectors = use_connectors

        self._institutional = InstitutionalDimension()
        self._options = OptionsDimension()
        self._price_action = PriceActionDimension()
        self._news = NewsDimension()
        self._retail = RetailDimension()
        self._regime_detector = RegimeDetector()
    def compute(
        self,
        ticker: str,
        raw_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the full divergence analysis for a single ticker."""
        data = raw_data or {}

        if not data and self.use_connectors:
            data = self._fetch_from_connectors(ticker)

        regime = self._detect_regime(data.get("regime"))

        dim_results: dict[str, dict[str, Any]] = {}

        inst_data = data.get("institutional", {})
        dim_results["institutional"] = self._institutional.compute(
            ticker,
            analyst_data=inst_data.get("analyst"),
            insider_data=inst_data.get("insider"),
        )

        opt_data = data.get("options", {})
        dim_results["options"] = self._options.compute(
            ticker,
            put_call_data=opt_data.get("put_call"),
            vix_data=opt_data.get("vix"),
        )

        pa_data = data.get("price_action")
        dim_results["price_action"] = self._price_action.compute(
            ticker,
            price_data=pa_data,
        )

        news_data = data.get("news")
        dim_results["news"] = self._news.compute(
            ticker,
            sentiment_data=news_data,
        )

        ret_data = data.get("retail", {})
        dim_results["retail"] = self._retail.compute(
            ticker,
            social_data=ret_data.get("social"),
            fear_greed=ret_data.get("fear_greed"),
        )

        available_count = sum(
            1 for d in DIMENSIONS if dim_results[d]["confidence"] > 0
        )

        composite, overall_confidence = self._compute_composite(
            dim_results, regime, available_count,
        )

        result = {
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regime": regime.value,
            "dimensions": dim_results,
            "composite_score": round(composite, 6),
            "weights": dict(self.weights),
            "confidence": round(overall_confidence, 4),
            "dimensions_available": available_count,
            "agent_summary": "",
        }
        result["agent_summary"] = self.get_agent_summary(result)
        return result
    def compute_batch(
        self,
        tickers: list[str],
        raw_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Compute divergence for multiple tickers."""
        batch_data = raw_data or {}
        results = []
        for ticker in tickers:
            ticker_data = batch_data.get(ticker)
            results.append(self.compute(ticker, raw_data=ticker_data))
        return results
    def get_agent_summary(self, result: dict[str, Any]) -> str:
        """Generate a concise summary string for LLM agent consumption."""
        composite = result["composite_score"]
        regime = result["regime"]
        dims = result["dimensions"]
        available = result["dimensions_available"]

        if abs(composite) < 0.1:
            direction = "NEUTRAL"
        elif composite > 0:
            direction = "BULLISH"
        else:
            direction = "BEARISH"

        if abs(composite) >= 0.5:
            strength = "STRONG"
        elif abs(composite) >= 0.2:
            strength = "MODERATE"
        else:
            strength = "WEAK"

        label = f"{strength} {direction}" if direction != "NEUTRAL" else "NEUTRAL"

        available_dims = {
            k: v for k, v in dims.items() if v["confidence"] > 0
        }

        if available_dims:
            strongest_name = max(
                available_dims, key=lambda k: abs(available_dims[k]["value"])
            )
            weakest_name = min(
                available_dims, key=lambda k: abs(available_dims[k]["value"])
            )
            s = available_dims[strongest_name]
            w = available_dims[weakest_name]
            s_conf = _conf_label(s["confidence"])
            w_conf = _conf_label(w["confidence"])
            sv = s["value"]
            wv = w["value"]
            strongest_str = f"{strongest_name} ({sv:+.2f}, {s_conf} conf)"
            weakest_str = f"{weakest_name} ({wv:+.2f}, {w_conf} conf)"
        else:
            strongest_str = "none"
            weakest_str = "none"

        tk = result["ticker"]
        return (
            f"{tk} Divergence: {label} ({composite:+.2f}) | "
            f"Regime: {regime} | "
            f"Strongest: {strongest_str} | "
            f"Weakest: {weakest_str} | "
            f"{available}/5 dimensions available"
        )
    def _detect_regime(
        self, regime_data: dict[str, Any] | None,
    ) -> RegimeState:
        """Run the regime detector on provided signals."""
        if regime_data is None:
            return self._regime_detector.detect()
        return self._regime_detector.detect(
            vix=regime_data.get("vix"),
            breadth=regime_data.get("breadth"),
            put_call_ratio=regime_data.get("put_call_ratio"),
        )

    def _compute_composite(
        self,
        dim_results: dict[str, dict[str, Any]],
        regime: RegimeState,
        available_count: int,
    ) -> tuple[float, float]:
        """Compute regime-adjusted weighted composite and overall confidence."""
        weighted_sum = 0.0
        weight_sum = 0.0

        # Redistribute weights among available dimensions
        active_weights: dict[str, float] = {}
        active_total = 0.0
        for dim_name in DIMENSIONS:
            if dim_results[dim_name]["confidence"] > 0:
                active_weights[dim_name] = self.weights.get(dim_name, 0.0)
                active_total += active_weights[dim_name]

        if active_total > 0:
            active_weights = {k: v / active_total for k, v in active_weights.items()}

        for dim_name, w in active_weights.items():
            score = dim_results[dim_name]
            conf = score["confidence"]
            effective_w = w * conf
            weighted_sum += score["value"] * effective_w
            weight_sum += effective_w

        if weight_sum == 0.0:
            composite = 0.0
        else:
            composite = weighted_sum / weight_sum

        # Regime adjustment
        multiplier = _REGIME_MULTIPLIERS.get(regime, 1.0)
        composite *= multiplier
        composite = max(-1.0, min(1.0, composite))

        # Overall confidence: average confidence of available dims * coverage
        if available_count == 0:
            overall_confidence = 0.0
        else:
            avg_conf = sum(
                dim_results[d]["confidence"]
                for d in DIMENSIONS
                if dim_results[d]["confidence"] > 0
            ) / available_count
            coverage = available_count / len(DIMENSIONS)
            overall_confidence = avg_conf * coverage

        return composite, overall_confidence
    def _fetch_from_connectors(self, ticker: str) -> dict[str, Any]:
        """Attempt to fetch data from registered connectors."""
        data: dict[str, Any] = {}
        try:
            from tradingagents.dataflows.connectors.registry import ConnectorRegistry
            registry = ConnectorRegistry()
            for connector_name in registry.list_connectors():
                try:
                    connector = registry.get(connector_name)
                    result = connector.fetch(ticker, {})
                    if result:
                        data.update(result)
                except Exception:
                    logger.debug(
                        "Connector %s failed for %s", connector_name, ticker,
                        exc_info=True,
                    )
        except ImportError:
            logger.warning("ConnectorRegistry not available; skipping auto-fetch")
        except Exception:
            logger.warning("Failed to auto-fetch from connectors", exc_info=True)
        return data


def _conf_label(confidence: float) -> str:
    """Map confidence float to human-readable label."""
    if confidence >= 0.7:
        return "high"
    if confidence >= 0.4:
        return "med"
    return "low"
