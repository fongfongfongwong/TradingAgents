"""Holdings and insider transaction routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["holdings"])


@router.get("/holdings/{ticker}")
async def get_holdings(ticker: str) -> dict[str, Any]:
    """Return institutional holders and insider transactions for a ticker."""
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"yfinance error: {exc}") from exc

    # --- Institutional holders ---
    institutional: list[dict[str, Any]] = []
    try:
        inst_df = t.institutional_holders
        if inst_df is not None and not inst_df.empty:
            for _, row in inst_df.iterrows():
                institutional.append(
                    {
                        "holder": _safe_str(row.get("Holder")),
                        "shares": _safe_int(row.get("Shares")),
                        "change": 0,
                        "change_pct": 0,
                        "filing_date": _safe_date(row.get("Date Reported")),
                    }
                )
    except Exception:
        pass  # Some tickers have no institutional data

    # --- Insider transactions ---
    insider_txns: list[dict[str, Any]] = []
    try:
        insider_df = t.insider_transactions
        if insider_df is not None and not insider_df.empty:
            for _, row in insider_df.iterrows():
                insider_txns.append(
                    {
                        "insider": _safe_str(row.get("Insider")),
                        "relation": _safe_str(row.get("Relation")),
                        "action": _safe_str(row.get("Transaction")),
                        "shares": _safe_int(row.get("Shares")),
                        "price": 0,
                        "date": _safe_date(row.get("Date")),
                    }
                )
    except Exception:
        pass  # Some tickers have no insider data

    return {
        "ticker": ticker.upper(),
        "institutional": institutional,
        "insider_transactions": insider_txns,
    }


def _safe_str(val: Any) -> str:
    """Convert to string, returning empty string for None/NaN."""
    if val is None:
        return ""
    s = str(val)
    return "" if s == "nan" else s


def _safe_int(val: Any) -> int:
    """Convert to int, returning 0 for None/NaN."""
    if val is None:
        return 0
    try:
        f = float(val)
        return int(f) if f == f else 0
    except (TypeError, ValueError):
        return 0


def _safe_date(val: Any) -> str:
    """Convert a date/timestamp to ISO string, returning empty string on failure."""
    if val is None:
        return ""
    try:
        return val.isoformat()
    except AttributeError:
        s = str(val)
        return "" if s == "nan" or s == "NaT" else s
