"""Market regime detector using VIX, breadth, and put/call ratio signals.

Classifies the current market environment as RISK_ON, RISK_OFF, or
TRANSITIONING.  This matters because divergence signals predict *opposite*
outcomes in different regimes (Miller 1977; Atmaz & Basak 2018).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING

from .schemas import RegimeState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Combine multiple market-health signals into a single regime label.

    Parameters
    ----------
    vix_thresholds:
        (low, high) boundaries.  VIX < low -> RISK_ON, VIX > high -> RISK_OFF.
    breadth_threshold:
        Fraction of stocks above their 200-day SMA that separates bullish
        from bearish.  > threshold -> RISK_ON, < (1 - threshold) -> RISK_OFF.
    pc_thresholds:
        (low, high) for the equity put/call ratio.
        ratio < low -> RISK_ON, ratio > high -> RISK_OFF.
    """

    def __init__(
        self,
        vix_thresholds: tuple[float, float] = (20.0, 30.0),
        breadth_threshold: float = 0.5,
        pc_thresholds: tuple[float, float] = (0.7, 1.0),
    ) -> None:
        self.vix_low, self.vix_high = vix_thresholds
        self.breadth_threshold = breadth_threshold
        self.pc_low, self.pc_high = pc_thresholds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        vix: float | None = None,
        breadth: float | None = None,
        put_call_ratio: float | None = None,
    ) -> RegimeState:
        """Classify regime from available signals via majority vote.

        Any subset of signals may be provided.  When no signals are given the
        detector conservatively returns TRANSITIONING.
        """
        signals: list[RegimeState] = []

        if vix is not None:
            signals.append(self._classify_vix(vix))
        if breadth is not None:
            signals.append(self._classify_breadth(breadth))
        if put_call_ratio is not None:
            signals.append(self._classify_put_call(put_call_ratio))

        if not signals:
            logger.warning("RegimeDetector.detect called with no data; defaulting to TRANSITIONING")
            return RegimeState.TRANSITIONING

        return self._majority_vote(signals)

    def detect_from_data(self, ticker: str = "SPY") -> RegimeState:
        """Convenience wrapper that fetches live data from the CBOE connector.

        Falls back gracefully if any fetch fails.
        """
        vix: float | None = None
        pc_ratio: float | None = None

        try:
            from tradingagents.dataflows.connectors.cboe_connector import CBOEConnector

            connector = CBOEConnector()
            try:
                vix_data = connector.fetch(ticker, {"data_type": "vix"})
                vix = vix_data.get("close")
            except Exception:
                logger.warning("Failed to fetch VIX data", exc_info=True)

            try:
                pc_data = connector.fetch(ticker, {"data_type": "put_call_ratio"})
                pc_ratio = pc_data.get("total_pc_ratio") or pc_data.get("equity_pc_ratio")
            except Exception:
                logger.warning("Failed to fetch put/call ratio", exc_info=True)

            connector.disconnect()
        except Exception:
            logger.warning("Could not initialise CBOEConnector", exc_info=True)

        return self.detect(vix=vix, put_call_ratio=pc_ratio)

    # ------------------------------------------------------------------
    # Signal classifiers
    # ------------------------------------------------------------------

    def _classify_vix(self, vix: float) -> RegimeState:
        """VIX < low -> RISK_ON, VIX > high -> RISK_OFF, else TRANSITIONING."""
        if vix < self.vix_low:
            return RegimeState.RISK_ON
        if vix > self.vix_high:
            return RegimeState.RISK_OFF
        return RegimeState.TRANSITIONING

    def _classify_breadth(self, breadth: float) -> RegimeState:
        """Market breadth (% stocks > 200-day SMA).

        breadth > threshold -> RISK_ON
        breadth < (1 - threshold) -> RISK_OFF
        else -> TRANSITIONING
        """
        if breadth > self.breadth_threshold:
            return RegimeState.RISK_ON
        if breadth < (1.0 - self.breadth_threshold):
            return RegimeState.RISK_OFF
        return RegimeState.TRANSITIONING

    def _classify_put_call(self, pc_ratio: float) -> RegimeState:
        """Put/call ratio classification.

        ratio > high -> RISK_OFF (heavy put buying = fear)
        ratio < low  -> RISK_ON  (heavy call buying = greed)
        else         -> TRANSITIONING
        """
        if pc_ratio > self.pc_high:
            return RegimeState.RISK_OFF
        if pc_ratio < self.pc_low:
            return RegimeState.RISK_ON
        return RegimeState.TRANSITIONING

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _majority_vote(self, signals: list[RegimeState]) -> RegimeState:
        """Return the regime that appears most often.

        Ties (including all-disagree) resolve to TRANSITIONING, reflecting
        genuine uncertainty.
        """
        counts = Counter(signals)
        most_common = counts.most_common()

        # Strict majority: the top count must exceed any other count.
        if len(most_common) == 1:
            return most_common[0][0]

        top_count = most_common[0][1]
        second_count = most_common[1][1]
        if top_count > second_count:
            return most_common[0][0]

        # Tie -> uncertain
        return RegimeState.TRANSITIONING
