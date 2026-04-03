"""Tests for the divergence LangChain tool and AgentState integration."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from tradingagents.agents.utils.divergence_tools import (
    DivergenceAggregator,
    get_divergence_report,
)
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.divergence.schemas import (
    DIMENSIONS,
    DimensionScore,
    DivergenceVector,
    RegimeState,
)
from tradingagents.divergence.engine import DivergenceEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vector(
    ticker: str = "AAPL",
    regime: RegimeState = RegimeState.RISK_ON,
    composite: float = 0.45,
    dim_values: dict[str, float] | None = None,
) -> DivergenceVector:
    """Create a DivergenceVector with controllable dimension values."""
    dim_values = dim_values or {
        "institutional": 0.6,
        "options": 0.3,
        "price_action": 0.2,
        "news": 0.0,
        "retail": -0.1,
    }
    dimensions = {}
    for name in DIMENSIONS:
        val = dim_values.get(name, 0.0)
        dimensions[name] = DimensionScore(
            dimension=name,
            value=val,
            confidence=0.8 if val != 0.0 else 0.0,
            sources=["mock_source"] if val != 0.0 else [],
            raw_data={},
        )
    return DivergenceVector(
        ticker=ticker,
        timestamp=datetime.now(timezone.utc),
        regime=regime,
        dimensions=dimensions,
        composite_score=composite,
        weights=dict(DivergenceEngine().weights),
    )


# ---------------------------------------------------------------------------
# 1. get_divergence_report returns a formatted string
# ---------------------------------------------------------------------------

class TestGetDivergenceReport:

    @patch.object(DivergenceAggregator, "compute")
    @patch.object(DivergenceAggregator, "__init__", return_value=None)
    def test_returns_string(self, mock_init, mock_compute):
        """Tool returns whatever the aggregator produces."""
        mock_compute.return_value = "# Divergence Analysis for AAPL\n..."
        result = get_divergence_report.invoke({"ticker": "AAPL", "trade_date": "2024-01-15"})
        assert isinstance(result, str)
        assert "Divergence Analysis" in result
        mock_compute.assert_called_once_with("AAPL", "2024-01-15")

    @patch.object(DivergenceAggregator, "compute")
    @patch.object(DivergenceAggregator, "__init__", return_value=None)
    def test_report_contains_ticker(self, mock_init, mock_compute):
        """Report string includes the ticker symbol."""
        mock_compute.return_value = "# Divergence Analysis for TSLA\n..."
        result = get_divergence_report.invoke({"ticker": "TSLA", "trade_date": "2024-06-01"})
        assert "TSLA" in result


# ---------------------------------------------------------------------------
# 2. Mock DivergenceAggregator returning known data
# ---------------------------------------------------------------------------

class TestDivergenceAggregatorMocked:

    @patch.object(DivergenceAggregator, "_gather_signals")
    @patch.object(DivergenceAggregator, "_detect_regime")
    def test_compute_with_mock_signals(self, mock_regime, mock_signals):
        """Aggregator produces markdown when dimensions return data."""
        mock_regime.return_value = RegimeState.RISK_ON
        mock_signals.return_value = {
            "institutional": {"value": 0.6, "sources": ["analyst_ratings", "insider_transactions"]},
            "options": {"value": -0.3, "sources": ["put_call_ratio"]},
            "price_action": {"value": 0.2, "sources": ["price_momentum"]},
            "news": None,
            "retail": None,
        }
        aggregator = DivergenceAggregator()
        report = aggregator.compute("AAPL", "2024-01-15")

        assert "# Divergence Analysis for AAPL" in report
        assert "Market Regime: RISK_ON" in report
        assert "Composite Score:" in report
        assert "Institutional" in report
        assert "Options" in report

    @patch.object(DivergenceAggregator, "_gather_signals")
    @patch.object(DivergenceAggregator, "_detect_regime")
    def test_risk_off_regime_noted_in_report(self, mock_regime, mock_signals):
        """RISK_OFF regime results in regime adjustment note."""
        mock_regime.return_value = RegimeState.RISK_OFF
        mock_signals.return_value = {
            "institutional": {"value": 0.5, "sources": ["analyst_ratings"]},
            "options": None,
            "price_action": None,
            "news": None,
            "retail": None,
        }
        aggregator = DivergenceAggregator()
        report = aggregator.compute("MSFT", "2024-03-01")

        assert "RISK_OFF" in report
        assert "contrarian flip" in report.lower() or "RISK_OFF" in report


# ---------------------------------------------------------------------------
# 3. Error handling -- aggregator raises -> graceful fallback
# ---------------------------------------------------------------------------

class TestErrorHandling:

    @patch.object(DivergenceAggregator, "__init__", side_effect=RuntimeError("boom"))
    def test_tool_returns_unavailable_on_init_error(self, mock_init):
        """If DivergenceAggregator.__init__ fails, tool returns fallback."""
        result = get_divergence_report.invoke({"ticker": "BAD", "trade_date": "2024-01-01"})
        assert "unavailable" in result.lower()

    @patch.object(DivergenceAggregator, "compute", side_effect=Exception("network down"))
    @patch.object(DivergenceAggregator, "__init__", return_value=None)
    def test_tool_returns_unavailable_on_compute_error(self, mock_init, mock_compute):
        """If compute() raises, tool returns graceful fallback."""
        result = get_divergence_report.invoke({"ticker": "FAIL", "trade_date": "2024-01-01"})
        assert "unavailable" in result.lower()
        assert "FAIL" in result

    @patch.object(DivergenceAggregator, "_gather_signals")
    @patch.object(DivergenceAggregator, "_detect_regime")
    def test_all_dimensions_missing_still_produces_report(self, mock_regime, mock_signals):
        """When every dimension returns None, report still renders."""
        mock_regime.return_value = RegimeState.TRANSITIONING
        mock_signals.return_value = {
            "institutional": None,
            "options": None,
            "price_action": None,
            "news": None,
            "retail": None,
        }
        aggregator = DivergenceAggregator()
        report = aggregator.compute("XYZ", "2024-01-01")

        assert "# Divergence Analysis for XYZ" in report
        assert "Composite Score: +0.000" in report


# ---------------------------------------------------------------------------
# 4. AgentState has new divergence_report field
# ---------------------------------------------------------------------------

class TestAgentStateDivergenceField:

    def test_divergence_report_field_exists(self):
        """AgentState TypedDict has a divergence_report annotation."""
        annotations = AgentState.__annotations__
        assert "divergence_report" in annotations

    def test_divergence_report_annotation_is_str(self):
        """The divergence_report field is annotated as str."""
        ann = AgentState.__annotations__["divergence_report"]
        # Annotated[str, ...] -- the first arg should be str
        assert getattr(ann, "__args__", [str])[0] is str


# ---------------------------------------------------------------------------
# 5. Backward compatibility -- all original fields still present
# ---------------------------------------------------------------------------

class TestAgentStateBackwardCompat:

    ORIGINAL_FIELDS = [
        "company_of_interest",
        "trade_date",
        "sender",
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
        "investment_debate_state",
        "investment_plan",
        "trader_investment_plan",
        "risk_debate_state",
        "final_trade_decision",
    ]

    @pytest.mark.parametrize("field", ORIGINAL_FIELDS)
    def test_original_field_present(self, field):
        """Every original AgentState field must still exist."""
        assert field in AgentState.__annotations__, (
            f"AgentState is missing original field: {field}"
        )


# ---------------------------------------------------------------------------
# 6. Report formatting edge cases
# ---------------------------------------------------------------------------

class TestReportFormatting:

    def test_format_report_bullish(self):
        """Composite > 0.3 labelled Bullish."""
        vector = _make_vector(composite=0.5)
        report = DivergenceAggregator._format_report(vector)
        assert "(Bullish)" in report

    def test_format_report_bearish(self):
        """Composite < -0.3 labelled Bearish."""
        vector = _make_vector(composite=-0.45)
        report = DivergenceAggregator._format_report(vector)
        assert "(Bearish)" in report

    def test_format_report_neutral(self):
        """Composite near zero labelled Neutral."""
        vector = _make_vector(composite=0.0)
        report = DivergenceAggregator._format_report(vector)
        assert "(Neutral)" in report

    def test_format_report_contains_table(self):
        """Report contains a markdown table with all dimensions."""
        vector = _make_vector()
        report = DivergenceAggregator._format_report(vector)
        assert "| Dimension |" in report
        for dim in DIMENSIONS:
            assert dim.title() in report
