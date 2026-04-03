"""Institutional divergence dimension.

Measures divergence between analyst consensus / insider activity and
actual market behaviour.
"""

from __future__ import annotations

from typing import Any


class InstitutionalDimension:
    """Analyst consensus + insider-transaction divergence calculator.

    Parameters
    ----------
    analyst_weight : float
        Weight for the analyst consensus component (default 0.6).
    insider_weight : float
        Weight for the insider-transaction component (default 0.4).
    """

    DIMENSION = "institutional"

    def __init__(
        self,
        analyst_weight: float = 0.6,
        insider_weight: float = 0.4,
    ) -> None:
        self.analyst_weight = analyst_weight
        self.insider_weight = insider_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        ticker: str,
        analyst_data: dict[str, Any] | None = None,
        insider_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the institutional divergence score.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol.
        analyst_data : dict | None
            Finnhub-style analyst ratings with keys:
            ``strong_buy``, ``buy``, ``hold``, ``sell``, ``strong_sell``.
        insider_data : dict | None
            Insider-transaction summary with key ``net_buying`` (positive
            means net purchases, negative means net sales) and optional
            ``total_volume`` for normalisation.

        Returns
        -------
        dict
            ``{"value", "confidence", "sources", "raw_data"}``
        """
        analyst_score = self._analyst_score(analyst_data)
        insider_score = self._insider_score(insider_data)

        sources: list[str] = []
        raw: dict[str, Any] = {}

        have_analyst = analyst_score is not None
        have_insider = insider_score is not None

        if have_analyst:
            sources.append("analyst_ratings")
            raw["analyst_score"] = analyst_score
        if have_insider:
            sources.append("insider_transactions")
            raw["insider_score"] = insider_score

        # Combine available signals
        if have_analyst and have_insider:
            total_w = self.analyst_weight + self.insider_weight
            value = (
                self.analyst_weight * analyst_score
                + self.insider_weight * insider_score
            ) / total_w
            confidence = 0.9
        elif have_analyst:
            value = analyst_score
            confidence = 0.5
        elif have_insider:
            value = insider_score
            confidence = 0.4
        else:
            value = 0.0
            confidence = 0.0

        # Clamp to [-1, 1]
        value = max(-1.0, min(1.0, value))

        return {
            "value": round(value, 6),
            "confidence": confidence,
            "sources": sources,
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _analyst_score(data: dict[str, Any] | None) -> float | None:
        """Compute normalised analyst consensus in [-1, +1].

        Formula: (strong_buy*2 + buy*1 + hold*0 + sell*-1 + strong_sell*-2)
                 / total_ratings
        The raw weighted mean lies in [-2, +2]; we divide by 2 to normalise.
        """
        if data is None:
            return None

        sb = data.get("strong_buy", 0)
        b = data.get("buy", 0)
        h = data.get("hold", 0)
        s = data.get("sell", 0)
        ss = data.get("strong_sell", 0)

        total = sb + b + h + s + ss
        if total == 0:
            return None

        weighted = sb * 2 + b * 1 + h * 0 + s * (-1) + ss * (-2)
        # weighted / total is in [-2, +2]; normalise to [-1, +1]
        return (weighted / total) / 2.0

    @staticmethod
    def _insider_score(data: dict[str, Any] | None) -> float | None:
        """Normalise insider net-buying signal to [-1, +1].

        Expects ``net_buying`` (signed dollar/share amount) and
        ``total_volume`` for normalisation.  If ``total_volume`` is absent
        we use ``abs(net_buying)`` (giving +1 or -1).
        """
        if data is None:
            return None

        net = data.get("net_buying", 0)
        if net == 0:
            return 0.0

        total_vol = data.get("total_volume", abs(net))
        if total_vol == 0:
            return 0.0

        score = net / total_vol
        return max(-1.0, min(1.0, score))
