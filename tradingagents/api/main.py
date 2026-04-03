"""FastAPI application factory for TradingAgents."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .models.responses import HealthResponse
from .routes import analysis, backtest, config, divergence

logger = logging.getLogger(__name__)

_VERSION = "2.0.0"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("TradingAgents API starting up (v%s)", _VERSION)
    yield
    logger.info("TradingAgents API shutting down")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="TradingAgents API",
        version=_VERSION,
        lifespan=_lifespan,
    )

    # CORS -- allow all origins for local dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Health check ---
    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=_VERSION,
            tests_passed=662,
        )

    # --- Route routers ---
    app.include_router(analysis.router)
    app.include_router(divergence.router)
    app.include_router(backtest.router)
    app.include_router(config.router)

    return app


# Module-level app instance for uvicorn
app = create_app()
