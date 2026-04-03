"""Price-action divergence dimension.

Measures divergence between price momentum and mean-reversion signals.
When momentum (trend-following) and mean-reversion (RSI contrarian)
agree, the signal is strong.  When they diverge (e.g., strong uptrend
but RSI overbought), the combined score moves toward zero -- flagging
uncertainty.
"""

from __future__ import annotations

from typing import Any


class PriceActionDimension:
    """Momentum vs. mean-reversion divergence calculator.

    Parameters
    ----------
    momentum_weight : float
        Weight for the momentum component (default 0.5).
    mean_reversion_weight : float
        Weight for the mean-reversion component (default 0.5).
    """

    DIMENSION = "price_action"

    def __init__(
        self,
        momentum_weight: float = 0.5,
        mean_reversion_weight: float = 0.5,
    ) -> None:
        self.momentum_weight = momentum_weight
        self.mean_reversion_weight = mean_reversion_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        ticker: str,
        price_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the price-action divergence score.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol.
        price_data : dict | None
            Price/indicator data with keys:
            ``current_price``, ``sma_50``, ``sma_200``, ``rsi_14``.

        Returns
        -------
        dict
            ``{"value", "confidence", "sources", "raw_data"}``
        """
        momentum = self._momentum_signal(price_data)
        mean_rev = self._mean_reversion_signal(price_data)

        sources: list[str] = []
        raw: dict[str, Any] = {}

        have_momentum = momentum is not None
        have_mean_rev = mean_rev is not None

        if have_momentum:
            sources.append("price_momentum")
            raw["momentum_signal"] = momentum
        if have_mean_rev:
            sources.append("mean_reversion")
            raw["mean_reversion_signal"] = mean_rev

        if have_momentum and have_mean_rev:
            total_w = self.momentum_weight + self.mean_reversion_weight
            value = (
                self.momentum_weight * momentum
                + self.mean_reversion_weight * mean_rev
            ) / total_w
            # Higher confidence when signals agree, lower when divergent
            agreement = 1.0 - abs(momentum - mean_rev) / 2.0
            confidence = 0.5 + 0.4 * agreement
            raw["signals_agree"] = (momentum > 0) == (mean_rev > 0)
        elif have_momentum:
            value = momentum
            confidence = 0.4
        elif have_mean_rev:
            value = mean_rev
            confidence = 0.3
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
    def _momentum_signal(data: dict[str, Any] | None) -> float | None:
        """Compute trend-following momentum signal in [-1, +1].

        Rules:
        - price > SMA50 > SMA200 (golden alignment)  -> +1
        - price < SMA50 < SMA200 (death alignment)   -> -1
        - Mixed alignments produce intermediate values.
        """
        if data is None:
            return None

        price = data.get("current_price")
        sma50 = data.get("sma_50")
        sma200 = data.get("sma_200")

        if price is None or sma50 is None or sma200 is None:
            return None

        score = 0.0

        # Price vs SMA50 contribution
        if price > sma50:
            score += 0.5
        elif price < sma50:
            score -= 0.5

        # SMA50 vs SMA200 contribution
        if sma50 > sma200:
            score += 0.5
        elif sma50 < sma200:
            score -= 0.5

        return max(-1.0, min(1.0, score))

    @staticmethod
    def _mean_reversion_signal(data: dict[str, Any] | None) -> float | None:
        """Compute contrarian mean-reversion signal from RSI.

        RSI > 70 -> overbought -> contrarian bearish (negative score)
        RSI < 30 -> oversold   -> contrarian bullish (positive score)
        RSI ~50  -> neutral    -> ~0

        Maps RSI linearly:  score = (50 - rsi) / 50, clamped to [-1, +1].
        """
        if data is None:
            return None

        rsi = data.get("rsi_14")
        if rsi is None:
            return None

        score = (50.0 - rsi) / 50.0
        return max(-1.0, min(1.0, score))
