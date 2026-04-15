"""Configuration routes -- read and update runtime config."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from tradingagents.api.models.responses import RuntimeConfig
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["config"])

# Runtime config (starts as a copy of defaults)
_runtime_config: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)

# Keys that must never be exposed via the API
_SENSITIVE_PATTERNS = {"api_key", "secret", "token", "password", "credential"}

# All configurable API keys with metadata
API_KEY_REGISTRY: list[dict[str, str]] = [
    {"id": "POLYGON_API_KEY", "label": "Polygon.io", "category": "Market Data", "tier": "$29/mo", "url": "https://polygon.io/"},
    {"id": "FMP_API_KEY", "label": "Financial Modeling Prep", "category": "Fundamentals", "tier": "$49/mo", "url": "https://financialmodelingprep.com/"},
    {"id": "QUIVER_API_KEY", "label": "Quiver Quant", "category": "Social", "tier": "$75/mo", "url": "https://quiverquant.com/"},
    {"id": "FINNHUB_API_KEY", "label": "Finnhub", "category": "News & Sentiment", "tier": "Free", "url": "https://finnhub.io/"},
    {"id": "UNUSUAL_WHALES_API_KEY", "label": "Unusual Whales", "category": "Options Flow", "tier": "$50/mo", "url": "https://unusualwhales.com/"},
    {"id": "ORATS_API_KEY", "label": "ORATS", "category": "IV Analytics", "tier": "$99/mo", "url": "https://orats.com/"},
    {"id": "FINTEL_API_KEY", "label": "Fintel", "category": "Holdings", "tier": "$25/mo", "url": "https://fintel.io/"},
    {"id": "FRED_API_KEY", "label": "FRED", "category": "Macro", "tier": "Free", "url": "https://fred.stlouisfed.org/"},
    {"id": "TRADING_ECONOMICS_API_KEY", "label": "Trading Economics", "category": "Macro", "tier": "$149/mo", "url": "https://tradingeconomics.com/"},
    {"id": "SEC_API_KEY", "label": "SEC-API.io", "category": "Filings", "tier": "$55/mo", "url": "https://sec-api.io/"},
    {"id": "ALPHA_VANTAGE_API_KEY", "label": "Alpha Vantage", "category": "Market Data", "tier": "Free/Paid", "url": "https://alphavantage.co/"},
    {"id": "OPENAI_API_KEY", "label": "OpenAI", "category": "LLM", "tier": "Usage", "url": "https://platform.openai.com/"},
    {"id": "ANTHROPIC_API_KEY", "label": "Anthropic", "category": "LLM", "tier": "Usage", "url": "https://console.anthropic.com/"},
    {"id": "GOOGLE_API_KEY", "label": "Google Gemini", "category": "LLM", "tier": "Usage", "url": "https://aistudio.google.com/"},
    {"id": "DATABENTO_API_KEY", "label": "Databento", "category": "Real-time Market Data", "tier": "$0.01/GB", "url": "https://databento.com/"},
    {"id": "ALPACA_API_KEY", "label": "Alpaca", "category": "Broker", "tier": "Free", "url": "https://alpaca.markets/"},
    {"id": "ALPACA_SECRET_KEY", "label": "Alpaca Secret", "category": "Broker", "tier": "Free", "url": "https://alpaca.markets/"},
    {"id": "BINANCE_API_KEY", "label": "Binance", "category": "Crypto", "tier": "Free", "url": "https://developers.binance.com/"},
    {"id": "COINGECKO_API_KEY", "label": "CoinGecko", "category": "Crypto", "tier": "Free", "url": "https://coingecko.com/"},
]


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


def _mask(val: str) -> str:
    """Show first 4 and last 4 chars only: sk-proj-xxxx...xxxx."""
    if not val or len(val) < 12:
        return ""
    return val[:4] + "..." + val[-4:]


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Return the current runtime configuration (API keys redacted)."""
    return _sanitize(_runtime_config)


@router.put("/config")
async def update_config(body: dict[str, Any]) -> dict[str, Any]:
    """Merge *body* into the runtime configuration and return the result."""
    _runtime_config.update(body)
    return _sanitize(_runtime_config)


@router.get("/config/api-keys")
async def get_api_keys() -> list[dict[str, str]]:
    """Return all API key slots with masked current values."""
    result = []
    for entry in API_KEY_REGISTRY:
        env_val = os.environ.get(entry["id"], "")
        configured = bool(env_val)
        result.append({
            **entry,
            "configured": str(configured).lower(),
            "masked_value": _mask(env_val) if configured else "",
        })
    return result


from tradingagents.gateway import api_key_store


@router.put("/config/api-keys")
async def set_api_keys(body: dict[str, str]) -> dict[str, Any]:
    """Set API keys at runtime AND persist to .env file.

    Accepts ``{"POLYGON_API_KEY": "pk_xxx", ...}``.
    Keys are set as environment variables, stored in runtime config,
    and written atomically to the project .env file so they survive restarts.
    """
    updated: list[str] = []
    persist_map: dict[str, str] = {}
    for key_id, value in body.items():
        # Only accept known key IDs
        known_ids = {e["id"] for e in API_KEY_REGISTRY}
        if key_id not in known_ids:
            continue
        value = value.strip()
        if not value:
            continue
        os.environ[key_id] = value
        # Also update runtime config api_keys dict
        short_name = key_id.replace("_API_KEY", "").replace("_SECRET_KEY", "_secret").lower()
        if "api_keys" in _runtime_config:
            _runtime_config["api_keys"][short_name] = value
        updated.append(key_id)
        persist_map[key_id] = value

    # Persist to SQLite key store for restart durability
    for k, v in persist_map.items():
        try:
            api_key_store.set_key(k, v)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist %s to DB: %s", k, exc)

    return {
        "updated": updated,
        "count": len(updated),
        "message": f"Set {len(updated)} API key(s). Persisted to ~/.tradingagents/api_keys.db.",
    }


# ---------------------------------------------------------------------------
# Diagnostic endpoint: ping each configured key against its upstream provider
# ---------------------------------------------------------------------------

def _probe_polygon(key: str) -> tuple[bool, str]:
    import requests
    r = requests.get(
        f"https://api.polygon.io/v2/aggs/ticker/AAPL/prev?apiKey={key}",
        timeout=10,
    )
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    data = r.json()
    if data.get("status") != "OK":
        return False, f"status={data.get('status')} msg={data.get('error','')[:80]}"
    close = data["results"][0]["c"]
    return True, f"AAPL prev close ${close}"


def _probe_alpha_vantage(key: str) -> tuple[bool, str]:
    import requests
    r = requests.get(
        "https://www.alphavantage.co/query"
        f"?function=GLOBAL_QUOTE&symbol=AAPL&apikey={key}",
        timeout=10,
    )
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    data = r.json()
    if "Error Message" in data:
        return False, data["Error Message"][:120]
    if "Note" in data:
        return False, f"Rate limit: {data['Note'][:100]}"
    if "Information" in data:
        return False, f"Info: {data['Information'][:100]}"
    price = data.get("Global Quote", {}).get("05. price")
    if not price:
        return False, f"No price field in response"
    return True, f"AAPL ${price}"


def _probe_finnhub(key: str) -> tuple[bool, str]:
    import requests
    r = requests.get(
        f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}",
        timeout=10,
    )
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    data = r.json()
    if "c" not in data:
        return False, f"Unexpected response: {data}"
    return True, f"AAPL ${data['c']}"


def _probe_quiver(key: str) -> tuple[bool, str]:
    import requests
    r = requests.get(
        "https://api.quiverquant.com/beta/live/congresstrading",
        headers={"Authorization": f"Bearer {key}"},
        timeout=15,
    )
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    data = r.json()
    if not isinstance(data, list):
        return False, f"Unexpected response shape"
    return True, f"{len(data)} congress trades available"


def _probe_fred(key: str) -> tuple[bool, str]:
    import requests
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=DFF&api_key={key}&file_type=json&limit=1&sort_order=desc",
        timeout=10,
    )
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    data = r.json()
    obs = data.get("observations") or []
    if not obs:
        return False, "no observations"
    return True, f"Fed funds rate {obs[0].get('value')}% @ {obs[0].get('date')}"


def _probe_anthropic(key: str) -> tuple[bool, str]:
    import requests
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "ok"}],
        },
        timeout=15,
    )
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:150]}"
    data = r.json()
    return True, f"ok (model={data.get('model','?')})"


_PROBES: dict[str, Any] = {
    "POLYGON_API_KEY": _probe_polygon,
    "ALPHA_VANTAGE_API_KEY": _probe_alpha_vantage,
    "FINNHUB_API_KEY": _probe_finnhub,
    "QUIVER_API_KEY": _probe_quiver,
    "FRED_API_KEY": _probe_fred,
    "ANTHROPIC_API_KEY": _probe_anthropic,
}


@router.get("/config/test-keys")
async def test_api_keys() -> dict[str, Any]:
    """Ping each configured API key against its upstream provider.

    Returns per-key status (ok/fail), detail message, and whether the connector
    is actually wired into the v3 pipeline today.
    """
    # Map of key_id -> (wired_to_pipeline, wired_location_or_notes)
    wired_map: dict[str, tuple[bool, str]] = {
        "ANTHROPIC_API_KEY": (True, "all 4 v3 agents (thesis/antithesis/base_rate/synthesis)"),
        "FINNHUB_API_KEY": (True, "materializer.NewsContext (event_flags + sentiment)"),
        "FRED_API_KEY": (True, "materializer.MacroContext (fed_funds_rate, yield_curve, regime)"),
        "POLYGON_API_KEY": (True, "materializer.PriceContext (via data_vendor_price='polygon')"),
        "ALPHA_VANTAGE_API_KEY": (True, "materializer.PriceContext (via data_vendor_price='alpha_vantage')"),
        "QUIVER_API_KEY": (True, "materializer.InstitutionalContext (congress/contracts/lobbying/insiders)"),
        "FMP_API_KEY": (False, "dead code"),
        "SEC_API_KEY": (False, "dead code"),
        "UNUSUAL_WHALES_API_KEY": (False, "dead code"),
        "ORATS_API_KEY": (False, "dead code"),
        "FINTEL_API_KEY": (False, "dead code"),
        "TRADING_ECONOMICS_API_KEY": (False, "dead code"),
    }

    results: list[dict[str, Any]] = []
    for entry in API_KEY_REGISTRY:
        key_id = entry["id"]
        key_val = os.environ.get(key_id, "").strip()
        if not key_val:
            continue  # skip unconfigured
        wired, wire_note = wired_map.get(key_id, (False, "unknown"))
        probe = _PROBES.get(key_id)
        if probe is None:
            results.append({
                "key_id": key_id,
                "label": entry["label"],
                "status": "skip",
                "detail": "no probe implemented",
                "wired": wired,
                "wire_note": wire_note,
            })
            continue
        try:
            ok, detail = probe(key_val)
            results.append({
                "key_id": key_id,
                "label": entry["label"],
                "status": "ok" if ok else "fail",
                "detail": detail,
                "wired": wired,
                "wire_note": wire_note,
            })
        except Exception as exc:  # noqa: BLE001
            results.append({
                "key_id": key_id,
                "label": entry["label"],
                "status": "error",
                "detail": str(exc)[:200],
                "wired": wired,
                "wire_note": wire_note,
            })

    return {
        "tested": len(results),
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "failed": sum(1 for r in results if r["status"] in ("fail", "error")),
        "results": results,
    }


# ---------------------------------------------------------------------------
# G4: Runtime configuration (thread-safe persistence)
# ---------------------------------------------------------------------------

_RUNTIME_CONFIG_DIR: Path = Path.home() / ".tradingagents"
_RUNTIME_CONFIG_PATH: Path = _RUNTIME_CONFIG_DIR / "runtime_config.json"
_runtime_cfg_lock = threading.Lock()
_runtime_cfg_cache: RuntimeConfig | None = None


def _load_runtime_from_disk() -> RuntimeConfig:
    """Read runtime config from disk, filling defaults for missing fields.

    Returns a fresh ``RuntimeConfig`` on any read/parse failure so the API
    never fails closed.
    """
    if not _RUNTIME_CONFIG_PATH.exists():
        return RuntimeConfig()
    try:
        with _RUNTIME_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read runtime config at %s (%s); falling back to defaults.",
            _RUNTIME_CONFIG_PATH,
            exc,
        )
        return RuntimeConfig()

    try:
        # Merge over defaults so missing fields are filled in (back-compat).
        merged = RuntimeConfig().model_dump()
        merged.update(raw)
        return RuntimeConfig.model_validate(merged)
    except ValidationError as exc:
        logger.warning(
            "Invalid runtime config on disk (%s); falling back to defaults.",
            exc,
        )
        return RuntimeConfig()


def _write_runtime_to_disk(cfg: RuntimeConfig) -> None:
    """Atomically write *cfg* to ``~/.tradingagents/runtime_config.json``.

    Uses tempfile + ``os.replace`` so partial writes cannot corrupt the file.
    """
    _RUNTIME_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = cfg.model_dump_json(indent=2)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".runtime_config_", suffix=".tmp", dir=str(_RUNTIME_CONFIG_DIR)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, _RUNTIME_CONFIG_PATH)
    except Exception:
        # Best-effort cleanup of the temp file on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_runtime_config() -> RuntimeConfig:
    """Return the current runtime config (read-through cache).

    Thread-safe. Reads from disk on first call and caches in memory.
    Agents import this to pick up live configuration changes.
    """
    global _runtime_cfg_cache
    with _runtime_cfg_lock:
        if _runtime_cfg_cache is None:
            _runtime_cfg_cache = _load_runtime_from_disk()
        return _runtime_cfg_cache


def _set_runtime_config(cfg: RuntimeConfig) -> RuntimeConfig:
    """Replace the cached runtime config and persist to disk."""
    global _runtime_cfg_cache
    with _runtime_cfg_lock:
        _write_runtime_to_disk(cfg)
        _runtime_cfg_cache = cfg
        return _runtime_cfg_cache


def reset_runtime_config_cache() -> None:
    """Clear the cached runtime config. Intended for tests only."""
    global _runtime_cfg_cache
    with _runtime_cfg_lock:
        _runtime_cfg_cache = None


@router.get("/config/runtime", response_model=RuntimeConfig)
async def get_runtime_config_route() -> RuntimeConfig:
    """Return the active runtime configuration."""
    return get_runtime_config()


@router.put("/config/runtime", response_model=RuntimeConfig)
async def put_runtime_config_route(body: RuntimeConfig) -> RuntimeConfig:
    """Validate, persist, and activate a new runtime configuration."""
    try:
        # FastAPI already validates via the body model, but re-parse to be
        # defensive against constructed dicts passed through model_dump.
        validated = RuntimeConfig.model_validate(body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return _set_runtime_config(validated)


# ---------------------------------------------------------------------------
# P0-4: Cost observability endpoints
# ---------------------------------------------------------------------------


@router.get("/config/costs/today")
async def get_costs_today() -> dict[str, Any]:
    """Return today's LLM spend breakdown.

    Shape::

        {
            "date": "2026-04-05",
            "total_usd": 12.34,
            "budget_daily_usd": 50.0,
            "budget_per_ticker_usd": 5.0,
            "pct_of_daily_budget": 24.68,
            "by_agent": {"thesis": 5.12, ...},
            "by_ticker": {"AAPL": 0.42, ...},
            "by_model": {"claude-sonnet-4-5": 9.34, ...},
            "call_count": 38,
            "budget_breached": false
        }
    """
    from datetime import date as _date

    from tradingagents.gateway.cost_tracker import get_cost_tracker

    tracker = get_cost_tracker()
    cfg = get_runtime_config()

    total = tracker.daily_total_usd()
    daily_budget = float(cfg.budget_daily_usd)
    per_ticker_budget = float(cfg.budget_per_ticker_usd)
    pct = (total / daily_budget * 100.0) if daily_budget > 0 else 0.0

    by_agent = {k: round(v, 6) for k, v in tracker.daily_total_by_agent().items()}
    by_ticker = {k: round(v, 6) for k, v in tracker.daily_total_by_ticker().items()}
    by_model = {k: round(v, 6) for k, v in tracker.daily_total_by_model().items()}

    return {
        "date": _date.today().isoformat(),
        "total_usd": round(total, 6),
        "budget_daily_usd": daily_budget,
        "budget_per_ticker_usd": per_ticker_budget,
        "pct_of_daily_budget": round(pct, 2),
        "by_agent": by_agent,
        "by_ticker": by_ticker,
        "by_model": by_model,
        "call_count": tracker.call_count_today(),
        "budget_breached": daily_budget > 0 and total >= daily_budget,
    }


@router.get("/config/costs/range")
async def get_costs_range(days: int = 7) -> list[dict[str, Any]]:
    """Return daily totals for the last *days* days (ascending by date)."""
    from tradingagents.gateway.cost_tracker import get_cost_tracker

    tracker = get_cost_tracker()
    return tracker.daily_totals_range(days)
