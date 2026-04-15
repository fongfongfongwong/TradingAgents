"""Databento real-time and historical market data connector.

Provides real-time OHLCV bars (1s / 1m granularity) via the Databento Live
streaming API and historical bars via the Historical API.  Uses the EQUS.MINI
dataset which includes pre-market / after-hours data and requires no exchange
authorization fee.

API key: set ``DATABENTO_API_KEY`` in environment or ``.env``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

# Databento fixed-point price divisor for EQUS.MINI
_PRICE_SCALE: float = 1e9

# In-memory price snapshot cache: {ticker: {last, open, high, low, close, volume, change_pct, ts}}
_price_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()

# Background streaming thread
_stream_thread: threading.Thread | None = None
_stream_running = False


def _get_api_key() -> str:
    """Resolve Databento API key from environment."""
    key = os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        raise ConnectorError(
            "DATABENTO_API_KEY not set. "
            "Export it or add to .env before using the Databento connector."
        )
    return key


def get_price_snapshot(ticker: str) -> dict[str, Any] | None:
    """Return the latest cached price snapshot for *ticker*, or ``None``."""
    with _cache_lock:
        return _price_cache.get(ticker.upper())


def get_all_snapshots() -> dict[str, dict[str, Any]]:
    """Return a copy of the full price snapshot cache."""
    with _cache_lock:
        return dict(_price_cache)


def _run_live_stream(symbols: list[str], schema: str = "ohlcv-1m") -> None:
    """Background thread: subscribe to Databento Live and update _price_cache."""
    global _stream_running
    try:
        import databento as db
    except ImportError:
        logger.error("databento package not installed — pip install databento")
        _stream_running = False
        return

    api_key = _get_api_key()
    _stream_running = True
    logger.info("Databento live stream starting for %s (schema=%s)", symbols, schema)

    while _stream_running:
        try:
            client = db.Live(key=api_key)
            client.subscribe(
                dataset="EQUS.MINI",
                schema=schema,
                symbols=symbols,
                stype_in="raw_symbol",
            )

            symbol_map: dict[int, str] = {}

            for record in client:
                if not _stream_running:
                    break

                if isinstance(record, db.SymbolMappingMsg):
                    symbol_map[record.instrument_id] = record.stype_in_symbol
                    continue

                if isinstance(record, db.ErrorMsg):
                    logger.warning("Databento stream error: %s", record)
                    continue

                if not isinstance(record, db.OHLCVMsg):
                    continue

                ticker = symbol_map.get(record.instrument_id)
                if ticker is None:
                    continue

                o = record.open / _PRICE_SCALE
                h = record.high / _PRICE_SCALE
                l = record.low / _PRICE_SCALE
                c = record.close / _PRICE_SCALE
                v = record.volume
                ts = datetime.fromtimestamp(
                    record.ts_event / 1e9, tz=timezone.utc
                ).isoformat()

                with _cache_lock:
                    prev = _price_cache.get(ticker)
                    prev_close = prev["close"] if prev else c
                    change_pct = ((c - prev_close) / prev_close * 100) if prev_close else 0.0

                    _price_cache[ticker] = {
                        "last": c,
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": v,
                        "change_pct": round(change_pct, 3),
                        "ts": ts,
                        "source": "databento",
                    }

        except Exception:
            logger.exception("Databento stream disconnected — reconnecting in 5s")
            time.sleep(5)

    logger.info("Databento live stream stopped")


def start_live_stream(symbols: list[str], schema: str = "ohlcv-1m") -> None:
    """Start the background streaming thread (idempotent)."""
    global _stream_thread
    if _stream_thread is not None and _stream_thread.is_alive():
        logger.debug("Databento stream already running")
        return

    _stream_thread = threading.Thread(
        target=_run_live_stream,
        args=(symbols, schema),
        daemon=True,
        name="databento-live",
    )
    _stream_thread.start()


def stop_live_stream() -> None:
    """Signal the background thread to stop."""
    global _stream_running
    _stream_running = False


class DatabentoConnector(BaseConnector):
    """Connector for Databento real-time and historical market data.

    Tier 2 — requires a paid API key.  Provides sub-second OHLCV bars
    for US equities via the EQUS.MINI dataset.
    """

    def __init__(self, rate_limit: int = 200, rate_period: float = 60.0):
        super().__init__(rate_limit=rate_limit, rate_period=rate_period)

    @property
    def name(self) -> str:
        return "databento"

    @property
    def tier(self) -> int:
        return 2

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.MARKET_DATA]

    @property
    def probe_data_type(self) -> str:
        return "ohlcv"

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        """Validate that the API key is present."""
        _get_api_key()  # raises ConnectorError if missing
        self._connected = True
        logger.info("Databento connector validated API key")

    # -- fetch dispatch ---------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "ohlcv")
        dispatch = {
            "ohlcv": self._fetch_ohlcv,
            "snapshot": self._fetch_snapshot,
            "historical": self._fetch_historical,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    def _fetch_snapshot(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Return the latest cached price from the live stream."""
        snap = get_price_snapshot(ticker)
        if snap is None:
            raise ConnectorError(
                f"No live snapshot for '{ticker}'. "
                "Ensure the Databento live stream is running."
            )
        return {"ticker": ticker, "data": snap, "source": "databento"}

    def _fetch_ohlcv(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Probe-compatible: try snapshot first, then one-shot historical."""
        snap = get_price_snapshot(ticker)
        if snap is not None:
            return {"ticker": ticker, "data": snap, "source": "databento"}
        return self._fetch_historical(ticker, params)

    def _fetch_historical(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch historical bars via Databento Historical API."""
        try:
            import databento as db
        except ImportError as exc:
            raise ConnectorError("databento package not installed") from exc

        api_key = _get_api_key()
        schema = params.get("schema", "ohlcv-1m")
        start = params.get("start", "2026-04-04T13:30")
        end = params.get("end")

        try:
            client = db.Historical(key=api_key)
            data = client.timeseries.get_range(
                dataset="EQUS.MINI",
                symbols=[ticker],
                schema=schema,
                start=start,
                end=end,
                stype_in="raw_symbol",
            )
            df = data.to_df()
        except Exception as exc:
            raise ConnectorError(f"Databento historical fetch failed: {exc}") from exc

        if df.empty:
            return {"ticker": ticker, "data": [], "source": "databento"}

        records = []
        for _, row in df.iterrows():
            records.append({
                "time": str(row.name),
                "open": float(row["open"]) / _PRICE_SCALE,
                "high": float(row["high"]) / _PRICE_SCALE,
                "low": float(row["low"]) / _PRICE_SCALE,
                "close": float(row["close"]) / _PRICE_SCALE,
                "volume": int(row["volume"]),
            })

        return {"ticker": ticker, "data": records, "source": "databento"}
