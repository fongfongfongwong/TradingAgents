"""Options divergence dimension.

Measures divergence signals from the options market: put/call ratio
and VIX level.
"""

from __future__ import annotations

from typing import Any


class OptionsDimension:
    """Put/call ratio + VIX-level divergence calculator.

    Parameters
    ----------
    put_call_weight : float
        Weight for the put/call ratio component (default 0.6).
    vix_weight : float
        Weight for the VIX level component (default 0.4).
    """

    DIMENSION = "options"

    def __init__(
        self,
        put_call_weight: float = 0.6,
        vix_weight: float = 0.4,
    ) -> None:
        self.put_call_weight = put_call_weight
        self.vix_weight = vix_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        ticker: str,
        put_call_data: dict[str, Any] | None = None,
        vix_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the options divergence score.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol.
        put_call_data : dict | None
            Must contain ``"ratio"`` (float).  ratio > 1.0 is bearish,
            ratio < 0.7 is bullish.
        vix_data : dict | None
            Must contain ``"level"`` (float).  > 30 is fear, < 15 is
            complacency.

        Returns
        -------
        dict
            ``{"value", "confidence", "sources", "raw_data"}``
        """
        pc_score = self._put_call_score(put_call_data)
        vix_score = self._vix_score(vix_data)

        sources: list[str] = []
        raw: dict[str, Any] = {}

        have_pc = pc_score is not None
        have_vix = vix_score is not None

        if have_pc:
            sources.append("put_call_ratio")
            raw["put_call_score"] = pc_score
        if have_vix:
            sources.append("vix_level")
            raw["vix_score"] = vix_score

        if have_pc and have_vix:
            total_w = self.put_call_weight + self.vix_weight
            value = (
                self.put_call_weight * pc_score
                + self.vix_weight * vix_score
            ) / total_w
            confidence = 0.9
        elif have_pc:
            value = pc_score
            confidence = 0.5
        elif have_vix:
            value = vix_score
            confidence = 0.4
        else:
            value = 0.0
            confidence = 0.0

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
    def _put_call_score(data: dict[str, Any] | None) -> float | None:
        """Map put/call ratio to [-1, +1].

        - ratio >= 1.0  ->  -1  (bearish)
        - ratio <= 0.7  ->  +1  (bullish)
        - between: linear interpolation
        """
        if data is None:
            return None

        ratio = data.get("ratio")
        if ratio is None:
            return None

        if ratio >= 1.0:
            return -1.0
        if ratio <= 0.7:
            return 1.0

        # Linear interp: 0.7 -> +1, 1.0 -> -1
        # score = 1 - 2 * (ratio - 0.7) / 0.3
        return 1.0 - 2.0 * (ratio - 0.7) / 0.3

    @staticmethod
    def _vix_score(data: dict[str, Any] | None) -> float | None:
        """Map VIX level to [-1, +1].

        - level >= 30  ->  -1  (fear)
        - level <= 15  ->  +1  (complacency)
        - between: linear interpolation
        """
        if data is None:
            return None

        level = data.get("level")
        if level is None:
            return None

        if level >= 30:
            return -1.0
        if level <= 15:
            return 1.0

        # Linear interp: 15 -> +1, 30 -> -1
        return 1.0 - 2.0 * (level - 15) / 15.0
