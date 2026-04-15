"""Options chain routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["options"])


@router.get("/options/{ticker}")
async def get_options(ticker: str) -> dict[str, Any]:
    """Return the nearest-expiration options chain for a ticker."""
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        expirations = t.options
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"yfinance error: {exc}") from exc

    if not expirations:
        raise HTTPException(
            status_code=404, detail=f"No options data for '{ticker}'"
        )

    nearest_exp = expirations[0]

    try:
        chain = t.option_chain(nearest_exp)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"yfinance error: {exc}") from exc

    calls = chain.calls
    puts = chain.puts

    # Build merged chain keyed by strike
    strikes: dict[float, dict[str, Any]] = {}

    for _, row in calls.iterrows():
        strike = float(row["strike"])
        strikes.setdefault(strike, {"strike": strike})
        entry = strikes[strike]
        entry["call_bid"] = _safe_float(row.get("bid"))
        entry["call_ask"] = _safe_float(row.get("ask"))
        entry["call_volume"] = _safe_int(row.get("volume"))
        entry["call_oi"] = _safe_int(row.get("openInterest"))

    for _, row in puts.iterrows():
        strike = float(row["strike"])
        strikes.setdefault(strike, {"strike": strike})
        entry = strikes[strike]
        entry["put_bid"] = _safe_float(row.get("bid"))
        entry["put_ask"] = _safe_float(row.get("ask"))
        entry["put_volume"] = _safe_int(row.get("volume"))
        entry["put_oi"] = _safe_int(row.get("openInterest"))

    # Fill missing sides with zeros
    merged: list[dict[str, Any]] = []
    for strike in sorted(strikes):
        rec = strikes[strike]
        merged.append(
            {
                "strike": rec["strike"],
                "call_bid": rec.get("call_bid", 0.0),
                "call_ask": rec.get("call_ask", 0.0),
                "call_volume": rec.get("call_volume", 0),
                "call_oi": rec.get("call_oi", 0),
                "put_bid": rec.get("put_bid", 0.0),
                "put_ask": rec.get("put_ask", 0.0),
                "put_volume": rec.get("put_volume", 0),
                "put_oi": rec.get("put_oi", 0),
            }
        )

    total_call_vol = sum(r["call_volume"] for r in merged)
    total_put_vol = sum(r["put_volume"] for r in merged)
    put_call_ratio = (total_put_vol / total_call_vol) if total_call_vol > 0 else 0.0

    return {
        "ticker": ticker.upper(),
        "expiration": nearest_exp,
        "chain": merged,
        "put_call_ratio": round(put_call_ratio, 4),
        "iv_rank": None,
    }


def _safe_float(val: Any) -> float:
    """Convert to float, returning 0.0 for None/NaN."""
    if val is None:
        return 0.0
    try:
        f = float(val)
        return f if f == f else 0.0  # NaN check
    except (TypeError, ValueError):
        return 0.0


def _safe_int(val: Any) -> int:
    """Convert to int, returning 0 for None/NaN."""
    if val is None:
        return 0
    try:
        f = float(val)
        return int(f) if f == f else 0
    except (TypeError, ValueError):
        return 0
