"""Signals v3 routes -- batch run of the v3 pipeline for multiple tickers.

Exposes:

- ``GET  /api/v3/signals/batch?tickers=AAPL,MSFT,...&force=0`` (synchronous)
- ``POST /api/v3/signals/batch/start`` (fire-and-forget, returns ``batch_id``)
- ``GET  /api/v3/signals/batch/{batch_id}/stream`` (SSE live progress)

Two-tier caching:

- **L1**: in-memory 5-minute TTL dict (hot path, cheap).
- **L2**: SQLite-backed 24h TTL store in ``~/.tradingagents/signals_cache.db``.

Concurrency: a module-level ``asyncio.Semaphore(5)`` gates LLM pipeline runs
so a 40/80-ticker Run All doesn't overwhelm upstream APIs. Cache hits skip
the semaphore entirely.

Per-ticker errors never bleed into the batch -- failing tickers return a
HOLD item with the error recorded in ``data_gaps``.
"""

from __future__ import annotations

import asyncio
import importlib
import json as _json
import logging
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from tradingagents.gateway import signals_cache
from tradingagents.gateway.cost_tracker import get_cost_tracker

from ..models.responses import BatchSignalItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["signals_v3"])

# ---------------------------------------------------------------------------
# L1 in-memory TTL cache (kept for hot-path reads; name preserved for tests)
# ---------------------------------------------------------------------------

_L1_TTL_SECONDS: int = 300  # 5 minutes
_CACHE_TTL_SECONDS: int = _L1_TTL_SECONDS  # legacy alias
_cache: dict[str, tuple[float, BatchSignalItem]] = {}


def _cache_get(key: str) -> BatchSignalItem | None:
    """Return the L1-cached item if present and not expired, else ``None``."""
    entry = _cache.get(key)
    if entry is None:
        return None
    stored_at, item = entry
    if time.time() - stored_at > _L1_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return item.model_copy(update={"cached": True})


def _cache_set(key: str, item: BatchSignalItem) -> None:
    """Store ``item`` in the L1 cache under ``key``."""
    _cache[key] = (time.time(), item)


# ---------------------------------------------------------------------------
# L2 SQLite cache helpers
# ---------------------------------------------------------------------------


def _l2_get(ticker: str, analysis_date: str) -> BatchSignalItem | None:
    """Return the L2-cached ``BatchSignalItem`` or ``None``."""
    try:
        blob = signals_cache.get(ticker, analysis_date)
    except Exception as exc:  # noqa: BLE001 - L2 must never break requests
        logger.warning("signals_cache.get failed for %s: %s", ticker, exc)
        return None
    if blob is None:
        return None
    try:
        item = BatchSignalItem.model_validate(blob)
    except Exception as exc:  # noqa: BLE001
        logger.warning("L2 cache blob for %s rejected by model: %s", ticker, exc)
        return None
    return item.model_copy(update={"cached": True})


def _l2_put(ticker: str, analysis_date: str, item: BatchSignalItem) -> None:
    """Persist ``item`` to the L2 SQLite cache (best effort)."""
    try:
        signals_cache.put(ticker, analysis_date, item.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("signals_cache.put failed for %s: %s", ticker, exc)


# ---------------------------------------------------------------------------
# Concurrency limiter
# ---------------------------------------------------------------------------

_SEMAPHORE_LIMIT: int = 5
_SEMAPHORE_LOCK: asyncio.Lock | None = None
_SIGNALS_SEMAPHORE: asyncio.Semaphore | None = None
_PIPELINE_TIMEOUT_SECONDS: int = 180  # 3-minute hard timeout per ticker

# ---------------------------------------------------------------------------
# Circuit breaker: skip pipeline if too many consecutive failures
# ---------------------------------------------------------------------------
_CIRCUIT_FAIL_COUNT: int = 0
_CIRCUIT_THRESHOLD: int = 3  # after 3 consecutive failures, trip the breaker
_CIRCUIT_TRIPPED: bool = False


def _circuit_record_success() -> None:
    global _CIRCUIT_FAIL_COUNT, _CIRCUIT_TRIPPED
    _CIRCUIT_FAIL_COUNT = 0
    _CIRCUIT_TRIPPED = False


def _circuit_record_failure() -> None:
    global _CIRCUIT_FAIL_COUNT, _CIRCUIT_TRIPPED
    _CIRCUIT_FAIL_COUNT += 1
    if _CIRCUIT_FAIL_COUNT >= _CIRCUIT_THRESHOLD:
        _CIRCUIT_TRIPPED = True
        logger.warning(
            "Circuit breaker tripped after %d consecutive pipeline failures — "
            "remaining tickers will return mock HOLD signals",
            _CIRCUIT_FAIL_COUNT,
        )


async def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init the module semaphore under an async lock.

    FastAPI may spin up its event loop *after* module import, so binding a
    Semaphore or Lock at import time can attach it to the wrong loop.
    Creating both on first use (within the current running loop) avoids
    that pitfall.
    """
    global _SEMAPHORE_LOCK, _SIGNALS_SEMAPHORE
    if _SIGNALS_SEMAPHORE is not None:
        return _SIGNALS_SEMAPHORE
    if _SEMAPHORE_LOCK is None:
        _SEMAPHORE_LOCK = asyncio.Lock()
    async with _SEMAPHORE_LOCK:
        if _SIGNALS_SEMAPHORE is None:
            _SIGNALS_SEMAPHORE = asyncio.Semaphore(_SEMAPHORE_LIMIT)
    return _SIGNALS_SEMAPHORE


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------


def _load_run_analysis() -> Callable[..., Any]:
    """Lazily import ``run_analysis`` via importlib."""
    mod = importlib.import_module("tradingagents.pipeline.runner")
    return mod.run_analysis


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return ``values`` with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _decision_to_item(ticker: str, decision: Any) -> BatchSignalItem:
    """Convert a ``FinalDecision`` pydantic model to a ``BatchSignalItem``."""
    thesis = getattr(decision, "thesis", None)
    antithesis = getattr(decision, "antithesis", None)
    synthesis = getattr(decision, "synthesis", None)

    thesis_confidence: float | None = (
        float(thesis.confidence_score) if thesis is not None else None
    )
    antithesis_confidence: float | None = (
        float(antithesis.confidence_score) if antithesis is not None else None
    )
    expected_value_pct: float | None = (
        float(synthesis.expected_value_pct) if synthesis is not None else None
    )
    disagreement_score: float | None = (
        float(synthesis.disagreement_score) if synthesis is not None else None
    )

    signal_value = getattr(decision.signal, "value", decision.signal)
    tier_value = getattr(decision.tier, "value", decision.tier)

    cost_usd = float(get_cost_tracker().ticker_total_usd(ticker))
    model_versions = getattr(decision, "model_versions", None) or {}
    models_used = _dedupe_preserve_order(
        [str(v) for v in model_versions.values() if v is not None]
    )

    # Surface HAR-RV Ridge forecast fields from the propagated VolatilityContext
    # so the signals table can render forecast-vs-realized without a second
    # round-trip. All fields default to None when the context is absent.
    volatility = getattr(decision, "volatility", None)
    predicted_rv_1d_pct = (
        getattr(volatility, "predicted_rv_1d_pct", None) if volatility else None
    )
    predicted_rv_5d_pct = (
        getattr(volatility, "predicted_rv_5d_pct", None) if volatility else None
    )
    rv_forecast_delta_pct = (
        getattr(volatility, "rv_forecast_delta_pct", None) if volatility else None
    )
    rv_forecast_model_version = (
        getattr(volatility, "rv_forecast_model_version", None)
        if volatility
        else None
    )

    # Extract TP/SL from RiskOutput (if available)
    risk = getattr(decision, "risk", None)
    tp_price = getattr(risk, "take_profit_price", None) if risk else None
    sl_price = getattr(risk, "stop_loss_price", None) if risk else None
    risk_reward = getattr(risk, "risk_reward_ratio", None) if risk else None

    return BatchSignalItem(
        ticker=ticker,
        signal=signal_value,
        conviction=int(decision.conviction),
        tier=int(tier_value),
        expected_value_pct=expected_value_pct,
        thesis_confidence=thesis_confidence,
        antithesis_confidence=antithesis_confidence,
        disagreement_score=disagreement_score,
        final_shares=int(decision.final_shares),
        pipeline_latency_ms=int(decision.pipeline_latency_ms),
        data_gaps=[],
        cached=False,
        cost_usd=cost_usd,
        models_used=models_used,
        options_direction=getattr(decision, "options_direction", None),
        options_impact=getattr(decision, "options_impact", None),
        realized_vol_20d_pct=getattr(decision, "realized_vol_20d_pct", None),
        atr_pct_of_price=getattr(decision, "atr_pct_of_price", None),
        predicted_rv_1d_pct=predicted_rv_1d_pct,
        predicted_rv_5d_pct=predicted_rv_5d_pct,
        rv_forecast_delta_pct=rv_forecast_delta_pct,
        rv_forecast_model_version=rv_forecast_model_version,
        used_mock=bool(getattr(decision, "any_agent_used_mock", False)),
        tp_price=tp_price,
        sl_price=sl_price,
        risk_reward=risk_reward,
    )


def _error_item(ticker: str, message: str) -> BatchSignalItem:
    """Build a safe HOLD item for a ticker whose pipeline crashed."""
    return BatchSignalItem(
        ticker=ticker,
        signal="HOLD",
        conviction=0,
        tier=3,
        expected_value_pct=None,
        thesis_confidence=None,
        antithesis_confidence=None,
        disagreement_score=None,
        final_shares=0,
        pipeline_latency_ms=0,
        data_gaps=[f"pipeline_error: {message}"],
        cached=False,
    )


async def _invoke_pipeline(
    ticker: str,
    analysis_date: str,
    on_event: Callable[..., Any] | None = None,
) -> BatchSignalItem:
    """Run the v3 pipeline for one ticker inside the concurrency limiter.

    Applies a hard timeout of ``_PIPELINE_TIMEOUT_SECONDS`` per ticker to
    prevent a single slow ticker from blocking the semaphore indefinitely.
    """
    sem = await _get_semaphore()
    async with sem:
        run_analysis = _load_run_analysis()
        decision = await asyncio.wait_for(
            asyncio.to_thread(
                run_analysis,
                ticker=ticker,
                date=analysis_date,
                on_event=on_event,
            ),
            timeout=_PIPELINE_TIMEOUT_SECONDS,
        )
    return _decision_to_item(ticker, decision)


async def _run_one(
    ticker: str,
    analysis_date: str,
    *,
    force: bool = False,
    on_event: Callable[..., Any] | None = None,
) -> BatchSignalItem:
    """Resolve one ticker via L1 -> L2 -> pipeline, honouring ``force``."""
    cache_key = f"{ticker}:{analysis_date}"

    if not force:
        hit = _cache_get(cache_key)
        if hit is not None:
            return hit

        l2_hit = _l2_get(ticker, analysis_date)
        if l2_hit is not None:
            # Populate L1 with the canonical (non-cached) item so subsequent
            # L1 reads still flip the cached flag on return.
            _cache_set(cache_key, l2_hit.model_copy(update={"cached": False}))
            return l2_hit

    # Circuit breaker: skip pipeline when consecutive failures indicate a
    # systemic issue (e.g. API credits exhausted).
    if _CIRCUIT_TRIPPED:
        return _error_item(ticker, "circuit_breaker: pipeline disabled after repeated failures")

    try:
        item = await _invoke_pipeline(ticker, analysis_date, on_event=on_event)
        _circuit_record_success()
    except Exception as exc:  # noqa: BLE001 - must never crash the batch
        logger.exception("v3 pipeline failed for ticker %s", ticker)
        _circuit_record_failure()
        return _error_item(ticker, str(exc))

    _cache_set(cache_key, item)
    _l2_put(ticker, analysis_date, item)
    return item


# ---------------------------------------------------------------------------
# Ticker cleaning
# ---------------------------------------------------------------------------


def _clean_tickers(raw_tickers: list[str] | str) -> list[str]:
    """Normalise ticker input into a de-duped uppercase list."""
    if isinstance(raw_tickers, str):
        candidates = raw_tickers.split(",")
    else:
        candidates = list(raw_tickers)

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        if raw is None:
            continue
        t = str(raw).strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
    return cleaned


# ---------------------------------------------------------------------------
# Price enrichment
# ---------------------------------------------------------------------------


async def _enrich_prices(items: list[BatchSignalItem]) -> list[BatchSignalItem]:
    """Merge real-time prices into signal items (Databento > yfinance)."""
    if not items:
        return items

    tickers = [it.ticker for it in items]

    # 1) Try Databento live cache
    try:
        from tradingagents.dataflows.connectors.databento_connector import (
            get_all_snapshots,
        )
        db_snaps = get_all_snapshots()
    except Exception:
        db_snaps = {}

    # 2) yfinance fallback for missing tickers
    missing = [t for t in tickers if t not in db_snaps]
    yf_snaps: dict[str, dict] = {}
    if missing:
        try:
            from tradingagents.api.routes.realtime_prices import _yf_snapshot

            results = await asyncio.gather(
                *(asyncio.to_thread(_yf_snapshot, t) for t in missing),
                return_exceptions=True,
            )
            for t, snap in zip(missing, results):
                if isinstance(snap, dict) and snap is not None:
                    yf_snaps[t] = snap
        except Exception:
            pass

    # 3) Merge into items
    enriched: list[BatchSignalItem] = []
    for it in items:
        snap = db_snaps.get(it.ticker) or yf_snaps.get(it.ticker)
        if snap:
            it = it.model_copy(update={
                "last_price": snap.get("last"),
                "change_pct": snap.get("change_pct"),
            })
        enriched.append(it)

    return enriched


# ---------------------------------------------------------------------------
# Sync batch endpoint
# ---------------------------------------------------------------------------


@router.get("/signals/batch", response_model=list[BatchSignalItem])
async def batch_signals(
    tickers: str = Query(
        ...,
        description="Comma-separated ticker symbols (e.g. 'AAPL,MSFT,NVDA').",
    ),
    force: bool = Query(
        False,
        description="If true, bypass L1 and L2 cache and recompute fresh.",
    ),
) -> list[BatchSignalItem]:
    """Run the v3 pipeline for each ticker in parallel.

    Results are served from a two-tier cache (5-min in-memory L1 + 24h
    SQLite L2) keyed on ``f"{ticker}:{today}"``. Set ``force=1`` to bypass
    both cache layers and recompute.

    Tickers whose pipeline raises an exception are returned as HOLD items
    with the error in ``data_gaps``.
    """
    cleaned = _clean_tickers(tickers)
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail="'tickers' query parameter must contain at least one symbol",
        )

    analysis_date: str = date.today().isoformat()

    results = await asyncio.gather(
        *(_run_one(t, analysis_date, force=force) for t in cleaned),
        return_exceptions=False,
    )

    # Enrich with real-time price data (best-effort, never blocks signals)
    items = list(results)
    try:
        items = await _enrich_prices(items)
    except Exception:
        logger.debug("Price enrichment failed (non-fatal)", exc_info=True)

    return items


# ---------------------------------------------------------------------------
# Async batch with SSE progress
# ---------------------------------------------------------------------------

_batch_progress: dict[str, dict[str, Any]] = {}
_BATCH_RETENTION_SECONDS: int = 3600  # keep finished batches for 1h


def _new_progress_record(total: int) -> dict[str, Any]:
    return {
        "total": total,
        "completed": 0,
        "failed": 0,
        "results": [],
        "events": [],
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "last_ticker": None,
        "last_signal": None,
        "total_cost_usd": 0.0,
    }


def _append_event(batch_id: str, event: str, data: dict[str, Any]) -> None:
    rec = _batch_progress.get(batch_id)
    if rec is None:
        return
    rec["events"].append({"event": event, "data": data})


def _prune_stale_batches() -> None:
    """Drop finished batches older than the retention window."""
    now = time.time()
    stale: list[str] = []
    for bid, rec in _batch_progress.items():
        finished_raw = rec.get("finished_at")
        if not finished_raw:
            continue
        try:
            finished_dt = datetime.fromisoformat(finished_raw)
        except ValueError:
            continue
        if finished_dt.tzinfo is None:
            finished_dt = finished_dt.replace(tzinfo=timezone.utc)
        age = now - finished_dt.timestamp()
        if age > _BATCH_RETENTION_SECONDS:
            stale.append(bid)
    for bid in stale:
        _batch_progress.pop(bid, None)


async def _run_batch_with_progress(
    batch_id: str,
    tickers: list[str],
    force: bool,
) -> None:
    """Background worker: run each ticker and update progress state."""
    rec = _batch_progress.get(batch_id)
    if rec is None:
        return
    analysis_date: str = date.today().isoformat()

    def _running() -> int:
        """Compute running count: everything not yet completed or failed."""
        return rec["total"] - rec["completed"] - rec["failed"]

    def _emit_progress() -> None:
        _append_event(
            batch_id,
            "progress",
            {
                "total": rec["total"],
                "completed": rec["completed"],
                "failed": rec["failed"],
                "running": _running(),
                "last_ticker": rec["last_ticker"],
                "last_signal": rec["last_signal"],
            },
        )

    async def _one(ticker: str) -> None:
        rec["last_ticker"] = ticker
        _append_event(batch_id, "ticker_start", {"ticker": ticker})

        def on_stage(event_type: str, data: dict) -> None:
            _append_event(
                batch_id, "ticker_stage",
                {"ticker": ticker, "stage": event_type, **(data or {})},
            )

        try:
            item = await _run_one(
                ticker, analysis_date, force=force, on_event=on_stage,
            )
            item_dict = item.model_dump(mode="json")
            rec["results"].append(item_dict)
            rec["last_signal"] = item.signal
            rec["total_cost_usd"] = float(rec.get("total_cost_usd", 0.0)) + float(
                item.cost_usd or 0.0
            )
            is_error = any(
                isinstance(g, str) and g.startswith("pipeline_error")
                for g in item.data_gaps
            )
            if is_error:
                rec["failed"] += 1
            else:
                rec["completed"] += 1
            _append_event(
                batch_id,
                "ticker_done",
                {
                    "ticker": ticker,
                    "signal": item.signal,
                    "conviction": item.conviction,
                    "cost_usd": float(item.cost_usd or 0.0),
                    "cached": bool(item.cached),
                },
            )
        except asyncio.TimeoutError:
            logger.warning("batch %s ticker %s timed out after %ds", batch_id, ticker, _PIPELINE_TIMEOUT_SECONDS)
            rec["failed"] += 1
            _append_event(
                batch_id,
                "ticker_done",
                {"ticker": ticker, "signal": "HOLD", "error": f"timeout after {_PIPELINE_TIMEOUT_SECONDS}s"},
            )
        except Exception as exc:  # noqa: BLE001 - never let one ticker kill the batch
            logger.exception("batch %s ticker %s failed", batch_id, ticker)
            rec["failed"] += 1
            _append_event(
                batch_id,
                "ticker_done",
                {"ticker": ticker, "signal": "HOLD", "error": str(exc)},
            )
        finally:
            _emit_progress()

    try:
        await asyncio.gather(*(_one(t) for t in tickers))
        rec["status"] = "complete"
    except Exception as exc:  # noqa: BLE001
        logger.exception("batch %s crashed", batch_id)
        rec["status"] = "failed"
        _append_event(batch_id, "error", {"message": str(exc)})
    finally:
        rec["finished_at"] = datetime.now(timezone.utc).isoformat()
        _append_event(
            batch_id,
            "complete",
            {
                "total_completed": rec["completed"],
                "total_failed": rec["failed"],
                "total_cost_usd": float(rec.get("total_cost_usd", 0.0)),
            },
        )
        _prune_stale_batches()


@router.post("/signals/batch/start")
async def start_batch(body: dict[str, Any]) -> dict[str, Any]:
    """Kick off a batch run in the background and return a ``batch_id``.

    Request body::

        {"tickers": ["AAPL", "MSFT", ...], "force": false}
    """
    tickers_raw = body.get("tickers") or []
    if not isinstance(tickers_raw, list):
        raise HTTPException(
            status_code=422, detail="'tickers' must be a list of symbols"
        )
    cleaned = _clean_tickers([str(t) for t in tickers_raw])
    if not cleaned:
        raise HTTPException(
            status_code=422, detail="'tickers' must contain at least one symbol"
        )
    force = bool(body.get("force", False))

    batch_id = uuid.uuid4().hex[:12]
    _batch_progress[batch_id] = _new_progress_record(len(cleaned))
    _append_event(
        batch_id,
        "progress",
        {
            "total": len(cleaned),
            "completed": 0,
            "failed": 0,
            "running": 0,
        },
    )
    asyncio.create_task(_run_batch_with_progress(batch_id, cleaned, force))
    return {"batch_id": batch_id, "total": len(cleaned)}


@router.get("/signals/batch/{batch_id}/status")
async def get_batch_status(batch_id: str) -> dict[str, Any]:
    """Return a snapshot of the current batch progress (JSON poll fallback)."""
    rec = _batch_progress.get(batch_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="batch_id not found")
    return {
        "batch_id": batch_id,
        "total": rec["total"],
        "completed": rec["completed"],
        "failed": rec["failed"],
        "running": rec["total"] - rec["completed"] - rec["failed"],
        "status": rec["status"],
        "last_ticker": rec.get("last_ticker"),
        "last_signal": rec.get("last_signal"),
        "total_cost_usd": float(rec.get("total_cost_usd", 0.0)),
        "started_at": rec.get("started_at"),
        "finished_at": rec.get("finished_at"),
        "results": list(rec.get("results", [])),
    }


@router.get("/signals/batch/{batch_id}/stream")
async def stream_batch_progress(batch_id: str) -> EventSourceResponse:
    """Server-Sent Events stream of live batch progress.

    Events emitted:

    - ``progress`` -- ``{completed, failed, running, total, last_ticker, last_signal}``
    - ``ticker_start`` -- ``{ticker}``
    - ``ticker_done`` -- ``{ticker, signal, conviction, cost_usd, cached}``
    - ``complete`` -- ``{total_completed, total_failed, total_cost_usd}``
    - ``error`` -- ``{message}`` (fatal batch-level error)
    """
    if batch_id not in _batch_progress:
        raise HTTPException(status_code=404, detail="batch_id not found")

    async def _event_generator():
        cursor = 0
        while True:
            rec = _batch_progress.get(batch_id)
            if rec is None:
                return
            events = rec.get("events", [])
            while cursor < len(events):
                evt = events[cursor]
                cursor += 1
                yield {
                    "event": evt["event"],
                    "data": _json.dumps(
                        evt["data"], default=str, separators=(",", ":")
                    ),
                }
                if evt["event"] in ("complete", "error"):
                    return
            if rec.get("status") in ("complete", "failed") and cursor >= len(
                rec.get("events", [])
            ):
                return
            await asyncio.sleep(0.2)

    return EventSourceResponse(_event_generator())
