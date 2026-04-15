"""Data source monitoring and probe endpoints.

GET /api/v3/sources/status       — All connector probe results (cached 60s)
GET /api/v3/sources/{name}/probe — Force-probe a single connector
GET /api/v3/sources/{name}/history — Recent probe history for trend charts
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from tradingagents.dataflows.connectors.probe import get_prober
from tradingagents.dataflows.connectors.registry import ConnectorRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/sources", tags=["sources"])


@router.get("/status")
async def get_sources_status(force: bool = False) -> list[dict[str, Any]]:
    """Return probe results for all registered connectors.

    Results are cached for 60s by the prober to avoid hammering APIs.
    Pass ``?force=true`` to bypass the cache.
    """
    prober = get_prober()
    try:
        results = prober.probe_all(force=force)
    except Exception as exc:
        logger.exception("Failed to probe all sources")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return [r.to_dict() for r in results]


@router.get("/coverage")
async def get_source_coverage() -> dict[str, Any]:
    """Return a category-to-connectors mapping for the coverage matrix.

    Response shape::

        {
            "categories": ["market_data", "news", ...],
            "connectors": [
                {
                    "name": "finnhub",
                    "tier": 1,
                    "status": "ok",
                    "categories": ["market_data", "news"],
                    "health_score": 85.0
                },
                ...
            ]
        }
    """
    registry = ConnectorRegistry()
    prober = get_prober()

    connectors_list: list[dict[str, Any]] = []
    categories_seen: set[str] = set()

    for conn in registry.list_all():
        cats = [c.value for c in conn.categories]
        categories_seen.update(cats)

        # Use cached probe if available
        try:
            result = prober.probe_one(conn.name, force=False)
            connectors_list.append({
                "name": conn.name,
                "tier": conn.tier,
                "status": result.status,
                "categories": cats,
                "health_score": round(result.health_score, 1),
            })
        except Exception:
            connectors_list.append({
                "name": conn.name,
                "tier": conn.tier,
                "status": "unknown",
                "categories": cats,
                "health_score": 0.0,
            })

    return {
        "categories": sorted(categories_seen),
        "connectors": connectors_list,
    }


@router.get("/{name}/probe")
async def probe_source(name: str) -> dict[str, Any]:
    """Force a fresh probe of a single data source connector."""
    registry = ConnectorRegistry()
    if name not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Connector '{name}' not found. Available: {registry.names}",
        )

    prober = get_prober()
    try:
        result = prober.probe_one(name, force=True)
    except Exception as exc:
        logger.exception("Failed to probe source '%s'", name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result.to_dict()


@router.get("/{name}/history")
async def get_source_history(name: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent probe history for a single connector (for trend charts)."""
    registry = ConnectorRegistry()
    if name not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Connector '{name}' not found. Available: {registry.names}",
        )

    prober = get_prober()
    return prober.get_history(name, limit=min(limit, 60))
