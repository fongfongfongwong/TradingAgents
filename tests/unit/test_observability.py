"""Tests for the observability layer: logging, cost tracking, and audit."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradingagents.observability.logger import (
    CorrelationContext,
    JSONFormatter,
    setup_logger,
)
from tradingagents.observability.cost_tracker import PersistentCostTracker
from tradingagents.observability.audit import AuditLogger, RETENTION_YEARS


# ---------------------------------------------------------------------------
# Logger tests
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    """Test that the JSON formatter produces well-formed JSON output."""

    def test_format_produces_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["name"] == "test"

    def test_format_includes_timestamp(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="warn",
            args=(),
            exc_info=None,
        )
        parsed = json.loads(formatter.format(record))
        assert "timestamp" in parsed
        assert "T" in parsed["timestamp"]  # ISO format

    def test_format_includes_correlation_id(self):
        CorrelationContext.set_correlation_id("test-corr-123")
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="with correlation",
            args=(),
            exc_info=None,
        )
        parsed = json.loads(formatter.format(record))
        assert parsed["correlation_id"] == "test-corr-123"

    def test_format_includes_extra_fields(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="extra",
            args=(),
            exc_info=None,
        )
        record.ticker = "AAPL"
        record.agent_name = "fundamentals_agent"
        parsed = json.loads(formatter.format(record))
        assert parsed["ticker"] == "AAPL"
        assert parsed["agent_name"] == "fundamentals_agent"


class TestCorrelationContext:
    """Test thread-local correlation ID management."""

    def test_set_and_get(self):
        CorrelationContext.set_correlation_id("abc-123")
        assert CorrelationContext.get_correlation_id() == "abc-123"

    def test_new_generates_unique(self):
        cid1 = CorrelationContext.new_correlation_id()
        cid2 = CorrelationContext.new_correlation_id()
        assert cid1 != cid2
        assert len(cid1) == 16

    def test_new_sets_current(self):
        cid = CorrelationContext.new_correlation_id()
        assert CorrelationContext.get_correlation_id() == cid


class TestSetupLogger:
    """Test the setup_logger factory function."""

    def test_returns_logger(self):
        logger = setup_logger("test.logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.logger"

    def test_logger_has_json_handler(self):
        logger = setup_logger("test.json_handler")
        assert len(logger.handlers) >= 1
        assert isinstance(logger.handlers[0].formatter, JSONFormatter)

    def test_logger_level(self):
        logger = setup_logger("test.debug_level", level="DEBUG")
        assert logger.level == logging.DEBUG


# ---------------------------------------------------------------------------
# PersistentCostTracker tests
# ---------------------------------------------------------------------------


class TestPersistentCostTracker:
    """Test SQLite-backed cost tracking."""

    @pytest.fixture(autouse=True)
    def _tracker(self, tmp_path):
        self.db_path = str(tmp_path / "costs.db")
        self.tracker = PersistentCostTracker(db_path=self.db_path)
        yield
        self.tracker.close()

    def test_record_and_daily_total(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 0.05)
        self.tracker.record("a2", "agent_b", "gpt-4o", 2000, 1000, 0.10)
        assert self.tracker.daily_total(today) == pytest.approx(0.15)

    def test_monthly_total(self):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 0.25)
        assert self.tracker.monthly_total(month) == pytest.approx(0.25)

    def test_daily_total_empty(self):
        assert self.tracker.daily_total("2020-01-01") == 0.0

    def test_by_model(self):
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 0.10)
        self.tracker.record("a2", "agent_b", "claude-sonnet", 2000, 1000, 0.20)
        self.tracker.record("a3", "agent_a", "gpt-4o", 500, 250, 0.05)
        breakdown = self.tracker.by_model(days=30)
        assert breakdown["gpt-4o"] == pytest.approx(0.15)
        assert breakdown["claude-sonnet"] == pytest.approx(0.20)

    def test_by_agent(self):
        self.tracker.record("a1", "fundamentals", "gpt-4o", 1000, 500, 0.10)
        self.tracker.record("a2", "sentiment", "gpt-4o", 2000, 1000, 0.30)
        breakdown = self.tracker.by_agent(days=30)
        assert breakdown["sentiment"] == pytest.approx(0.30)
        assert breakdown["fundamentals"] == pytest.approx(0.10)

    def test_budget_check_within(self):
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 0.05)
        result = self.tracker.budget_check(daily_limit=1.0, monthly_limit=10.0)
        assert result["within_budget"] is True
        assert result["daily_used"] == pytest.approx(0.05)

    def test_budget_check_over_daily(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 5.00)
        result = self.tracker.budget_check(daily_limit=1.0)
        assert result["within_budget"] is False
        assert result["daily_used"] == pytest.approx(5.00)

    def test_budget_check_over_monthly(self):
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 50.0)
        result = self.tracker.budget_check(monthly_limit=10.0)
        assert result["within_budget"] is False

    def test_summary_keys(self):
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 0.05)
        s = self.tracker.summary(days=30)
        assert "total_cost_usd" in s
        assert "call_count" in s
        assert "by_model" in s
        assert "by_agent" in s
        assert s["call_count"] == 1

    def test_budget_check_no_limits(self):
        self.tracker.record("a1", "agent_a", "gpt-4o", 1000, 500, 999.0)
        result = self.tracker.budget_check()
        assert result["within_budget"] is True


# ---------------------------------------------------------------------------
# AuditLogger tests
# ---------------------------------------------------------------------------


class TestAuditLogger:
    """Test SQLite-backed audit trail."""

    @pytest.fixture(autouse=True)
    def _audit(self, tmp_path):
        self.db_path = str(tmp_path / "audit.db")
        self.audit = AuditLogger(db_path=self.db_path)
        yield
        self.audit.close()

    def test_log_analysis_and_get_history(self):
        self.audit.log_analysis(
            analysis_id="run-001",
            ticker="AAPL",
            trade_date="2026-04-01",
            config={"model": "gpt-4o"},
            agents_used=["fundamentals", "sentiment"],
        )
        history = self.audit.get_history()
        assert len(history) == 1
        assert history[0]["ticker"] == "AAPL"
        assert history[0]["analysis_id"] == "run-001"
        assert history[0]["agents_used"] == ["fundamentals", "sentiment"]

    def test_log_decision(self):
        self.audit.log_analysis("run-002", "MSFT", "2026-04-01", {}, ["agent_a"])
        self.audit.log_decision("run-002", "BUY", 0.85, "Strong fundamentals")
        history = self.audit.get_history()
        assert history[0]["decision"] == "BUY"
        assert history[0]["confidence"] == pytest.approx(0.85)

    def test_filter_by_ticker(self):
        self.audit.log_analysis("run-a", "AAPL", "2026-04-01", {}, ["a"])
        self.audit.log_analysis("run-b", "MSFT", "2026-04-01", {}, ["b"])
        self.audit.log_analysis("run-c", "AAPL", "2026-04-02", {}, ["c"])

        aapl = self.audit.get_history(ticker="AAPL")
        assert len(aapl) == 2
        assert all(r["ticker"] == "AAPL" for r in aapl)

        msft = self.audit.get_history(ticker="MSFT")
        assert len(msft) == 1

    def test_log_trade(self):
        self.audit.log_analysis("run-t", "TSLA", "2026-04-01", {}, ["a"])
        self.audit.log_trade("run-t", {"action": "BUY", "qty": 100, "price": 250.0})
        # Verify trade was stored
        row = self.audit._conn.execute(
            "SELECT trade_data FROM trades WHERE analysis_id = ?", ("run-t",)
        ).fetchone()
        trade = json.loads(row["trade_data"])
        assert trade["action"] == "BUY"
        assert trade["qty"] == 100

    def test_retention_constant(self):
        assert RETENTION_YEARS == 7

    def test_history_limit(self):
        for i in range(10):
            self.audit.log_analysis(f"run-{i}", "AAPL", "2026-04-01", {}, ["a"])
        history = self.audit.get_history(limit=3)
        assert len(history) == 3


# ---------------------------------------------------------------------------
# Dockerfile structure tests
# ---------------------------------------------------------------------------


class TestDockerfileStructure:
    """Verify the Dockerfile exists and has correct structure."""

    @pytest.fixture(autouse=True)
    def _read_dockerfile(self):
        dockerfile_path = Path(__file__).resolve().parents[2] / "Dockerfile"
        assert dockerfile_path.exists(), f"Dockerfile not found at {dockerfile_path}"
        self.content = dockerfile_path.read_text()

    def test_multi_stage_builder(self):
        assert "FROM python:3.12-slim AS builder" in self.content

    def test_multi_stage_runtime(self):
        assert "FROM python:3.12-slim AS runtime" in self.content

    def test_non_root_user(self):
        assert "USER appuser" in self.content

    def test_expose_port(self):
        assert "EXPOSE 8000" in self.content

    def test_cmd_uvicorn(self):
        assert "uvicorn" in self.content
        assert "tradingagents.api.main:app" in self.content
