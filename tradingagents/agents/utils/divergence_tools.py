"""LangChain-compatible tool for divergence analysis.

Orchestrates the Divergence Engine pipeline:
1. Detect market regime (via RegimeDetector)
2. Compute dimension scores (institutional, options, price_action)
3. Fuse into a DivergenceVector via DivergenceEngine
4. Return a formatted markdown report for LLM agent consumption
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


class DivergenceAggregator:
    """Orchestrates data collection and divergence computation for a ticker.

    This is the high-level facade that the tool function delegates to.
    It pulls data from connectors, runs dimension calculators, detects
    the market regime, and calls DivergenceEngine.compute().
    """

    def __init__(self) -> None:
        from tradingagents.divergence.engine import DivergenceEngine
        from tradingagents.divergence.regime import RegimeDetector
        from tradingagents.divergence.dimensions.institutional import (
            InstitutionalDimension,
        )
        from tradingagents.divergence.dimensions.options import OptionsDimension
        from tradingagents.divergence.dimensions.price_action import (
            PriceActionDimension,
        )

        self.engine = DivergenceEngine()
        self.regime_detector = RegimeDetector()
        self.institutional = InstitutionalDimension()
        self.options = OptionsDimension()
        self.price_action = PriceActionDimension()

    def compute(self, ticker: str, trade_date: str | None = None) -> str:
        """Run the full divergence pipeline and return a formatted report.

        Parameters
        ----------
        ticker : str
            Equity ticker symbol (e.g. ``"AAPL"``).
        trade_date : str | None
            Date string (yyyy-mm-dd), currently unused but reserved for
            historical look-back support.

        Returns
        -------
        str
            Markdown-formatted divergence report.
        """
        # 1. Detect market regime (gracefully falls back to TRANSITIONING)
        regime = self._detect_regime(ticker)

        # 2. Compute per-dimension raw signals
        raw_signals = self._gather_signals(ticker)

        # 3. Fuse into DivergenceVector
        vector = self.engine.compute(ticker, raw_signals, regime=regime)

        # 4. Format report
        return self._format_report(vector)

    # ------------------------------------------------------------------
    # Data gathering (best-effort, failures produce empty dimensions)
    # ------------------------------------------------------------------

    def _detect_regime(self, ticker: str):
        """Detect regime via RegimeDetector; fall back on failure."""
        from tradingagents.divergence.schemas import RegimeState

        try:
            return self.regime_detector.detect_from_data(ticker)
        except Exception:
            logger.warning("Regime detection failed; defaulting to TRANSITIONING", exc_info=True)
            return RegimeState.TRANSITIONING

    def _gather_signals(self, ticker: str) -> dict[str, dict[str, Any] | None]:
        """Collect signals from each dimension calculator.

        Each dimension calculator is called inside a try/except so a
        single failing connector never breaks the whole report.
        """
        signals: dict[str, dict[str, Any] | None] = {}

        # Institutional dimension -- tries connectors for analyst + insider data
        try:
            analyst_data = self._fetch_analyst_data(ticker)
            insider_data = self._fetch_insider_data(ticker)
            result = self.institutional.compute(ticker, analyst_data, insider_data)
            signals["institutional"] = result
        except Exception:
            logger.warning("Institutional dimension failed for %s", ticker, exc_info=True)
            signals["institutional"] = None

        # Options dimension -- tries CBOE connector for VIX + put/call
        try:
            pc_data, vix_data = self._fetch_options_data(ticker)
            result = self.options.compute(ticker, pc_data, vix_data)
            signals["options"] = result
        except Exception:
            logger.warning("Options dimension failed for %s", ticker, exc_info=True)
            signals["options"] = None

        # Price-action dimension -- tries yfinance for SMA/RSI
        try:
            price_data = self._fetch_price_data(ticker)
            result = self.price_action.compute(ticker, price_data)
            signals["price_action"] = result
        except Exception:
            logger.warning("Price-action dimension failed for %s", ticker, exc_info=True)
            signals["price_action"] = None

        # News and retail dimensions are not yet wired to connectors
        signals["news"] = None
        signals["retail"] = None

        return signals

    # ------------------------------------------------------------------
    # Connector helpers (best-effort)
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_analyst_data(ticker: str) -> dict[str, Any] | None:
        try:
            from tradingagents.dataflows.connectors.finnhub_connector import (
                FinnhubConnector,
            )

            c = FinnhubConnector()
            data = c.fetch(ticker, {"data_type": "analyst_ratings"})
            c.disconnect()
            return data
        except Exception:
            return None

    @staticmethod
    def _fetch_insider_data(ticker: str) -> dict[str, Any] | None:
        try:
            from tradingagents.dataflows.interface import route_to_vendor

            raw = route_to_vendor("get_insider_transactions", ticker)
            if isinstance(raw, dict):
                return raw
            return None
        except Exception:
            return None

    @staticmethod
    def _fetch_options_data(ticker: str) -> tuple[dict | None, dict | None]:
        try:
            from tradingagents.dataflows.connectors.cboe_connector import (
                CBOEConnector,
            )

            c = CBOEConnector()
            pc_data = None
            vix_data = None
            try:
                raw_pc = c.fetch(ticker, {"data_type": "put_call_ratio"})
                ratio = raw_pc.get("total_pc_ratio") or raw_pc.get("equity_pc_ratio")
                if ratio is not None:
                    pc_data = {"ratio": ratio}
            except Exception:
                pass
            try:
                raw_vix = c.fetch(ticker, {"data_type": "vix"})
                level = raw_vix.get("close")
                if level is not None:
                    vix_data = {"level": level}
            except Exception:
                pass
            c.disconnect()
            return pc_data, vix_data
        except Exception:
            return None, None

    @staticmethod
    def _fetch_price_data(ticker: str) -> dict[str, Any] | None:
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            hist = t.history(period="1y")
            if hist.empty:
                return None
            close = hist["Close"]
            current = float(close.iloc[-1])
            sma50 = float(close.rolling(50).mean().iloc[-1])
            sma200 = float(close.rolling(200).mean().iloc[-1])
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi_series = 100 - (100 / (1 + rs))
            rsi14 = float(rsi_series.iloc[-1])
            return {
                "current_price": current,
                "sma_50": sma50,
                "sma_200": sma200,
                "rsi_14": rsi14,
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Report formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_report(vector) -> str:
        """Build the markdown report from a DivergenceVector."""
        from tradingagents.divergence.schemas import DIMENSIONS, RegimeState

        composite = vector.composite_score
        if composite > 0.3:
            interpretation = "Bullish"
        elif composite < -0.3:
            interpretation = "Bearish"
        else:
            interpretation = "Neutral"

        regime_applied = vector.regime == RegimeState.RISK_OFF

        lines = [
            f"# Divergence Analysis for {vector.ticker}",
            f"## Market Regime: {vector.regime.value}",
            f"## Composite Score: {composite:+.3f} ({interpretation})",
            "",
            "### Dimension Breakdown:",
            "| Dimension | Score | Confidence | Signal |",
            "|-----------|-------|------------|--------|",
        ]

        for dim_name in DIMENSIONS:
            d = vector.dimensions.get(dim_name)
            if d is None:
                lines.append(f"| {dim_name.title()} | N/A | N/A | No Data |")
                continue
            if d.value > 0.15:
                signal = "Bullish"
            elif d.value < -0.15:
                signal = "Bearish"
            else:
                signal = "Neutral"
            conf_label = (
                "High" if d.confidence >= 0.7
                else "Medium" if d.confidence >= 0.4
                else "Low"
            )
            lines.append(
                f"| {dim_name.title()} | {d.value:+.3f} | {conf_label} | {signal} |"
            )

        strongest = vector.strongest_signal()
        lines.extend([
            "",
            "### Key Insights:",
            f"- Strongest signal: {strongest.dimension} at {strongest.value:+.3f}",
            f"- Regime adjustment applied: {'Yes -- RISK_OFF contrarian flip' if regime_applied else 'No'}",
            f"- Signals divergent: {vector.is_divergent()}",
        ])

        return "\n".join(lines)


@tool
def get_divergence_report(
    ticker: Annotated[str, "Ticker symbol of the company"],
    trade_date: Annotated[str, "Trade date in yyyy-mm-dd format"],
) -> str:
    """
    Compute a multi-dimensional divergence analysis for a given ticker.

    Fuses institutional flow, options sentiment, price-action momentum,
    news, and retail signals into a single divergence vector with a
    composite score and market-regime context.

    Args:
        ticker (str): Ticker symbol (e.g. AAPL, MSFT, TSLA)
        trade_date (str): Trade date in yyyy-mm-dd format

    Returns:
        str: A markdown-formatted divergence report with dimension
             breakdown, composite score, and key insights.
    """
    try:
        aggregator = DivergenceAggregator()
        return aggregator.compute(ticker, trade_date)
    except Exception:
        logger.exception("Divergence report failed for %s", ticker)
        return (
            f"Divergence data unavailable for {ticker}. "
            "The divergence connectors could not be reached. "
            "Please rely on other available data sources for your analysis."
        )
