"""Unit tests for G4 runtime configuration endpoints and accessor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradingagents.api.main import create_app
from tradingagents.api.models.responses import RuntimeConfig
from tradingagents.api.routes import config as config_module


@pytest.fixture()
def tmp_runtime_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the runtime config path to a temp dir for isolation."""
    cfg_dir = tmp_path / ".tradingagents"
    cfg_path = cfg_dir / "runtime_config.json"
    monkeypatch.setattr(config_module, "_RUNTIME_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_module, "_RUNTIME_CONFIG_PATH", cfg_path)
    config_module.reset_runtime_config_cache()
    yield cfg_path
    config_module.reset_runtime_config_cache()


@pytest.fixture()
def client(tmp_runtime_cfg: Path) -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# GET /api/config/runtime
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_returns_defaults_when_no_file(client: TestClient) -> None:
    resp = client.get("/api/config/runtime")
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm_provider"] == "anthropic"
    assert data["thesis_model"] == "claude-sonnet-4-5"
    assert data["synthesis_model"] == "claude-sonnet-4-5"
    assert data["budget_daily_usd"] == 15.0
    assert data["budget_per_ticker_usd"] == 0.6
    assert data["output_language"] == "en"
    assert set(data["analyst_selection"]) == {
        "market",
        "news",
        "fundamentals",
        "macro",
        "options",
        "social",
    }


# ---------------------------------------------------------------------------
# PUT /api/config/runtime
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_put_persists_and_accessor_reflects(
    client: TestClient, tmp_runtime_cfg: Path
) -> None:
    default = RuntimeConfig().model_dump()
    default["thesis_model"] = "claude-haiku-4-5-20251001"
    default["budget_daily_usd"] = 12.5
    default["output_language"] = "zh"

    resp = client.put("/api/config/runtime", json=default)
    assert resp.status_code == 200
    echoed = resp.json()
    assert echoed["thesis_model"] == "claude-haiku-4-5-20251001"
    assert echoed["budget_daily_usd"] == 12.5

    # File was written atomically and contains the new values.
    assert tmp_runtime_cfg.exists()
    on_disk = json.loads(tmp_runtime_cfg.read_text())
    assert on_disk["thesis_model"] == "claude-haiku-4-5-20251001"
    assert on_disk["budget_daily_usd"] == 12.5
    assert on_disk["output_language"] == "zh"

    # The read-only accessor returns the latest PUT value.
    live = config_module.get_runtime_config()
    assert live.thesis_model == "claude-haiku-4-5-20251001"
    assert live.output_language == "zh"
    assert live.budget_daily_usd == 12.5


@pytest.mark.unit
def test_put_rejects_invalid_enum(client: TestClient) -> None:
    body = RuntimeConfig().model_dump()
    body["output_language"] = "klingon"
    resp = client.put("/api/config/runtime", json=body)
    assert resp.status_code == 422


@pytest.mark.unit
def test_put_rejects_out_of_range_budget(client: TestClient) -> None:
    body = RuntimeConfig().model_dump()
    body["budget_daily_usd"] = 999_999.0  # above max 10_000
    resp = client.put("/api/config/runtime", json=body)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Persistence edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_loading_missing_fields_fills_defaults(tmp_runtime_cfg: Path) -> None:
    tmp_runtime_cfg.parent.mkdir(parents=True, exist_ok=True)
    # Partial config missing most fields.
    tmp_runtime_cfg.write_text(
        json.dumps({"thesis_model": "claude-haiku-4-5-20251001"})
    )
    config_module.reset_runtime_config_cache()
    cfg = config_module.get_runtime_config()
    assert cfg.thesis_model == "claude-haiku-4-5-20251001"
    # Every other field should be the default.
    assert cfg.antithesis_model == "claude-sonnet-4-5"
    assert cfg.budget_daily_usd == 15.0
    assert cfg.llm_provider == "anthropic"


@pytest.mark.unit
def test_invalid_json_on_disk_falls_back_to_defaults(tmp_runtime_cfg: Path) -> None:
    tmp_runtime_cfg.parent.mkdir(parents=True, exist_ok=True)
    tmp_runtime_cfg.write_text("{ not: valid json }")
    config_module.reset_runtime_config_cache()
    cfg = config_module.get_runtime_config()
    assert isinstance(cfg, RuntimeConfig)
    # Defaults intact.
    assert cfg.thesis_model == "claude-sonnet-4-5"


@pytest.mark.unit
def test_write_is_atomic_no_stray_tempfiles(
    client: TestClient, tmp_runtime_cfg: Path
) -> None:
    body = RuntimeConfig().model_dump()
    body["budget_per_ticker_usd"] = 2.0
    resp = client.put("/api/config/runtime", json=body)
    assert resp.status_code == 200

    # Only the final file should exist in the directory -- no leftover temps.
    files = list(tmp_runtime_cfg.parent.iterdir())
    assert [f.name for f in files] == [tmp_runtime_cfg.name]
