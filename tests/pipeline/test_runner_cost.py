"""Tests for pipeline_cost_usd and model_versions wiring in runner.py."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1: pipeline_cost_usd is non-zero when cost_tracker has entries
# ---------------------------------------------------------------------------


class TestPipelineCostUsd:
    """Verify _resolve_pipeline_cost reads from the real cost tracker."""

    def test_resolve_pipeline_cost_returns_tracker_value(self) -> None:
        from tradingagents.gateway.cost_tracker import CostEntry, get_cost_tracker

        tracker = get_cost_tracker()
        tracker.reset()

        # Record a cost entry for today
        today_str = datetime.now().strftime("%Y-%m-%d")
        tracker.record(
            CostEntry(
                ticker="AAPL",
                agent_name="thesis",
                model="claude-sonnet-4-5",
                input_tokens=1000,
                output_tokens=500,
                cost_usd=0.0105,
                timestamp=datetime.now(),
            )
        )

        from tradingagents.pipeline.runner import _resolve_pipeline_cost

        cost = _resolve_pipeline_cost("AAPL", today_str)
        assert cost > 0.0, f"Expected non-zero cost, got {cost}"
        assert cost == pytest.approx(0.0105, abs=1e-6)

        # Cleanup
        tracker.reset()

    def test_resolve_pipeline_cost_zero_when_no_entries(self) -> None:
        from tradingagents.gateway.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        tracker.reset()

        from tradingagents.pipeline.runner import _resolve_pipeline_cost

        today_str = datetime.now().strftime("%Y-%m-%d")
        cost = _resolve_pipeline_cost("AAPL", today_str)
        assert cost == 0.0

    def test_resolve_pipeline_cost_filters_by_ticker(self) -> None:
        from tradingagents.gateway.cost_tracker import CostEntry, get_cost_tracker

        tracker = get_cost_tracker()
        tracker.reset()

        today_str = datetime.now().strftime("%Y-%m-%d")
        tracker.record(
            CostEntry(
                ticker="TSLA",
                agent_name="thesis",
                model="claude-sonnet-4-5",
                input_tokens=1000,
                output_tokens=500,
                cost_usd=0.05,
                timestamp=datetime.now(),
            )
        )

        from tradingagents.pipeline.runner import _resolve_pipeline_cost

        # AAPL should be 0 since only TSLA was recorded
        cost = _resolve_pipeline_cost("AAPL", today_str)
        assert cost == 0.0

        # TSLA should be non-zero
        cost_tsla = _resolve_pipeline_cost("TSLA", today_str)
        assert cost_tsla == pytest.approx(0.05, abs=1e-6)

        tracker.reset()


# ---------------------------------------------------------------------------
# Test 2: model_versions reflects runtime config, not hardcoded strings
# ---------------------------------------------------------------------------


class TestModelVersions:
    """Verify _resolve_model_versions reads from RuntimeConfig."""

    def test_model_versions_from_runtime_config(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.thesis_model = "claude-sonnet-4-5"
        mock_cfg.antithesis_model = "claude-sonnet-4-5"
        mock_cfg.base_rate_model = "claude-sonnet-4-5"
        mock_cfg.synthesis_model = "claude-opus-4-1-20250805"

        with patch(
            "tradingagents.pipeline.runner.get_runtime_config",
            return_value=mock_cfg,
            create=True,
        ):
            # Need to patch at the import site inside _resolve_model_versions
            with patch(
                "tradingagents.api.routes.config.get_runtime_config",
                return_value=mock_cfg,
            ):
                from tradingagents.pipeline.runner import _resolve_model_versions

                versions = _resolve_model_versions()

        assert versions["thesis"] == "claude-sonnet-4-5"
        assert versions["antithesis"] == "claude-sonnet-4-5"
        assert versions["base_rate"] == "claude-sonnet-4-5"
        assert versions["synthesis"] == "claude-opus-4-1-20250805"

        # Verify these are NOT the old hardcoded values
        assert versions["thesis"] != "claude-4-sonnet"
        assert versions["synthesis"] != "claude-4-opus/sonnet"

    def test_model_versions_custom_config(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.thesis_model = "gpt-4o"
        mock_cfg.antithesis_model = "gpt-4o-mini"
        mock_cfg.base_rate_model = "gemini-2.0-flash"
        mock_cfg.synthesis_model = "claude-opus-4-1-20250805"

        with patch(
            "tradingagents.api.routes.config.get_runtime_config",
            return_value=mock_cfg,
        ):
            from tradingagents.pipeline.runner import _resolve_model_versions

            versions = _resolve_model_versions()

        assert versions["thesis"] == "gpt-4o"
        assert versions["antithesis"] == "gpt-4o-mini"
        assert versions["base_rate"] == "gemini-2.0-flash"
        assert versions["synthesis"] == "claude-opus-4-1-20250805"


# ---------------------------------------------------------------------------
# Test 3: Graceful fallback when config module is unavailable
# ---------------------------------------------------------------------------


class TestGracefulFallback:
    """Verify fallback behavior when config module raises."""

    def test_model_versions_fallback_on_import_error(self) -> None:
        with patch(
            "tradingagents.api.routes.config.get_runtime_config",
            side_effect=ImportError("config module unavailable"),
        ):
            from tradingagents.pipeline.runner import _resolve_model_versions

            versions = _resolve_model_versions()

        # Should return the hardcoded fallback
        assert versions == {
            "thesis": "claude-sonnet-4-5",
            "antithesis": "claude-sonnet-4-5",
            "base_rate": "claude-sonnet-4-5",
            "synthesis": "claude-sonnet-4-5",
        }

    def test_model_versions_fallback_on_runtime_error(self) -> None:
        with patch(
            "tradingagents.api.routes.config.get_runtime_config",
            side_effect=RuntimeError("disk read failed"),
        ):
            from tradingagents.pipeline.runner import _resolve_model_versions

            versions = _resolve_model_versions()

        assert versions == {
            "thesis": "claude-sonnet-4-5",
            "antithesis": "claude-sonnet-4-5",
            "base_rate": "claude-sonnet-4-5",
            "synthesis": "claude-sonnet-4-5",
        }

    def test_pipeline_cost_fallback_on_error(self) -> None:
        """_resolve_pipeline_cost returns 0.0 if an exception occurs."""
        from tradingagents.pipeline.runner import _resolve_pipeline_cost

        # Invalid date string should not crash, should return 0.0
        cost = _resolve_pipeline_cost("AAPL", "not-a-date")
        assert cost == 0.0
