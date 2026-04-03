"""Analysis routes -- trigger, poll, and stream analysis results."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..models.requests import AnalyzeRequest
from ..models.responses import AnalysisResponse

router = APIRouter(prefix="/api", tags=["analysis"])

# In-memory store for analysis jobs (production would use Redis / DB)
_analyses: dict[str, dict[str, Any]] = {}
_analysis_events: dict[str, list[dict[str, Any]]] = {}


@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    """Dashboard statistics."""
    completed = [a for a in _analyses.values() if a["status"] == "complete"]
    return {
        "analyses_today": len(_analyses),
        "analyses_total": len(_analyses),
        "active_agents": sum(1 for a in _analyses.values() if a["status"] == "running"),
        "avg_confidence": (
            sum(a["result"]["confidence"] for a in completed) / len(completed)
            if completed else 0
        ),
    }


@router.get("/analyses")
async def list_analyses(limit: int = 20) -> list[dict[str, Any]]:
    """List recent analyses."""
    items = list(_analyses.values())[-limit:]
    return [
        {
            "id": a["analysis_id"],
            "ticker": a["ticker"],
            "status": a["status"],
            "result": a.get("result"),
            "created_at": "2026-04-03T00:00:00Z",
        }
        for a in reversed(items)
    ]


@router.get("/analyses/{analysis_id}")
async def get_analysis_by_id(analysis_id: str) -> dict[str, Any]:
    """Get a single analysis by id."""
    record = _analyses.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {
        "id": record["analysis_id"],
        "ticker": record["ticker"],
        "status": record["status"],
        "result": record.get("result"),
        "created_at": "2026-04-03T00:00:00Z",
    }


@router.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    """Portfolio summary (paper trading)."""
    return {
        "cash": 100000.0,
        "total_value": 100000.0,
        "total_pnl": 0.0,
        "total_pnl_pct": 0.0,
        "positions": [],
    }


@router.post("/analyze", response_model=AnalysisResponse)
async def start_analysis(req: AnalyzeRequest) -> AnalysisResponse:
    """Trigger a new analysis run (async -- returns immediately)."""
    analysis_id = uuid.uuid4().hex[:12]
    _analyses[analysis_id] = {
        "analysis_id": analysis_id,
        "status": "pending",
        "ticker": req.ticker,
        "result": None,
        "request": req.model_dump(),
    }
    _analysis_events[analysis_id] = []

    # Fire-and-forget the background task
    asyncio.get_event_loop().create_task(_run_analysis(analysis_id, req))

    return AnalysisResponse(
        analysis_id=analysis_id,
        status="pending",
        ticker=req.ticker,
        result=None,
    )


@router.get("/analyze/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(analysis_id: str) -> AnalysisResponse:
    """Poll for analysis result."""
    record = _analyses.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return AnalysisResponse(
        analysis_id=record["analysis_id"],
        status=record["status"],
        ticker=record["ticker"],
        result=record["result"],
    )


@router.get("/analyze/{analysis_id}/stream")
async def stream_analysis(analysis_id: str) -> EventSourceResponse:
    """SSE endpoint streaming progress events for an analysis."""
    if analysis_id not in _analyses:
        raise HTTPException(status_code=404, detail="Analysis not found")

    async def _event_generator():
        cursor = 0
        while True:
            events = _analysis_events.get(analysis_id, [])
            while cursor < len(events):
                evt = events[cursor]
                cursor += 1
                yield {"event": evt["event"], "data": evt["data"]}
                if evt["event"] == "analysis_complete":
                    return
            await asyncio.sleep(0.2)

    return EventSourceResponse(_event_generator())


# ---- Background runner ----

async def _run_analysis(analysis_id: str, req: AnalyzeRequest) -> None:
    """Simulate an analysis pipeline with agent events."""
    record = _analyses[analysis_id]
    events = _analysis_events[analysis_id]
    record["status"] = "running"

    agent_names = {
        "market": "Market Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
        "divergence": "Divergence Analyst",
    }

    for analyst_key in req.selected_analysts:
        agent_name = agent_names.get(analyst_key, analyst_key.title() + " Analyst")
        events.append({"event": "agent_start", "data": {"agent": agent_name}})
        # Yield control so SSE consumers can pick up events
        await asyncio.sleep(0)
        events.append({"event": "agent_complete", "data": {"agent": agent_name}})
        await asyncio.sleep(0)

    result = {
        "ticker": req.ticker,
        "trade_date": req.trade_date,
        "decision": "HOLD",
        "confidence": 0.5,
        "analysts": req.selected_analysts,
    }
    record["result"] = result
    record["status"] = "complete"
    events.append({"event": "analysis_complete", "data": result})
