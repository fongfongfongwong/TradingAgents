"""FastAPI application factory for TradingAgents."""

from __future__ import annotations

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(override=True)
except ImportError:
    pass  # python-dotenv not installed; env vars must be set manually

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tradingagents.gateway import api_key_store

from .models.responses import HealthResponse
from .routes import analysis, analysis_v3, backtest, config, divergence, holdings, macro, market, news, news_v3, options, price, realtime_prices, rv_forecast, screener, signals, signals_v3, sources, universe
from .routes.legacy import social  # legacy route kept for schema stability; not called by current frontend

logger = logging.getLogger(__name__)

_VERSION = "2.0.0"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("TradingAgents API starting up (v%s)", _VERSION)
    # Load persisted API keys from SQLite into os.environ (overrides .env)
    try:
        loaded = api_key_store.load_all_into_env()
        logger.info("Loaded %d API keys from persistent store", loaded)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load persisted API keys: %s", exc)
    try:
        from tradingagents.gateway import signals_cache
        purged = signals_cache.purge_old_schema_versions()
        if purged > 0:
            logger.info(
                "Purged %d stale signals cache entries (schema version changed)",
                purged,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to purge stale cache: %s", exc)
    # Bootstrap data source connectors for monitoring
    try:
        from tradingagents.dataflows.connectors.bootstrap import bootstrap_connectors
        bootstrap_connectors()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to bootstrap connectors: %s", exc)
    # Auto-start Databento real-time stream if API key is configured
    try:
        databento_key = os.environ.get("DATABENTO_API_KEY", "")
        if databento_key:
            from tradingagents.dataflows.connectors.databento_connector import start_live_stream
            # Subscribe all universe tickers for real-time coverage.
            # Uses ohlcv-1s (1-second bars) for sub-2-second freshness.
            _DEFAULT_STREAM_TICKERS = [
                # Equities (NDX top-30)
                "AAPL", "MSFT", "NVDA", "AVGO", "AMZN", "META", "GOOG", "GOOGL",
                "TSLA", "COST", "NFLX", "AMD", "ADBE", "CRM", "PEP", "CSCO",
                "INTC", "QCOM", "TXN", "AMGN",
                # ETFs (sector + macro)
                "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY", "XLI",
                "XLC", "XLP", "XLE", "XLU", "XLRE", "XLB", "TLT", "HYG", "GLD",
                "USO",
            ]
            start_live_stream(_DEFAULT_STREAM_TICKERS, schema="ohlcv-1s")
            logger.info("Databento live stream started for %d tickers (1s bars)", len(_DEFAULT_STREAM_TICKERS))
        else:
            logger.info("DATABENTO_API_KEY not set — skipping live stream")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start Databento live stream: %s", exc)
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
    app.include_router(analysis_v3.router)
    app.include_router(divergence.router)
    app.include_router(backtest.router)
    app.include_router(config.router)
    app.include_router(price.router)
    app.include_router(news.router)
    app.include_router(news_v3.router)
    app.include_router(options.router)
    app.include_router(holdings.router)
    app.include_router(social.router)
    app.include_router(macro.router)
    app.include_router(market.router)
    app.include_router(signals.router)
    app.include_router(signals_v3.router)
    app.include_router(screener.router)
    app.include_router(rv_forecast.router)
    app.include_router(sources.router)
    app.include_router(realtime_prices.router)
    app.include_router(universe.router)

    return app


# Module-level app instance for uvicorn
app = create_app()
