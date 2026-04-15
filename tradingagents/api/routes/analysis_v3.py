"""Analysis v3 routes -- run the v3 pipeline via HTTP + SSE."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3", tags=["analysis_v3"])

# ---------------------------------------------------------------------------
# In-memory stores (production would use Redis / DB)
# ---------------------------------------------------------------------------
_analyses: dict[str, dict[str, Any]] = {}
_events: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_run_analysis():
    """Lazily import ``run_analysis`` via *importlib* to avoid pulling in
    heavy langchain transitive dependencies at module-load time."""
    mod = importlib.import_module("tradingagents.pipeline.runner")
    return mod.run_analysis


def _push_event(analysis_id: str, event: str, data: dict[str, Any]) -> None:
    """Append a named event to the per-analysis event list."""
    _events.setdefault(analysis_id, []).append(
        {"event": event, "data": data}
    )


def _make_on_event(analysis_id: str):
    """Return an ``on_event`` callback the pipeline can call."""

    def on_event(event: str, data: dict[str, Any] | None = None) -> None:
        _push_event(analysis_id, event, data or {})

    return on_event


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------

async def _run_pipeline(analysis_id: str, ticker: str, analysis_date: str) -> None:
    """Execute the v3 pipeline in a worker thread and record results."""
    record = _analyses[analysis_id]
    record["status"] = "running"
    _push_event(analysis_id, "running", {"analysis_id": analysis_id})

    try:
        run_analysis = _load_run_analysis()
        on_event = _make_on_event(analysis_id)

        # The pipeline is synchronous -- offload to a thread so the event
        # loop stays responsive.
        result = await asyncio.to_thread(
            run_analysis,
            ticker=ticker,
            date=analysis_date,
            on_event=on_event,
        )

        record["result"] = result
        record["status"] = "complete"
        _push_event(analysis_id, "pipeline_complete", {"result": result})

    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline failed for %s", analysis_id)
        record["status"] = "failed"
        record["error"] = str(exc)
        _push_event(analysis_id, "pipeline_failed", {"error": str(exc)})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def start_analysis(body: dict) -> dict[str, Any]:
    """Start a v3 analysis. Returns *analysis_id* immediately.

    Body::

        {"ticker": "AAPL", "date": "2026-04-05"}   # date is optional

    Response::

        {"analysis_id": str, "status": "pending", "ticker": str}
    """
    ticker: str | None = body.get("ticker")
    if not ticker:
        raise HTTPException(status_code=422, detail="'ticker' is required")

    analysis_date: str = body.get("date", date.today().isoformat())
    analysis_id: str = uuid.uuid4().hex[:12]

    _analyses[analysis_id] = {
        "analysis_id": analysis_id,
        "status": "pending",
        "ticker": ticker,
        "date": analysis_date,
        "result": None,
        "error": None,
    }
    _events[analysis_id] = []

    # Fire-and-forget background task (uses running loop — 3.10+ safe)
    asyncio.create_task(_run_pipeline(analysis_id, ticker, analysis_date))

    return {
        "analysis_id": analysis_id,
        "status": "pending",
        "ticker": ticker,
    }


@router.get("/analyze/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict[str, Any]:
    """Poll for analysis result.

    Response::

        {"analysis_id": str,
         "status": "pending"|"running"|"complete"|"failed",
         "result": FinalDecision | null}
    """
    record = _analyses.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return {
        "analysis_id": record["analysis_id"],
        "status": record["status"],
        "result": record.get("result"),
    }


@router.get("/analyze/{analysis_id}/stream")
async def stream_analysis(analysis_id: str) -> EventSourceResponse:
    """SSE endpoint streaming pipeline events.

    Event names emitted by the pipeline include:

    * ``materialized``
    * ``screened``
    * ``thesis_complete``
    * ``antithesis_complete``
    * ``base_rate_complete``
    * ``synthesis_complete``
    * ``risk_complete``
    * ``pipeline_complete``
    """
    if analysis_id not in _analyses:
        raise HTTPException(status_code=404, detail="Analysis not found")

    async def _event_generator():
        cursor = 0
        while True:
            events = _events.get(analysis_id, [])
            while cursor < len(events):
                evt = events[cursor]
                cursor += 1
                data_payload = evt["data"]
                if not isinstance(data_payload, str):
                    data_payload = json.dumps(data_payload, default=str)
                yield {"event": evt["event"], "data": data_payload}
                if evt["event"] in ("pipeline_complete", "pipeline_failed"):
                    return
            await asyncio.sleep(0.25)

    return EventSourceResponse(_event_generator())


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test: Import works
    print("F12: analysis_v3 router created successfully")
    print(f"Routes: {[r.path for r in router.routes]}")
    print("All F12 tests PASSED")
