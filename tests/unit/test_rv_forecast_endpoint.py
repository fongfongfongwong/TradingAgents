"""Unit tests for the HAR-RV Ridge forecast API routes.

These tests mock the (possibly not-yet-existing) ``tradingagents.models.
har_rv_ridge`` and ``tradingagents.factors.har_rv_factors`` modules so the
endpoint plumbing can be verified in isolation from Agent R1-1 / R1-2's
deliverables.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tradingagents.api.main import create_app
from tradingagents.api.routes import rv_forecast as rv_forecast_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubTrainedModel:
    """Minimal stand-in for Agent R1-2's ``TrainedModel``."""

    def __init__(self, trained_at: str = "2026-04-05T12:00:00Z", train_rows: int = 12345) -> None:
        self.trained_at = trained_at
        self.train_rows = train_rows
        self.horizon = 1


def _stub_feature_frame() -> pd.DataFrame:
    cols = [
        "rv_d",
        "rv_w",
        "rv_m",
        "ret_d",
        "ret_w",
        "ret_m",
        "jump_d",
        "bipower_d",
        "log_rv_d",
        "log_rv_w",
    ]
    return pd.DataFrame([[0.0002] * len(cols)], columns=cols)


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_prediction_cache() -> None:
    """Ensure cached predictions don't leak between tests."""
    rv_forecast_module._PREDICTION_CACHE.clear()
    yield
    rv_forecast_module._PREDICTION_CACHE.clear()


def _install_stub_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    model_1d: Any | None,
    model_5d: Any | None,
    feature_frame: pd.DataFrame | None = None,
) -> None:
    """Install stub versions of the har_rv_ridge + har_rv_factors modules."""
    stub_model_module = types.ModuleType("tradingagents.models.har_rv_ridge")

    def _load_model(horizon: int):
        if horizon == 1:
            return model_1d
        if horizon == 5:
            return model_5d
        return None

    def _predict(model: Any, features: pd.DataFrame) -> pd.Series:
        return pd.Series([0.002], index=features.index)

    def _train_and_save(**kwargs: Any) -> dict[str, Any]:
        return {
            "pooled_r2": {"1d": 0.42, "5d": 0.31},
            "ic_mean": {"1d": 0.10, "5d": 0.07},
            "trained_at": "2026-04-05T12:00:00Z",
            "tickers": kwargs.get("tickers") or ["AAPL"],
        }

    stub_model_module.load_model = _load_model  # type: ignore[attr-defined]
    stub_model_module.predict = _predict  # type: ignore[attr-defined]
    stub_model_module.train_and_save = _train_and_save  # type: ignore[attr-defined]
    stub_model_module.TrainedModel = _StubTrainedModel  # type: ignore[attr-defined]

    stub_factor_module = types.ModuleType("tradingagents.factors.har_rv_factors")
    stub_factor_module.FEATURE_NAMES = tuple(  # type: ignore[attr-defined]
        (feature_frame or _stub_feature_frame()).columns.tolist()
    )

    def _compute_har_factors(ohlc: pd.DataFrame) -> pd.DataFrame:
        return feature_frame if feature_frame is not None else _stub_feature_frame()

    stub_factor_module.compute_har_factors = _compute_har_factors  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "tradingagents.models.har_rv_ridge", stub_model_module)
    monkeypatch.setitem(sys.modules, "tradingagents.factors.har_rv_factors", stub_factor_module)


def _stub_yfinance_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a yfinance stub whose ``Ticker.history`` returns a usable frame."""

    class _StubTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, period: str = "2y", auto_adjust: bool = False) -> pd.DataFrame:
            # 80 bars of plausible OHLC data so ``len(hist) >= 60`` holds.
            idx = pd.date_range(end="2026-04-04", periods=80, freq="B")
            close = pd.Series([100 + i * 0.1 for i in range(len(idx))], index=idx)
            return pd.DataFrame(
                {
                    "Open": close * 0.99,
                    "High": close * 1.01,
                    "Low": close * 0.98,
                    "Close": close,
                    "Volume": [1_000_000] * len(idx),
                }
            )

    stub_yf = types.ModuleType("yfinance")
    stub_yf.Ticker = _StubTicker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", stub_yf)


# ---------------------------------------------------------------------------
# /api/v3/rv/forecast/{ticker}
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_rv_forecast_returns_200_with_loaded_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_modules(monkeypatch, model_1d=_StubTrainedModel(), model_5d=None)
    _stub_yfinance_history(monkeypatch)

    response = client.get("/api/v3/rv/forecast/AAPL?horizon=1")
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["horizon_days"] == 1
    assert "predicted_rv_pct" in data
    assert "model_version" in data
    assert data["model_version"].startswith("har_rv_ridge_v1")
    assert "computed_at" in data
    # current_realized_vol_20d_pct and delta_pct may be None or numeric,
    # but the keys must always be present.
    assert "current_realized_vol_20d_pct" in data
    assert "delta_pct" in data


@pytest.mark.unit
def test_get_rv_forecast_returns_404_when_no_model_loaded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_modules(monkeypatch, model_1d=None, model_5d=None)
    _stub_yfinance_history(monkeypatch)

    response = client.get("/api/v3/rv/forecast/AAPL?horizon=1")
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert "No trained" in body["detail"]


# ---------------------------------------------------------------------------
# /api/v3/rv/model/status
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_model_status_reports_per_horizon_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_modules(
        monkeypatch,
        model_1d=_StubTrainedModel(trained_at="2026-04-05T12:00:00Z", train_rows=100),
        model_5d=None,
    )

    response = client.get("/api/v3/rv/model/status")
    assert response.status_code == 200

    data = response.json()
    assert "models" in data
    assert "1d" in data["models"]
    assert "5d" in data["models"]
    assert data["models"]["1d"]["loaded"] is True
    assert data["models"]["1d"]["version"].startswith("har_rv_ridge_v1_")
    assert data["models"]["1d"]["train_rows"] == 100
    assert data["models"]["5d"]["loaded"] is False
    assert "outputs_root" in data


# ---------------------------------------------------------------------------
# /api/v3/rv/train
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trigger_training_returns_summary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub_modules(monkeypatch, model_1d=_StubTrainedModel(), model_5d=_StubTrainedModel())

    response = client.post(
        "/api/v3/rv/train",
        json={"tickers": ["AAPL", "MSFT"], "horizons": [1, 5]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "ok"
    assert "summary" in data
    assert data["summary"]["pooled_r2"]["1d"] == 0.42
    assert data["summary"]["ic_mean"]["5d"] == 0.07
    assert "completed_at" in data


@pytest.mark.unit
def test_trigger_training_503_when_module_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the har_rv_ridge module isn't importable, return 503."""
    # Remove any previously imported stub so the import fails.
    monkeypatch.delitem(sys.modules, "tradingagents.models.har_rv_ridge", raising=False)

    real_import = __import__

    def _fail_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "tradingagents.models.har_rv_ridge":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fail_import)

    response = client.post("/api/v3/rv/train", json={})
    assert response.status_code == 503
    assert "training module" in response.json()["detail"].lower()
