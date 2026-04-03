"""Configuration routes -- read and update runtime config."""

from __future__ import annotations

import copy
from typing import Any

from fastapi import APIRouter

from tradingagents.default_config import DEFAULT_CONFIG

router = APIRouter(prefix="/api", tags=["config"])

# Runtime config (starts as a copy of defaults)
_runtime_config: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)

# Keys that must never be exposed via the API
_SENSITIVE_PATTERNS = {"api_key", "secret", "token", "password", "credential"}


def _sanitize(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *cfg* with sensitive keys redacted."""
    sanitized: dict[str, Any] = {}
    for key, value in cfg.items():
        if any(pat in key.lower() for pat in _SENSITIVE_PATTERNS):
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize(value)
        else:
            sanitized[key] = value
    return sanitized


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Return the current runtime configuration (API keys redacted)."""
    return _sanitize(_runtime_config)


@router.put("/config")
async def update_config(body: dict[str, Any]) -> dict[str, Any]:
    """Merge *body* into the runtime configuration and return the result."""
    _runtime_config.update(body)
    return _sanitize(_runtime_config)
