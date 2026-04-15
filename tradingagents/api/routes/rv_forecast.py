"""RV forecast endpoints: train + predict.

Wires the HAR-RV Ridge baseline model (see
``tradingagents/models/har_rv_ridge.py`` and
``tradingagents/factors/har_rv_factors.py``) into the v3 API surface.

Endpoints
---------
- ``GET  /api/v3/rv/forecast/{ticker}`` -- single-ticker prediction.
- ``GET  /api/v3/rv/model/status``      -- per-horizon load metadata.
- ``POST /api/v3/rv/train``             -- trigger a (blocking) training run.

All blocking work -- joblib model loads, pandas feature computation,
yfinance fetches, and the training loop -- is offloaded to
``asyncio.to_thread`` so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/rv", tags=["rv_forecast"])


# ---------------------------------------------------------------------------
# In-process prediction cache (ticker, date, horizon) -> payload
# ---------------------------------------------------------------------------

_PREDICTION_CACHE: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}
_PREDICTION_TTL_SECONDS: float = 3600.0  # 1 hour


def _cache_get(key: tuple[str, str, int]) -> dict[str, Any] | None:
    import time

    entry = _PREDICTION_CACHE.get(key)
    if entry is None:
        return None
    stored_at, payload = entry
    if time.time() - stored_at > _PREDICTION_TTL_SECONDS:
        _PREDICTION_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: tuple[str, str, int], payload: dict[str, Any]) -> None:
    import time

    _PREDICTION_CACHE[(key[0], key[1], key[2])] = (time.time(), payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_model_safe(horizon: int) -> Any | None:
    """Import ``load_model`` lazily and invoke it.

    Returns ``None`` (rather than raising) when the model module cannot be
    imported yet (e.g. during Round 1 before R1-2 has shipped) or when no
    trained artifact is on disk.
    """
    try:
        from tradingagents.models.har_rv_ridge import load_model  # type: ignore
    except Exception as exc:  # noqa: BLE001 - defensive: module may not exist yet
        logger.warning("har_rv_ridge module import failed: %s", exc)
        return None
    try:
        return load_model(horizon=horizon)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_model(%d) failed: %s", horizon, exc)
        return None


_LEGACY_FEATURE_NAMES: tuple[str, ...] = (
    "rv_daily",
    "rv_5d_mean",
    "rv_22d_mean",
    "bpv_daily",
    "rv_momentum",
    "vol_surprise",
    "rv_5d_std",
    "rv_22d_std",
    "rv_ar1_pred",
    "rv_ar1_resid",
)


def _align_features_to_model(
    features: Any,
    model: Any,
    options_ctx: Any | None = None,
) -> Any:
    """Project ``features`` onto the exact columns the model was trained on.

    Columns the model does not know about are dropped, missing columns are
    filled with NaN, and known options-context fields are attached iff the
    model expects them. Never raises.
    """
    model_features = tuple(getattr(model, "feature_names", ()) or ())
    if not model_features:
        return features

    aligned = features.copy()

    if options_ctx is not None:
        options_field_map: dict[str, Any] = {
            "iv_skew_25d": getattr(options_ctx, "iv_skew_25d", None),
            "iv_rank_percentile": getattr(options_ctx, "iv_rank_percentile", None),
            "put_call_ratio": getattr(options_ctx, "put_call_ratio", None),
            "iv_level_30d": getattr(options_ctx, "iv_level_30d", None),
        }
        for col_name, value in options_field_map.items():
            if col_name in model_features:
                aligned[col_name] = (
                    float(value) if value is not None else float("nan")
                )

    for col in model_features:
        if col not in aligned.columns:
            aligned[col] = float("nan")

    return aligned[list(model_features)]


def _invert_target_transform(raw_pred: float, model: Any) -> float:
    """Apply the inverse of the training-time ``target_transform`` metadata.

    Supports ``"log"`` (applies ``np.exp``) and ``"raw"`` / missing (no-op).
    Unknown transform values log a warning and return the raw prediction.
    """
    transform = getattr(model, "target_transform", None)
    if transform is None or transform == "raw":
        return float(raw_pred)
    if transform == "log":
        import numpy as np  # type: ignore

        return float(np.exp(raw_pred))
    logger.warning(
        "Unknown target_transform=%r on model; returning raw prediction",
        transform,
    )
    return float(raw_pred)


def _compute_features_for_ticker(
    ticker: str,
    model: Any | None = None,
    options_ctx: Any | None = None,
) -> Any | None:
    """Fetch OHLC for ``ticker`` and compute HAR features.

    Returns the most recent non-NaN feature row as a DataFrame, or ``None``
    on any failure (module missing, no data, all-NaN features).

    When ``model`` is supplied the returned frame is projected onto
    ``model.feature_names``. Extra columns produced by newer
    ``har_rv_factors`` versions (Tier 0 / Tier 1) are dropped for legacy
    models that only know the 10 baseline columns. Missing columns are
    filled with NaN so ``predict()`` never crashes. When ``options_ctx`` is
    also supplied, known options fields are attached iff the model expects
    them.
    """
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance import failed: %s", exc)
        return None

    try:
        from tradingagents.factors.har_rv_factors import (  # type: ignore
            compute_har_factors,
        )
        try:
            from tradingagents.factors.har_rv_factors import (  # type: ignore
                FEATURE_NAMES,
            )
        except Exception:  # noqa: BLE001
            FEATURE_NAMES = _LEGACY_FEATURE_NAMES
    except Exception as exc:  # noqa: BLE001
        logger.warning("har_rv_factors module import failed: %s", exc)
        return None

    try:
        import pandas as pd  # type: ignore

        hist = yf.Ticker(ticker).history(period="2y", auto_adjust=False)
        if hist is None or len(hist) < 60:
            return None
        ohlc = hist.rename(columns=str.lower)
        required = {"open", "high", "low", "close"}
        if not required.issubset(set(ohlc.columns)):
            return None
        features = compute_har_factors(ohlc)

        # Use legacy column subset as the NaN gate so Tier 0 rows that are
        # legitimately NaN early in the history do not filter everything.
        legacy_subset = [
            c for c in FEATURE_NAMES if c in features.columns
        ] or list(features.columns)
        last = features.tail(1).dropna(subset=legacy_subset)
        if last.empty:
            return None

        # predict() expects a MultiIndex panel (date, ticker).
        # Reshape the single-row feature frame into that shape.
        last_date = last.index[0]
        last_panel = last.copy()
        last_panel.index = pd.MultiIndex.from_tuples(
            [(last_date, ticker.upper())], names=["date", "ticker"]
        )

        if model is not None:
            last_panel = _align_features_to_model(
                last_panel, model, options_ctx=options_ctx
            )

        return last_panel
    except Exception as exc:  # noqa: BLE001
        logger.warning("_compute_features_for_ticker(%s) failed: %s", ticker, exc)
        return None


def _predict_with_model(model: Any, features: Any) -> float | None:
    """Invoke ``har_rv_ridge.predict`` and return the (inverse-transformed) scalar."""
    try:
        from tradingagents.models.har_rv_ridge import predict  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("har_rv_ridge.predict import failed: %s", exc)
        return None
    try:
        series = predict(model, features)
        if len(series) == 0:
            return None
        raw_value = float(series.iloc[0])
        return _invert_target_transform(raw_value, model)
    except Exception as exc:  # noqa: BLE001
        logger.warning("predict() failed: %s", exc)
        return None


def _current_realized_vol_20d_pct(ticker: str) -> float | None:
    """Compute the 20d annualized realized vol % from yfinance history.

    Mirrors the materializer's computation using log returns; returns
    ``None`` when insufficient data or yfinance is unavailable.
    """
    try:
        import math

        import numpy as np
        import yfinance as yf  # type: ignore
    except Exception:
        return None

    try:
        hist = yf.Ticker(ticker).history(period="3mo", auto_adjust=False)
        if hist is None or len(hist) < 21 or "Close" not in hist.columns:
            return None
        close = hist["Close"].astype(float)
        close = close[close > 0.0]
        if len(close) < 21:
            return None
        log_returns = np.log(close / close.shift(1)).dropna().iloc[-20:]
        stdev = float(log_returns.std(ddof=1))
        return round(stdev * math.sqrt(252.0) * 100.0, 4)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/forecast/{ticker}")
async def get_rv_forecast(
    ticker: str,
    horizon: int = Query(1, ge=1, le=5),
) -> dict[str, Any]:
    """Return HAR-RV Ridge prediction for ``ticker``.

    Response shape::

        {
            "ticker": "AAPL",
            "horizon_days": 1,
            "predicted_rv_pct": 19.5,
            "current_realized_vol_20d_pct": 18.2,
            "delta_pct": 1.3,
            "model_version": "har_rv_ridge_v1_trained_2026-04-05",
            "computed_at": "2026-04-05T18:30:00Z"
        }

    Returns HTTP 404 when no trained model is available for the horizon.
    """
    ticker_norm = ticker.upper()
    today = date.today().isoformat()
    cache_key = (ticker_norm, today, int(horizon))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    model = await asyncio.to_thread(_load_model_safe, int(horizon))
    if model is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No trained HAR-RV Ridge model available for horizon={horizon}. "
                "Run POST /api/v3/rv/train to fit one, or wait for the scheduled "
                "training batch to complete."
            ),
        )

    features = await asyncio.to_thread(
        _compute_features_for_ticker, ticker_norm, model, None
    )
    if features is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not compute HAR features for {ticker_norm}: "
                "insufficient history or yfinance fetch failed."
            ),
        )

    pred_raw = await asyncio.to_thread(_predict_with_model, model, features)
    if pred_raw is None:
        raise HTTPException(
            status_code=500,
            detail="Prediction failed; see server logs for details.",
        )

    # Model output is daily Garman-Klass RV in return space (e.g. 0.015 = 1.5%/day).
    # Annualize: daily_vol * sqrt(252) * 100 to match realized_vol_20d_pct units.
    import math
    predicted_rv_pct = round(pred_raw * math.sqrt(252.0) * 100.0, 4)
    current_rv = await asyncio.to_thread(_current_realized_vol_20d_pct, ticker_norm)
    delta_pct: float | None = None
    if current_rv is not None:
        delta_pct = round(predicted_rv_pct - current_rv, 4)

    trained_at = getattr(model, "trained_at", "") or ""
    model_version = f"har_rv_ridge_v1_{trained_at[:10]}" if trained_at else "har_rv_ridge_v1"

    payload: dict[str, Any] = {
        "ticker": ticker_norm,
        "horizon_days": int(horizon),
        "predicted_rv_pct": predicted_rv_pct,
        "current_realized_vol_20d_pct": current_rv,
        "delta_pct": delta_pct,
        "model_version": model_version,
        "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _cache_set(cache_key, payload)
    return payload


@router.get("/model/status")
async def get_model_status() -> dict[str, Any]:
    """Return metadata about loaded HAR-RV Ridge models.

    Always returns HTTP 200 -- a missing model is reported as
    ``loaded: false`` rather than raising.
    """
    models: dict[str, dict[str, Any]] = {}
    for horizon in (1, 5):
        model = await asyncio.to_thread(_load_model_safe, horizon)
        if model is None:
            models[f"{horizon}d"] = {
                "loaded": False,
                "version": None,
                "train_rows": None,
            }
            continue
        trained_at = getattr(model, "trained_at", "") or ""
        version = (
            f"har_rv_ridge_v1_{trained_at[:10]}" if trained_at else "har_rv_ridge_v1"
        )
        models[f"{horizon}d"] = {
            "loaded": True,
            "version": version,
            "train_rows": getattr(model, "train_rows", None),
        }

    outputs_root = str(
        Path("~/.tradingagents/outputs/rv_prediction/baseline/").expanduser()
    )
    return {"models": models, "outputs_root": outputs_root}


@router.post("/train")
async def trigger_training(body: dict | None = None) -> dict[str, Any]:
    """Trigger a HAR-RV Ridge training run (blocking, offloaded to a thread).

    Body (all optional)::

        {
            "tickers": ["AAPL", ...] | null,
            "horizons": [1, 5],
            "train_end": "2023-12-31",
            "valid_end": "2024-06-30"
        }

    ``tickers=null`` falls back to a default universe defined by the training
    module. Returns the training summary once complete.

    .. warning::
       This endpoint is synchronous and can run for several minutes on a
       full universe. Prefer the CLI entrypoint for production batches.
    """
    body = body or {}
    tickers = body.get("tickers")
    horizons = body.get("horizons") or [1, 5]
    train_end = body.get("train_end")
    valid_end = body.get("valid_end")

    try:
        from tradingagents.models.har_rv_ridge import train_and_save  # type: ignore
    except Exception as exc:  # noqa: BLE001 - module may not exist yet
        raise HTTPException(
            status_code=503,
            detail=(
                "HAR-RV Ridge training module not yet available on this "
                f"deployment ({exc}). Wait for Round 1 / R1-2 to land."
            ),
        ) from exc

    def _run_training() -> dict[str, Any]:
        return train_and_save(
            tickers=tickers,
            horizons=horizons,
            train_end=train_end,
            valid_end=valid_end,
        )

    try:
        summary = await asyncio.to_thread(_run_training)
    except Exception as exc:  # noqa: BLE001
        logger.exception("HAR-RV training failed")
        raise HTTPException(status_code=500, detail=f"Training failed: {exc}") from exc

    return {
        "status": "ok",
        "summary": summary,
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
