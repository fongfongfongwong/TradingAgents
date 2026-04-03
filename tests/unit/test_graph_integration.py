"""Tests for graph integration with new options and macro analysts.

Verifies that the LangGraph workflow compiles correctly with various
analyst combinations, and that all conditional logic methods exist.
"""

import pytest
from unittest.mock import MagicMock, patch

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.agents import (
    create_options_analyst,
    create_macro_analyst,
    create_market_analyst,
    create_social_media_analyst,
    create_news_analyst,
    create_fundamentals_analyst,
    create_msg_delete,
)


def _make_mock_llm():
    """Create a mock LLM that supports bind_tools."""
    llm = MagicMock()
    bound = MagicMock()
    llm.bind_tools.return_value = bound
    bound.invoke.return_value = MagicMock(
        tool_calls=[], content="mock report"
    )
    return llm


def _make_mock_tool_node():
    """Create a mock ToolNode."""
    return MagicMock()


def _build_graph_setup(selected_analysts):
    """Build a GraphSetup and compile a graph for the given analysts."""
    from tradingagents.graph.setup import GraphSetup

    llm = _make_mock_llm()
    conditional_logic = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)

    all_analyst_keys = ["market", "social", "news", "fundamentals", "options", "macro"]
    tool_nodes = {k: _make_mock_tool_node() for k in all_analyst_keys}

    setup = GraphSetup(
        quick_thinking_llm=llm,
        deep_thinking_llm=llm,
        tool_nodes=tool_nodes,
        bull_memory=MagicMock(),
        bear_memory=MagicMock(),
        trader_memory=MagicMock(),
        invest_judge_memory=MagicMock(),
        portfolio_manager_memory=MagicMock(),
        conditional_logic=conditional_logic,
    )
    return setup.setup_graph(selected_analysts)


class TestGraphCompilation:
    """Graph compiles with various analyst selections."""

    def test_original_four_analysts(self):
        graph = _build_graph_setup(["market", "social", "news", "fundamentals"])
        assert graph is not None

    def test_all_six_analysts(self):
        graph = _build_graph_setup(
            ["market", "social", "news", "fundamentals", "options", "macro"]
        )
        assert graph is not None

    def test_subset_market_options(self):
        graph = _build_graph_setup(["market", "options"])
        assert graph is not None

    def test_subset_macro_only(self):
        graph = _build_graph_setup(["macro"])
        assert graph is not None

    def test_subset_options_macro(self):
        graph = _build_graph_setup(["options", "macro"])
        assert graph is not None

    def test_empty_analysts_raises(self):
        with pytest.raises(ValueError, match="no analysts selected"):
            _build_graph_setup([])

    def test_single_fundamentals(self):
        graph = _build_graph_setup(["fundamentals"])
        assert graph is not None

    def test_all_original_plus_options(self):
        graph = _build_graph_setup(
            ["market", "social", "news", "fundamentals", "options"]
        )
        assert graph is not None


class TestConditionalLogicMethods:
    """Verify the new should_continue_* methods exist and behave correctly."""

    def setup_method(self):
        self.logic = ConditionalLogic()

    def test_should_continue_options_exists(self):
        assert hasattr(self.logic, "should_continue_options")
        assert callable(self.logic.should_continue_options)

    def test_should_continue_macro_exists(self):
        assert hasattr(self.logic, "should_continue_macro")
        assert callable(self.logic.should_continue_macro)

    def test_should_continue_options_routes_to_tools(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "get_divergence_report"}]
        state = {"messages": [msg]}
        result = self.logic.should_continue_options(state)
        assert result == "tools_options"

    def test_should_continue_options_routes_to_clear(self):
        msg = MagicMock()
        msg.tool_calls = []
        state = {"messages": [msg]}
        result = self.logic.should_continue_options(state)
        assert result == "Msg Clear Options"

    def test_should_continue_macro_routes_to_tools(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "get_macro_data"}]
        state = {"messages": [msg]}
        result = self.logic.should_continue_macro(state)
        assert result == "tools_macro"

    def test_should_continue_macro_routes_to_clear(self):
        msg = MagicMock()
        msg.tool_calls = []
        state = {"messages": [msg]}
        result = self.logic.should_continue_macro(state)
        assert result == "Msg Clear Macro"


class TestAgentFactories:
    """Verify new analyst factory functions return callables."""

    def test_create_options_analyst_returns_callable(self):
        llm = _make_mock_llm()
        node = create_options_analyst(llm)
        assert callable(node)

    def test_create_macro_analyst_returns_callable(self):
        llm = _make_mock_llm()
        node = create_macro_analyst(llm)
        assert callable(node)


class TestAgentExports:
    """Verify new analysts are exported from the agents package."""

    def test_options_analyst_in_all(self):
        import tradingagents.agents as agents_mod
        assert "create_options_analyst" in agents_mod.__all__

    def test_macro_analyst_in_all(self):
        import tradingagents.agents as agents_mod
        assert "create_macro_analyst" in agents_mod.__all__


class TestDefaultConfig:
    """Verify default_config includes options and macro analysts."""

    def test_selected_analysts_includes_options(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        assert "options" in DEFAULT_CONFIG["selected_analysts"]

    def test_selected_analysts_includes_macro(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        assert "macro" in DEFAULT_CONFIG["selected_analysts"]

    def test_selected_analysts_preserves_originals(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        for a in ["market", "social", "news", "fundamentals"]:
            assert a in DEFAULT_CONFIG["selected_analysts"]
