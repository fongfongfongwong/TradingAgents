"""Unit tests for new analyst agents, Pydantic schemas, and AgentState updates."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas.analyst_output import AnalystReport, FactorSignal
from tradingagents.agents.analysts.options_analyst import create_options_analyst
from tradingagents.agents.analysts.macro_analyst import create_macro_analyst, get_macro_data
from tradingagents.agents.utils.agent_states import AgentState


# =========================================================================
# FactorSignal validation
# =========================================================================

class TestFactorSignal:
    def test_valid_bullish_signal(self):
        sig = FactorSignal(
            name="put_call_ratio",
            value=0.6,
            confidence=0.85,
            direction="bullish",
            source="CBOE",
        )
        assert sig.name == "put_call_ratio"
        assert sig.value == 0.6
        assert sig.confidence == 0.85
        assert sig.direction == "bullish"
        assert sig.source == "CBOE"
        assert sig.timestamp is None

    def test_valid_signal_with_timestamp(self):
        ts = datetime(2025, 1, 15, 10, 30)
        sig = FactorSignal(
            name="iv_skew",
            value=-0.3,
            confidence=0.5,
            direction="bearish",
            source="options_chain",
            timestamp=ts,
        )
        assert sig.timestamp == ts

    def test_neutral_signal_zero_value(self):
        sig = FactorSignal(
            name="gamma_exposure",
            value=0.0,
            confidence=0.2,
            direction="neutral",
            source="market_maker",
        )
        assert sig.direction == "neutral"
        assert sig.value == 0.0

    def test_invalid_value_too_high(self):
        with pytest.raises(ValidationError):
            FactorSignal(
                name="test",
                value=1.5,
                confidence=0.5,
                direction="bullish",
                source="test",
            )

    def test_invalid_value_too_low(self):
        with pytest.raises(ValidationError):
            FactorSignal(
                name="test",
                value=-1.5,
                confidence=0.5,
                direction="bearish",
                source="test",
            )

    def test_invalid_confidence_above_one(self):
        with pytest.raises(ValidationError):
            FactorSignal(
                name="test",
                value=0.5,
                confidence=1.2,
                direction="bullish",
                source="test",
            )

    def test_invalid_confidence_negative(self):
        with pytest.raises(ValidationError):
            FactorSignal(
                name="test",
                value=0.5,
                confidence=-0.1,
                direction="bullish",
                source="test",
            )

    def test_invalid_direction(self):
        with pytest.raises(ValidationError):
            FactorSignal(
                name="test",
                value=0.5,
                confidence=0.5,
                direction="sideways",
                source="test",
            )

    def test_boundary_values(self):
        sig = FactorSignal(
            name="edge",
            value=-1.0,
            confidence=1.0,
            direction="bearish",
            source="test",
        )
        assert sig.value == -1.0
        assert sig.confidence == 1.0


# =========================================================================
# AnalystReport validation
# =========================================================================

class TestAnalystReport:
    def test_valid_report_minimal(self):
        report = AnalystReport(
            ticker="AAPL",
            analyst_type="options",
            text_report="Options analysis for AAPL shows elevated IV.",
            confidence=0.75,
        )
        assert report.ticker == "AAPL"
        assert report.analyst_type == "options"
        assert report.signals == []
        assert report.sources_cited == []
        assert report.insufficient_data is False

    def test_valid_report_with_signals(self):
        sig = FactorSignal(
            name="pc_ratio",
            value=0.4,
            confidence=0.8,
            direction="bullish",
            source="CBOE",
        )
        report = AnalystReport(
            ticker="TSLA",
            analyst_type="options",
            text_report="Bullish flow detected.",
            signals=[sig],
            confidence=0.8,
            sources_cited=["CBOE", "options_chain"],
        )
        assert len(report.signals) == 1
        assert report.signals[0].name == "pc_ratio"
        assert len(report.sources_cited) == 2

    def test_insufficient_data_flag(self):
        report = AnalystReport(
            ticker="XYZ",
            analyst_type="macro",
            text_report="Insufficient macro data available.",
            confidence=0.1,
            insufficient_data=True,
        )
        assert report.insufficient_data is True

    def test_invalid_confidence(self):
        with pytest.raises(ValidationError):
            AnalystReport(
                ticker="AAPL",
                analyst_type="options",
                text_report="report",
                confidence=2.0,
            )


# =========================================================================
# create_options_analyst
# =========================================================================

class TestOptionsAnalyst:
    def test_returns_callable(self):
        mock_llm = MagicMock()
        node_fn = create_options_analyst(mock_llm)
        assert callable(node_fn)

    def test_returns_callable_with_memory(self):
        mock_llm = MagicMock()
        mock_memory = MagicMock()
        node_fn = create_options_analyst(mock_llm, memory=mock_memory)
        assert callable(node_fn)


# =========================================================================
# create_macro_analyst
# =========================================================================

class TestMacroAnalyst:
    def test_returns_callable(self):
        mock_llm = MagicMock()
        node_fn = create_macro_analyst(mock_llm)
        assert callable(node_fn)

    def test_returns_callable_with_memory(self):
        mock_llm = MagicMock()
        mock_memory = MagicMock()
        node_fn = create_macro_analyst(mock_llm, memory=mock_memory)
        assert callable(node_fn)

    def test_get_macro_data_tool_exists(self):
        """Verify get_macro_data is a LangChain tool with correct metadata."""
        assert hasattr(get_macro_data, "name")
        assert get_macro_data.name == "get_macro_data"


# =========================================================================
# AgentState new fields
# =========================================================================

class TestAgentStateFields:
    def test_options_report_field_exists(self):
        annotations = AgentState.__annotations__
        assert "options_report" in annotations

    def test_macro_report_field_exists(self):
        annotations = AgentState.__annotations__
        assert "macro_report" in annotations

    def test_backward_compat_market_report(self):
        annotations = AgentState.__annotations__
        assert "market_report" in annotations

    def test_backward_compat_sentiment_report(self):
        annotations = AgentState.__annotations__
        assert "sentiment_report" in annotations

    def test_backward_compat_news_report(self):
        annotations = AgentState.__annotations__
        assert "news_report" in annotations

    def test_backward_compat_fundamentals_report(self):
        annotations = AgentState.__annotations__
        assert "fundamentals_report" in annotations

    def test_backward_compat_divergence_report(self):
        annotations = AgentState.__annotations__
        assert "divergence_report" in annotations
