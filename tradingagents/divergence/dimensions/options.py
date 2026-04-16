"""Options divergence dimension.

Measures divergence signals from the options market: put/call ratio, VIX
level, and — when the paid Databento OPRA feed is available — real-time
trade-flow PCR + flow-vs-OI divergence.
"""

from __future__ import annotations

from typing import Any


class OptionsDimension:
    """Multi-source options divergence calculator.

    Signals (each maps to ``[-1, +1]``):

    * Put/call ratio (OI-weighted, from yfinance)
    * VIX level (aggregate fear gauge)
    * Trade-flow PCR (real-time, from Databento OPRA trades) — optional
    * Flow-vs-OI divergence — positive when trade-flow is more bullish
      than OI PCR, negative when trades are more bearish than OI. A wide
      divergence signals **fresh positioning** that stale OI hasn't caught.

    Parameters
    ----------
    put_call_weight : float
        Weight for the OI-based put/call score (default 0.45).
    vix_weight : float
        Weight for the VIX level score (default 0.30).
    flow_pcr_weight : float
        Weight for the trade-flow PCR score when Databento is present
        (default 0.15).
    flow_divergence_weight : float
        Weight for the flow-vs-OI divergence signal (default 0.10).
    """

    DIMENSION = "options"

    def __init__(
        self,
        put_call_weight: float = 0.45,
        vix_weight: float = 0.30,
        flow_pcr_weight: float = 0.15,
        flow_divergence_weight: float = 0.10,
    ) -> None:
        self.put_call_weight = put_call_weight
        self.vix_weight = vix_weight
        self.flow_pcr_weight = flow_pcr_weight
        self.flow_divergence_weight = flow_divergence_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        ticker: str,
        put_call_data: dict[str, Any] | None = None,
        vix_data: dict[str, Any] | None = None,
        flow_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute the options divergence score.

        Parameters
        ----------
        ticker : str
            Stock ticker symbol.
        put_call_data : dict | None
            OI-based put/call ratio. Must contain ``"ratio"`` (float).
            ratio > 1.0 is bearish, ratio < 0.7 is bullish.
        vix_data : dict | None
            Must contain ``"level"`` (float). > 30 is fear, < 15 is
            complacency.
        flow_data : dict | None
            Optional trade-flow payload from Databento. Recognised keys:
              * ``"flow_pcr"``: trade-weighted put/call ratio
              * ``"large_trade_bias"``: normalised large-trade call/put
                balance in ``[-1, +1]`` (bullish when positive)

        Returns
        -------
        dict
            ``{"value", "confidence", "sources", "raw_data"}``
        """
        pc_score = self._put_call_score(put_call_data)
        vix_score = self._vix_score(vix_data)
        flow_pcr_score = self._flow_pcr_score(flow_data)
        divergence_score = self._flow_divergence_score(put_call_data, flow_data)
        large_trade_score = self._large_trade_score(flow_data)

        sources: list[str] = []
        raw: dict[str, Any] = {}

        have_pc = pc_score is not None
        have_vix = vix_score is not None
        have_flow_pcr = flow_pcr_score is not None
        have_divergence = divergence_score is not None
        have_large_trade = large_trade_score is not None

        if have_pc:
            sources.append("put_call_ratio")
            raw["put_call_score"] = pc_score
        if have_vix:
            sources.append("vix_level")
            raw["vix_score"] = vix_score
        if have_flow_pcr:
            sources.append("trade_flow_pcr")
            raw["flow_pcr_score"] = flow_pcr_score
        if have_divergence:
            sources.append("flow_vs_oi_divergence")
            raw["flow_divergence_score"] = divergence_score
        if have_large_trade:
            sources.append("large_trade_bias")
            raw["large_trade_score"] = large_trade_score

        # Build weighted components list; absent inputs are skipped and the
        # remaining weights are renormalised so a missing source doesn't
        # silently dampen the dimension magnitude.
        components: list[tuple[float, float]] = []
        if have_pc:
            components.append((pc_score, self.put_call_weight))
        if have_vix:
            components.append((vix_score, self.vix_weight))
        if have_flow_pcr:
            components.append((flow_pcr_score, self.flow_pcr_weight))
        if have_divergence:
            components.append((divergence_score, self.flow_divergence_weight))
        if have_large_trade:
            # Large-trade share reuses the divergence weight budget.
            components.append((large_trade_score, self.flow_divergence_weight / 2.0))

        if components:
            total_w = sum(w for _, w in components)
            value = sum(s * w for s, w in components) / total_w
        else:
            value = 0.0

        # Confidence baseline: PC + VIX alone yields 0.9 (preserves legacy
        # behaviour). Paid-feed sources add up to an additional +0.25 so a
        # fully-populated dimension saturates at 1.0.
        confidence = 0.0
        if have_pc:
            confidence += 0.50
        if have_vix:
            confidence += 0.40
        if have_flow_pcr:
            confidence += 0.10
        if have_divergence:
            confidence += 0.10
        if have_large_trade:
            confidence += 0.05

        value = max(-1.0, min(1.0, value))

        return {
            "value": round(value, 6),
            "confidence": round(min(confidence, 1.0), 6),
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

    @staticmethod
    def _flow_pcr_score(flow_data: dict[str, Any] | None) -> float | None:
        """Map real-time trade-flow PCR to ``[-1, +1]`` using the same curve
        as the OI-based PCR scorer. Returns ``None`` when no flow PCR is
        supplied.
        """
        if flow_data is None:
            return None
        flow_pcr = flow_data.get("flow_pcr")
        if flow_pcr is None:
            return None
        if flow_pcr >= 1.0:
            return -1.0
        if flow_pcr <= 0.7:
            return 1.0
        return 1.0 - 2.0 * (flow_pcr - 0.7) / 0.3

    @staticmethod
    def _flow_divergence_score(
        put_call_data: dict[str, Any] | None,
        flow_data: dict[str, Any] | None,
    ) -> float | None:
        """Score the divergence between real-time flow PCR and OI PCR.

        Returns a value in ``[-1, +1]``:

        * **positive** when flow PCR is **lower** than OI PCR (flow is more
          bullish than static OI would suggest — new long positioning).
        * **negative** when flow PCR is **higher** than OI PCR (flow is
          more bearish than OI — new short positioning).
        * **zero** when they agree.

        A ±0.5 gap in PCR maps to a full ±1.0 divergence score. Gaps smaller
        than 0.05 are ignored (inside noise floor).
        """
        if put_call_data is None or flow_data is None:
            return None
        oi_pcr = put_call_data.get("ratio")
        flow_pcr = flow_data.get("flow_pcr")
        if oi_pcr is None or flow_pcr is None:
            return None
        gap = float(oi_pcr) - float(flow_pcr)
        if abs(gap) < 0.05:
            return 0.0
        return max(-1.0, min(1.0, gap * 2.0))

    @staticmethod
    def _large_trade_score(flow_data: dict[str, Any] | None) -> float | None:
        """Return the ``large_trade_bias`` value when present (already in
        ``[-1, +1]``)."""
        if flow_data is None:
            return None
        bias = flow_data.get("large_trade_bias")
        if bias is None:
            return None
        return max(-1.0, min(1.0, float(bias)))
