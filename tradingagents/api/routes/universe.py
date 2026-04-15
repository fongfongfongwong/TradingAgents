"""Universe endpoints: top volatile equities and ETFs.

Endpoint
--------
- ``GET /api/v3/universe/top-volatile`` -- returns the top N most volatile
  equities and ETFs ranked by predicted 1-day realized volatility.

Data flow:
1. Batch-download 1 month of daily OHLC for all 306 tickers via yfinance.
2. Compute Garman-Klass RV and 20-day rolling realized vol for each ticker.
3. If a trained HAR-RV Ridge model exists (horizon=1), run batch prediction
   to get ``predicted_rv_1d_pct``. Otherwise fall back to the most recent
   GK RV daily value (annualised percentage).
4. Sort descending, return top ``n_equity`` equities + top ``n_etf`` ETFs.
5. Cache the result in-process for 60 seconds.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/universe", tags=["universe"])

# ---------------------------------------------------------------------------
# In-process TTL cache
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS: float = 60.0
_CACHE_LOCK = asyncio.Lock()


def _cache_get(key: str) -> dict[str, Any] | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    stored_at, payload = entry
    if time.time() - stored_at > _CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: dict[str, Any]) -> None:
    _CACHE[key] = (time.time(), payload)


# ---------------------------------------------------------------------------
# Core computation (runs in thread via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _compute_gk_rv_daily(ohlc_df: pd.DataFrame) -> pd.Series:
    """Garman-Klass daily RV from OHLC columns (lowercase)."""
    o = ohlc_df["Open"].astype(float).replace(0, np.nan)
    h = ohlc_df["High"].astype(float)
    lo = ohlc_df["Low"].astype(float).replace(0, np.nan)
    c = ohlc_df["Close"].astype(float)
    log_hl = np.log(h / lo)
    log_co = np.log(c / o)
    gk_coef = 2.0 * np.log(2.0) - 1.0
    gk = 0.5 * log_hl**2 - gk_coef * log_co**2
    gk = gk.replace([np.inf, -np.inf], np.nan)
    gk_clamped = gk.where(gk > 0.0, other=0.0)
    return np.sqrt(gk_clamped)


def _load_har_rv_model() -> Any | None:
    """Attempt to load the HAR-RV Ridge model for horizon=1."""
    try:
        from tradingagents.models.har_rv_ridge import load_model
        return load_model(horizon=1)
    except Exception as exc:  # noqa: BLE001
        logger.debug("HAR-RV model load failed (expected if not trained): %s", exc)
        return None


def _compute_top_volatile(
    n_equity: int,
    n_etf: int,
) -> dict[str, Any]:
    """Batch-download OHLC, compute vol metrics, rank, and return payload."""
    import yfinance as yf

    from tradingagents.factors.clean_tickers import (
        CLEAN_ETF_TICKERS,
        CLEAN_STOCK_TICKERS,
    )

    all_tickers = list(CLEAN_STOCK_TICKERS) + list(CLEAN_ETF_TICKERS)
    equity_set = frozenset(CLEAN_STOCK_TICKERS)
    etf_set = frozenset(CLEAN_ETF_TICKERS)

    # Single batch download for all tickers
    raw = yf.download(
        tickers=all_tickers,
        period="1mo",
        group_by="ticker",
        threads=True,
        progress=False,
        timeout=30,
    )

    if raw is None or raw.empty:
        logger.warning("yfinance batch download returned empty data")
        return _empty_response(len(CLEAN_STOCK_TICKERS), len(CLEAN_ETF_TICKERS))

    # Build per-ticker volatility records
    records: list[dict[str, Any]] = []

    for ticker in all_tickers:
        try:
            # Extract single-ticker OHLC from multi-level columns
            if isinstance(raw.columns, pd.MultiIndex):
                try:
                    df = raw[ticker].dropna(how="all")
                except KeyError:
                    try:
                        df = raw.xs(ticker, axis=1, level=1, drop_level=True)
                    except KeyError:
                        continue
            else:
                # Single ticker fallback (shouldn't happen with 306 tickers)
                df = raw.dropna(how="all")

            if df is None or len(df) < 5:
                continue

            required_cols = {"Open", "High", "Low", "Close"}
            if not required_cols.issubset(set(df.columns)):
                continue

            gk_rv = _compute_gk_rv_daily(df)
            if gk_rv.empty or gk_rv.isna().all():
                continue

            # 20-day rolling realized vol (annualised %)
            rv_20d = gk_rv.rolling(window=20, min_periods=10).mean()
            latest_rv_20d = rv_20d.dropna().iloc[-1] if not rv_20d.dropna().empty else np.nan
            realized_vol_20d_pct = float(latest_rv_20d) * np.sqrt(252) * 100 if not np.isnan(latest_rv_20d) else None

            # Latest daily GK RV as fallback for predicted_rv_1d_pct
            latest_gk = gk_rv.dropna().iloc[-1] if not gk_rv.dropna().empty else np.nan
            predicted_rv_1d_pct = float(latest_gk) * np.sqrt(252) * 100 if not np.isnan(latest_gk) else None

            if predicted_rv_1d_pct is None:
                continue

            asset_type = "equity" if ticker in equity_set else "etf"
            records.append({
                "ticker": ticker,
                "predicted_rv_1d_pct": round(predicted_rv_1d_pct, 2),
                "realized_vol_20d_pct": round(realized_vol_20d_pct, 2) if realized_vol_20d_pct is not None else None,
                "asset_type": asset_type,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping ticker %s: %s", ticker, exc)
            continue

    # Attempt HAR-RV model prediction override
    model = _load_har_rv_model()
    if model is not None:
        logger.info("HAR-RV model loaded; overriding predicted_rv_1d_pct with model predictions")
        _apply_model_predictions(model, raw, records, all_tickers)

    # Split into equity / etf and sort
    equity_records = sorted(
        [r for r in records if r["asset_type"] == "equity"],
        key=lambda r: r.get("predicted_rv_1d_pct") or 0.0,
        reverse=True,
    )[:n_equity]

    etf_records = sorted(
        [r for r in records if r["asset_type"] == "etf"],
        key=lambda r: r.get("predicted_rv_1d_pct") or 0.0,
        reverse=True,
    )[:n_etf]

    # Assign ranks and remove internal asset_type field
    for i, rec in enumerate(equity_records, start=1):
        rec["rank"] = i
        rec.pop("asset_type", None)

    for i, rec in enumerate(etf_records, start=1):
        rec["rank"] = i
        rec.pop("asset_type", None)

    return {
        "equity": equity_records,
        "etf": etf_records,
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe_size": {
            "equity": len(CLEAN_STOCK_TICKERS),
            "etf": len(CLEAN_ETF_TICKERS),
        },
    }


def _apply_model_predictions(
    model: Any,
    raw: pd.DataFrame,
    records: list[dict[str, Any]],
    all_tickers: list[str],
) -> None:
    """Override predicted_rv_1d_pct with HAR-RV model predictions where possible."""
    try:
        from tradingagents.factors.har_rv_factors import compute_har_factors
        from tradingagents.models.har_rv_ridge import predict

        predictions: dict[str, float] = {}

        for ticker in all_tickers:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    try:
                        df = raw[ticker].dropna(how="all")
                    except KeyError:
                        try:
                            df = raw.xs(ticker, axis=1, level=1, drop_level=True)
                        except KeyError:
                            continue
                else:
                    df = raw.dropna(how="all")

                if df is None or len(df) < 25:
                    continue

                ohlc = df.rename(columns=str.lower)
                required = {"open", "high", "low", "close"}
                if not required.issubset(set(ohlc.columns)):
                    continue

                features = compute_har_factors(ohlc)
                last = features.tail(1).dropna(
                    subset=[c for c in features.columns if c in model.feature_names]
                )
                if last.empty:
                    continue

                last_date = last.index[0]
                last_panel = last.copy()
                last_panel.index = pd.MultiIndex.from_tuples(
                    [(last_date, ticker.upper())], names=["date", "ticker"]
                )

                # Align features to model
                model_features = list(model.feature_names)
                for col in model_features:
                    if col not in last_panel.columns:
                        last_panel[col] = float("nan")
                last_panel = last_panel[model_features]

                pred_series = predict(model, last_panel, min_tickers=1)
                if not pred_series.empty:
                    raw_pred = float(pred_series.iloc[0])
                    # Handle target transform
                    transform = getattr(model, "target_transform", None)
                    if transform == "log":
                        raw_pred = float(np.exp(raw_pred))
                    predictions[ticker.upper()] = round(raw_pred * np.sqrt(252) * 100, 2)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Model prediction for %s failed: %s", ticker, exc)
                continue

        # Override records with model predictions
        for rec in records:
            ticker_upper = rec["ticker"].upper()
            if ticker_upper in predictions:
                rec["predicted_rv_1d_pct"] = predictions[ticker_upper]

    except Exception as exc:  # noqa: BLE001
        logger.warning("Batch model prediction failed; using GK RV fallback: %s", exc)


def _empty_response(universe_equity_count: int, universe_etf_count: int) -> dict[str, Any]:
    """Return a valid but empty response when no data is available."""
    return {
        "equity": [],
        "etf": [],
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe_size": {"equity": universe_equity_count, "etf": universe_etf_count},
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/top-volatile")
async def top_volatile(
    n_equity: int = Query(default=20, ge=1, le=256, description="Number of top volatile equities"),
    n_etf: int = Query(default=20, ge=1, le=50, description="Number of top volatile ETFs"),
) -> dict[str, Any]:
    """Return the top N most volatile equities and ETFs."""
    cache_key = f"top_volatile:{n_equity}:{n_etf}"
    async with _CACHE_LOCK:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        result = await asyncio.to_thread(_compute_top_volatile, n_equity, n_etf)
        _cache_set(cache_key, result)
        return result
