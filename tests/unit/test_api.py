"""Tests for the TradingAgents FastAPI REST + SSE API.

Covers health, analysis, divergence, backtest, and config endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tradingagents.api.main import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_format(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert data["version"] == "2.0.0"
        assert data["tests_passed"] == 662


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


class TestAnalysis:
    _PAYLOAD = {
        "ticker": "AAPL",
        "trade_date": "2025-01-15",
        "selected_analysts": ["market", "news"],
        "debate_rounds": 1,
    }

    def test_post_analyze_returns_analysis_id(self, client: TestClient) -> None:
        resp = client.post("/api/analyze", json=self._PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert "analysis_id" in data
        assert data["status"] == "pending"
        assert data["ticker"] == "AAPL"

    def test_get_analyze_unknown_id_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/analyze/nonexistent")
        assert resp.status_code == 404

    def test_get_analyze_after_post(self, client: TestClient) -> None:
        post_resp = client.post("/api/analyze", json=self._PAYLOAD)
        aid = post_resp.json()["analysis_id"]
        get_resp = client.get(f"/api/analyze/{aid}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["analysis_id"] == aid
        assert data["ticker"] == "AAPL"

    def test_analyze_stream_unknown_id_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/analyze/nonexistent/stream")
        assert resp.status_code == 404

    def test_post_analyze_default_analysts(self, client: TestClient) -> None:
        payload = {"ticker": "MSFT", "trade_date": "2025-02-01"}
        resp = client.post("/api/analyze", json=payload)
        assert resp.status_code == 200
        assert resp.json()["ticker"] == "MSFT"

    def test_analyze_invalid_body_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/analyze", json={"bad_field": 123})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Divergence
# ---------------------------------------------------------------------------


class TestDivergence:
    def test_get_divergence_valid_ticker(self, client: TestClient) -> None:
        mock_result = {
            "ticker": "TSLA",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "regime": "risk_on",
            "dimensions": {},
            "composite_score": 0.42,
            "weights": {},
            "confidence": 0.5,
            "dimensions_available": 0,
            "agent_summary": "",
        }
        with patch(
            "tradingagents.divergence.aggregator.DivergenceAggregator"
        ) as MockAgg:
            MockAgg.return_value.compute.return_value = mock_result
            resp = client.get("/api/divergence/TSLA")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "TSLA"
        assert data["regime"] == "risk_on"
        assert isinstance(data["composite_score"], float)
        assert "dimensions" in data
        assert "timestamp" in data

    def test_get_divergence_response_schema(self, client: TestClient) -> None:
        mock_result = {
            "ticker": "GOOG",
            "timestamp": "2025-06-01T12:00:00+00:00",
            "regime": "transitioning",
            "dimensions": {"institutional": {"value": 0.1, "confidence": 0.5}},
            "composite_score": -0.15,
            "weights": {},
            "confidence": 0.3,
            "dimensions_available": 1,
            "agent_summary": "",
        }
        with patch(
            "tradingagents.divergence.aggregator.DivergenceAggregator"
        ) as MockAgg:
            MockAgg.return_value.compute.return_value = mock_result
            resp = client.get("/api/divergence/GOOG")

        data = resp.json()
        assert set(data.keys()) == {
            "ticker", "regime", "composite_score", "dimensions", "timestamp",
        }


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


class TestBacktest:
    _PAYLOAD = {
        "ticker": "AAPL",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 50_000,
    }

    def test_post_backtest_returns_valid_metrics(self, client: TestClient) -> None:
        mock_engine = MagicMock()
        mock_engine.run.return_value = {
            "equity_curve": [50000, 51000, 52000],
            "trades": [],
            "positions": {},
            "final_value": 52000,
            "initial_capital": 50000,
            "dates": ["2024-01-01", "2024-01-02", "2024-01-03"],
        }
        mock_metrics = MagicMock()
        mock_metrics.compute.return_value = {
            "total_return": 0.04,
            "sharpe_ratio": 1.2,
            "max_drawdown": 0.01,
        }

        with (
            patch(
                "tradingagents.backtest.engine.BacktestEngine",
                return_value=mock_engine,
            ),
            patch(
                "tradingagents.backtest.metrics.BacktestMetrics",
                return_value=mock_metrics,
            ),
        ):
            resp = client.post("/api/backtest", json=self._PAYLOAD)

        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert "metrics" in data
        assert "trades_count" in data

    def test_backtest_invalid_body(self, client: TestClient) -> None:
        resp = client.post("/api/backtest", json={"ticker": "AAPL"})
        assert resp.status_code == 422

    def test_backtest_default_capital(self, client: TestClient) -> None:
        payload = {
            "ticker": "NVDA",
            "start_date": "2024-01-01",
            "end_date": "2024-06-30",
        }
        mock_engine = MagicMock()
        mock_engine.run.return_value = {
            "equity_curve": [100000],
            "trades": [],
            "positions": {},
            "final_value": 100000,
            "initial_capital": 100000,
            "dates": ["2024-01-01"],
        }
        mock_metrics = MagicMock()
        mock_metrics.compute.return_value = {"total_return": 0.0}

        with (
            patch(
                "tradingagents.backtest.engine.BacktestEngine",
                return_value=mock_engine,
            ),
            patch(
                "tradingagents.backtest.metrics.BacktestMetrics",
                return_value=mock_metrics,
            ),
        ):
            resp = client.post("/api/backtest", json=payload)

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_get_config_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/config")
        assert resp.status_code == 200

    def test_get_config_no_api_keys(self, client: TestClient) -> None:
        data = client.get("/api/config").json()
        flat = _flatten_dict(data)
        for key, value in flat.items():
            if any(p in key.lower() for p in ("api_key", "secret", "token", "password")):
                assert value == "***REDACTED***", f"Key {key} not redacted"

    def test_put_config_updates_value(self, client: TestClient) -> None:
        resp = client.put("/api/config", json={"max_debate_rounds": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_debate_rounds"] == 3

    def test_get_config_has_expected_keys(self, client: TestClient) -> None:
        data = client.get("/api/config").json()
        assert "llm_provider" in data
        assert "selected_analysts" in data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    items: list[tuple[str, object]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)
