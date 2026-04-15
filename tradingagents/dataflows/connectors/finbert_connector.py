"""FinBERT local sentiment analysis connector.

Runs ProsusAI/finbert locally for financial sentiment scoring. Falls back
to realistic mock scores when the ``transformers`` library is unavailable.
No API key required — model runs entirely on the local machine.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

# Attempt to import transformers at module level so we know early
# whether the real model is available.
try:
    from transformers import pipeline as _hf_pipeline  # type: ignore[import-untyped]

    _HAS_TRANSFORMERS = True
except ImportError:
    _HAS_TRANSFORMERS = False


_LABEL_MAP = {
    "LABEL_0": "positive",
    "LABEL_1": "negative",
    "LABEL_2": "neutral",
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
}


class FinBERTConnector(BaseConnector):
    """Connector for local FinBERT sentiment analysis.

    Tier 1 (free): runs the ProsusAI/finbert model locally via
    HuggingFace ``transformers``.  If the library is not installed the
    connector returns realistic mock sentiment scores instead.
    """

    TIER = 1
    CATEGORIES = ["SENTIMENT"]

    _DATA_TYPES = ("score_text", "score_batch")

    def __init__(self) -> None:
        # No external rate limit needed — local inference only.
        super().__init__(rate_limit=1000, rate_period=60.0)
        self._pipeline: Any = None
        self._use_mock = not _HAS_TRANSFORMERS

    @property
    def name(self) -> str:
        return "finbert"

    @property
    def tier(self) -> int:
        return self.TIER

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.SENTIMENT]

    def connect(self) -> None:
        if _HAS_TRANSFORMERS:
            try:
                self._pipeline = _hf_pipeline(
                    "sentiment-analysis",
                    model="ProsusAI/finbert",
                    tokenizer="ProsusAI/finbert",
                    truncation=True,
                )
                self._use_mock = False
                logger.info("FinBERT model loaded successfully")
            except Exception as exc:
                logger.warning(
                    "Failed to load FinBERT model, falling back to mock: %s", exc
                )
                self._use_mock = True
        else:
            logger.warning(
                "transformers library not installed — using mock sentiment. "
                "Install with: pip install transformers torch"
            )
        super().connect()

    def disconnect(self) -> None:
        self._pipeline = None
        super().disconnect()

    @property
    def probe_data_type(self) -> str:
        return "health"

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "score_text")
        dispatch = {
            "health": self._fetch_health,
            "score_text": self._score_text,
            "score_batch": self._score_batch,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- health (probe) ---------------------------------------------------------

    def _fetch_health(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Lightweight probe -- just verify the connector is operational."""
        return {
            "status": "ok",
            "model": "ProsusAI/finbert",
            "mock": self._use_mock,
            "source": "finbert",
        }

    # -- score_text -------------------------------------------------------------

    def _score_text(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        text = params.get("text", "")
        if not text:
            raise ConnectorError("'text' parameter is required for score_text")

        result = self._analyse(text)
        return {
            "ticker": ticker,
            "result": result,
            "source": "finbert" if not self._use_mock else "finbert_mock",
        }

    # -- score_batch ------------------------------------------------------------

    def _score_batch(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        texts: list[str] = params.get("texts", [])
        if not texts:
            raise ConnectorError("'texts' parameter is required for score_batch")

        results = [self._analyse(t) for t in texts]
        return {
            "ticker": ticker,
            "results": results,
            "count": len(results),
            "source": "finbert" if not self._use_mock else "finbert_mock",
        }

    # -- internal helpers -------------------------------------------------------

    def _analyse(self, text: str) -> dict[str, Any]:
        """Score a single text string, using real model or mock."""
        if self._use_mock:
            return self._mock_score(text)
        return self._real_score(text)

    def _real_score(self, text: str) -> dict[str, Any]:
        if self._pipeline is None:
            raise ConnectorError("FinBERT pipeline not initialised — call connect()")

        output = self._pipeline(text[:512])[0]
        raw_label = output.get("label", "neutral")
        label = _LABEL_MAP.get(raw_label, raw_label)
        confidence = round(float(output.get("score", 0.0)), 4)

        # Convert label to a signed score for downstream consumers
        score_sign = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
        score = round(score_sign.get(label, 0.0) * confidence, 4)

        return {
            "text": text[:200],
            "sentiment": label,
            "score": score,
            "confidence": confidence,
        }

    @staticmethod
    def _mock_score(text: str) -> dict[str, Any]:
        """Return a deterministic-ish mock sentiment score."""
        random.seed(hash(text) % 2**32)
        score = round(random.uniform(-0.8, 0.8), 4)
        confidence = round(random.uniform(0.55, 0.97), 4)

        if score > 0.15:
            sentiment = "positive"
        elif score < -0.15:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "text": text[:200],
            "sentiment": sentiment,
            "score": score,
            "confidence": confidence,
        }
