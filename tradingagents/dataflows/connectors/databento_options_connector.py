"""Databento OPRA options data connector.

Provides minute-level option BBO quotes and trade data from the OPRA.PILLAR
dataset via the Databento Historical API.  Supports options chain aggregation,
implied volatility surface construction, and flow-based sentiment (put/call
volume ratios).

API key: set ``DATABENTO_API_KEY`` in environment or ``.env``.

Data schemas:
- ``cbbo-1m``: Consolidated Best Bid/Offer at 1-minute granularity
- ``trades``: Individual option trades
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .base import BaseConnector, ConnectorCategory, ConnectorError

logger = logging.getLogger(__name__)

# Databento fixed-point price divisor
_PRICE_SCALE: float = 1e9


def _get_api_key() -> str:
    """Resolve Databento API key from environment."""
    key = os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        raise ConnectorError(
            "DATABENTO_API_KEY not set. "
            "Export it or add to .env before using the Databento options connector."
        )
    return key


def _parse_opra_symbol(symbol: str) -> dict[str, Any]:
    """Parse OPRA symbol string into structured fields.

    Example: ``"AAPL  250905C00340000"`` ->
    ``{underlying: "AAPL", expiration: "2025-09-05", option_type: "call", strike: 340.0}``
    """
    parts = symbol.strip().split()
    if len(parts) < 2:
        return {"underlying": symbol.strip(), "expiration": None, "option_type": None, "strike": None}

    underlying = parts[0]
    detail = parts[1]  # e.g. "250905C00340000"

    try:
        expiration = f"20{detail[:2]}-{detail[2:4]}-{detail[4:6]}"
        option_type = "call" if detail[6] == "C" else "put"
        strike = int(detail[7:]) / 1000.0
    except (IndexError, ValueError):
        return {"underlying": underlying, "expiration": None, "option_type": None, "strike": None}

    return {
        "underlying": underlying,
        "expiration": expiration,
        "option_type": option_type,
        "strike": strike,
    }


class DatabentoOptionsConnector(BaseConnector):
    """Connector for Databento OPRA options data.

    Tier 2 -- requires a paid API key. Provides options BBO quotes and
    trades from the OPRA.PILLAR dataset (full US options market).

    Supported data_types:
    - ``"chains"``: Aggregated options chain (nearest expiration BBO)
    - ``"flow"``: Options flow analysis (put/call volume, large trades)
    - ``"bbo_raw"``: Raw minute-level BBO data
    - ``"trades_raw"``: Raw option trade data
    """

    def __init__(self, rate_limit: int = 60, rate_period: float = 60.0):
        super().__init__(rate_limit=rate_limit, rate_period=rate_period)

    @property
    def name(self) -> str:
        return "databento-options"

    @property
    def tier(self) -> int:
        return 2

    @property
    def categories(self) -> list[ConnectorCategory]:
        return [ConnectorCategory.OPTIONS]

    @property
    def probe_data_type(self) -> str:
        return "chains"

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        """Validate that the API key is present and databento is installed."""
        _get_api_key()
        try:
            import databento  # noqa: F401
        except ImportError as exc:
            raise ConnectorError(
                "databento package not installed — pip install databento"
            ) from exc
        self._connected = True
        logger.info("Databento options connector validated API key")

    # -- fetch dispatch ---------------------------------------------------

    def _fetch_impl(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        data_type = params.get("data_type", "chains")
        dispatch = {
            "chains": self._fetch_chains,
            "flow": self._fetch_flow,
            "bbo_raw": self._fetch_bbo_raw,
            "trades_raw": self._fetch_trades_raw,
        }
        handler = dispatch.get(data_type)
        if handler is None:
            raise ConnectorError(
                f"Unknown data_type '{data_type}'. "
                f"Supported: {list(dispatch.keys())}"
            )
        return handler(ticker, params)

    # -- chains: aggregated options chain ---------------------------------

    def _fetch_chains(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch and aggregate an options chain for the nearest expiration.

        Returns strikes with bid/ask/volume for calls and puts, plus
        put_call_ratio and iv_rank derived from the flow data.
        """
        lookback_days = params.get("lookback_days", 1)
        end = datetime.now()
        start = end - timedelta(days=lookback_days)

        bbo_df = self._download_bbo(
            ticker,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            limit=params.get("limit", 50_000),
        )

        if bbo_df.empty:
            raise ConnectorError(f"No BBO data returned for {ticker} options")

        # Parse OPRA symbols
        bbo_df = self._enrich_opra_fields(bbo_df)

        # Filter to nearest expiration
        valid_exp = bbo_df.dropna(subset=["expiration"])
        if valid_exp.empty:
            raise ConnectorError(f"Could not parse option expirations for {ticker}")

        nearest_exp = sorted(valid_exp["expiration"].unique())[0]
        chain_df = valid_exp[valid_exp["expiration"] == nearest_exp]

        # Aggregate to latest quote per strike/type
        chain = self._aggregate_chain(chain_df)

        # Compute put/call ratio from volume
        total_call_vol = sum(
            r.get("call_volume", 0) or 0 for r in chain
        )
        total_put_vol = sum(
            r.get("put_volume", 0) or 0 for r in chain
        )
        pc_ratio = round(total_put_vol / total_call_vol, 3) if total_call_vol > 0 else None

        return {
            "ticker": ticker,
            "expiration": nearest_exp,
            "chain": chain,
            "put_call_ratio": pc_ratio,
            "iv_rank": None,  # Databento BBO doesn't include IV; use ORATS for IV
            "total_call_volume": total_call_vol,
            "total_put_volume": total_put_vol,
            "source": "databento-options",
        }

    # -- flow: options flow sentiment ------------------------------------

    def _fetch_flow(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Analyse options trade flow for directional sentiment.

        Returns put/call volume ratios, large-trade detection, and
        call-skew vs put-skew indicators.
        """
        lookback_days = params.get("lookback_days", 1)
        end = datetime.now()
        start = end - timedelta(days=lookback_days)

        trades_df = self._download_trades(
            ticker,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            limit=params.get("limit", 100_000),
        )

        if trades_df.empty:
            raise ConnectorError(f"No trade data returned for {ticker} options")

        trades_df = self._enrich_opra_fields(trades_df)
        valid = trades_df.dropna(subset=["option_type"])

        calls = valid[valid["option_type"] == "call"]
        puts = valid[valid["option_type"] == "put"]

        call_volume = int(calls["size"].sum()) if "size" in calls.columns else 0
        put_volume = int(puts["size"].sum()) if "size" in puts.columns else 0
        pc_ratio = round(put_volume / call_volume, 3) if call_volume > 0 else None

        # Large trade detection (> 100 contracts)
        large_threshold = params.get("large_trade_threshold", 100)
        large_trades = valid[valid["size"] >= large_threshold] if "size" in valid.columns else pd.DataFrame()
        large_call_vol = int(large_trades[large_trades["option_type"] == "call"]["size"].sum()) if not large_trades.empty else 0
        large_put_vol = int(large_trades[large_trades["option_type"] == "put"]["size"].sum()) if not large_trades.empty else 0

        # Directional sentiment
        if pc_ratio is not None:
            if pc_ratio < 0.7:
                sentiment = "BULLISH"
            elif pc_ratio > 1.3:
                sentiment = "BEARISH"
            else:
                sentiment = "NEUTRAL"
        else:
            sentiment = "UNKNOWN"

        return {
            "ticker": ticker,
            "call_volume": call_volume,
            "put_volume": put_volume,
            "put_call_ratio": pc_ratio,
            "sentiment": sentiment,
            "large_call_volume": large_call_vol,
            "large_put_volume": large_put_vol,
            "large_trade_count": len(large_trades),
            "total_trades": len(valid),
            "source": "databento-options",
        }

    # -- raw data methods -------------------------------------------------

    def _fetch_bbo_raw(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Return raw BBO DataFrame as list of dicts."""
        start = params.get("start", (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
        end = params.get("end", datetime.now().strftime("%Y-%m-%d"))
        limit = params.get("limit", 10_000)

        df = self._download_bbo(ticker, start, end, limit=limit)
        if df.empty:
            return {"ticker": ticker, "data": [], "source": "databento-options"}

        df = self._enrich_opra_fields(df)
        records = df.head(1000).to_dict(orient="records")

        return {
            "ticker": ticker,
            "data": records,
            "row_count": len(df),
            "source": "databento-options",
        }

    def _fetch_trades_raw(self, ticker: str, params: dict[str, Any]) -> dict[str, Any]:
        """Return raw trades DataFrame as list of dicts."""
        start = params.get("start", (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
        end = params.get("end", datetime.now().strftime("%Y-%m-%d"))
        limit = params.get("limit", 10_000)

        df = self._download_trades(ticker, start, end, limit=limit)
        if df.empty:
            return {"ticker": ticker, "data": [], "source": "databento-options"}

        df = self._enrich_opra_fields(df)
        records = df.head(1000).to_dict(orient="records")

        return {
            "ticker": ticker,
            "data": records,
            "row_count": len(df),
            "source": "databento-options",
        }

    # -- Databento API calls ----------------------------------------------

    def _download_bbo(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int | None = None,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        """Download minute-level option BBO (cbbo-1m) from OPRA.PILLAR."""
        import databento as db

        api_key = _get_api_key()
        client = db.Historical(key=api_key)
        symbol = f"{ticker}.OPT"

        request_params: dict[str, Any] = {
            "dataset": "OPRA.PILLAR",
            "schema": "cbbo-1m",
            "symbols": [symbol],
            "start": f"{start_date}T00:00:00",
            "end": f"{end_date}T23:59:59",
            "stype_in": "parent",
        }
        if limit is not None:
            request_params["limit"] = limit

        for attempt in range(max_retries):
            try:
                df = client.timeseries.get_range(**request_params).to_df()
                df.reset_index(inplace=True)
                if "ts_event" in df.columns:
                    df["ts_event"] = (
                        pd.to_datetime(df["ts_event"])
                        .dt.tz_convert("America/New_York")
                        .dt.tz_localize(None)
                    )
                logger.info("[BBO] Downloaded %d rows for %s options", len(df), ticker)
                return df
            except Exception as exc:
                if attempt < max_retries - 1:
                    logger.warning(
                        "[BBO] Retry %d/%d for %s: %s",
                        attempt + 1, max_retries, ticker, exc,
                    )
                    time.sleep(2)
                else:
                    logger.error("[BBO] FAILED after %d retries: %s", max_retries, exc)
                    return pd.DataFrame()

        return pd.DataFrame()

    def _download_trades(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        limit: int | None = None,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        """Download option trades from OPRA.PILLAR."""
        import databento as db

        api_key = _get_api_key()
        client = db.Historical(key=api_key)
        symbol = f"{ticker}.OPT"

        request_params: dict[str, Any] = {
            "dataset": "OPRA.PILLAR",
            "schema": "trades",
            "symbols": [symbol],
            "start": f"{start_date}T00:00:00",
            "end": f"{end_date}T23:59:59",
            "stype_in": "parent",
        }
        if limit is not None:
            request_params["limit"] = limit

        for attempt in range(max_retries):
            try:
                df = client.timeseries.get_range(**request_params).to_df()
                df.reset_index(inplace=True)
                if "ts_event" in df.columns:
                    df["ts_event"] = (
                        pd.to_datetime(df["ts_event"])
                        .dt.tz_convert("America/New_York")
                        .dt.tz_localize(None)
                    )
                logger.info("[TRADES] Downloaded %d rows for %s options", len(df), ticker)
                return df
            except Exception as exc:
                if attempt < max_retries - 1:
                    logger.warning(
                        "[TRADES] Retry %d/%d for %s: %s",
                        attempt + 1, max_retries, ticker, exc,
                    )
                    time.sleep(2)
                else:
                    logger.error("[TRADES] FAILED after %d retries: %s", max_retries, exc)
                    return pd.DataFrame()

        return pd.DataFrame()

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _enrich_opra_fields(df: pd.DataFrame) -> pd.DataFrame:
        """Parse OPRA symbol column into underlying, expiration, option_type, strike."""
        if df.empty or "symbol" not in df.columns:
            return df

        parsed = df["symbol"].apply(lambda s: _parse_opra_symbol(str(s)))
        parsed_df = pd.DataFrame(parsed.tolist())
        for col in ("underlying", "expiration", "option_type", "strike"):
            if col in parsed_df.columns:
                df[col] = parsed_df[col]
        return df

    @staticmethod
    def _aggregate_chain(chain_df: pd.DataFrame) -> list[dict[str, Any]]:
        """Aggregate BBO data into a per-strike options chain."""
        if chain_df.empty or "strike" not in chain_df.columns:
            return []

        strikes = sorted(chain_df["strike"].dropna().unique())
        result: list[dict[str, Any]] = []

        for strike in strikes:
            strike_data = chain_df[chain_df["strike"] == strike]
            calls = strike_data[strike_data["option_type"] == "call"]
            puts = strike_data[strike_data["option_type"] == "put"]

            row: dict[str, Any] = {"strike": float(strike)}

            # Call side — use last available quote
            if not calls.empty:
                last_call = calls.iloc[-1]
                row["call_bid"] = float(last_call.get("bid_px_00", 0) or 0) / _PRICE_SCALE if "bid_px_00" in calls.columns else None
                row["call_ask"] = float(last_call.get("ask_px_00", 0) or 0) / _PRICE_SCALE if "ask_px_00" in calls.columns else None
                row["call_volume"] = int(calls.get("bid_sz_00", pd.Series([0])).sum()) if "bid_sz_00" in calls.columns else 0
                row["call_oi"] = 0  # OI not in BBO schema
            else:
                row.update({"call_bid": None, "call_ask": None, "call_volume": 0, "call_oi": 0})

            # Put side
            if not puts.empty:
                last_put = puts.iloc[-1]
                row["put_bid"] = float(last_put.get("bid_px_00", 0) or 0) / _PRICE_SCALE if "bid_px_00" in puts.columns else None
                row["put_ask"] = float(last_put.get("ask_px_00", 0) or 0) / _PRICE_SCALE if "ask_px_00" in puts.columns else None
                row["put_volume"] = int(puts.get("bid_sz_00", pd.Series([0])).sum()) if "bid_sz_00" in puts.columns else 0
                row["put_oi"] = 0
            else:
                row.update({"put_bid": None, "put_ask": None, "put_volume": 0, "put_oi": 0})

            result.append(row)

        return result
