"""Market overview routes with real-time data from yfinance."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["market"])

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_cache: dict[str, Any] = {}
_cache_ts: float = 0.0
_CACHE_TTL_SECONDS = 60

# ---------------------------------------------------------------------------
# Breadth tickers (large-cap Nasdaq-100 sample)
# ---------------------------------------------------------------------------
_BREADTH_TICKERS: list[str] = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD",
    "AMGN", "AMZN", "ANSS", "AVGO", "AZN", "BIIB", "BKNG", "BKR", "CDNS",
    "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP", "CSX",
    "CTAS", "CTSH", "DDOG", "DLTR", "DXCM", "EA", "ENPH", "EXC", "FANG",
    "FAST", "FTNT", "GEHC", "GFS", "GILD", "GOOG", "GOOGL", "HON", "IDXX",
    "ILMN", "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LRCX", "LULU",
    "MAR", "MCHP", "MDB", "MDLZ", "MELI", "META", "MNST", "MRNA", "MRVL",
    "MSFT", "MU", "NFLX", "NVDA", "NXPI", "ODFL", "ON", "ORLY", "PANW",
    "PAYX", "PCAR", "PDD", "PEP", "PYPL", "QCOM", "REGN", "ROST", "SBUX",
    "SIRI", "SNPS", "SPLK", "TEAM", "TMUS", "TSLA", "TTD", "TXN", "VRSK",
    "VRTX", "WBA", "WBD", "WDAY", "XEL", "ZM", "ZS",
]


# ---------------------------------------------------------------------------
# Sector definitions
# ---------------------------------------------------------------------------
_SECTOR_MAP: list[tuple[str, str]] = [
    ("Technology", "XLK"),
    ("Financials", "XLF"),
    ("Healthcare", "XLV"),
    ("Consumer Discretionary", "XLY"),
    ("Industrials", "XLI"),
    ("Communication Services", "XLC"),
    ("Consumer Staples", "XLP"),
    ("Energy", "XLE"),
    ("Utilities", "XLU"),
    ("Real Estate", "XLRE"),
    ("Materials", "XLB"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct_change(current: float, previous: float) -> float:
    """Return percentage change rounded to 2 decimals."""
    if previous == 0:
        return 0.0
    return round((current - previous) / previous * 100, 2)


def _safe_download(symbol: str, period: str = "2d") -> tuple[float, float]:
    """Download price history via yfinance and return (last_close, prev_close).

    Handles the yfinance MultiIndex columns issue (single ticker still gets
    a MultiIndex with the ticker name as level-1).
    Returns (0.0, 0.0) on any failure.
    """
    try:
        import yfinance as yf

        df = yf.download(symbol, period=period, progress=False)
        if df is None or df.empty:
            return 0.0, 0.0

        # Handle MultiIndex columns from yfinance (Price, Ticker) layout
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        if len(df) < 2:
            # Only one row available — return it with 0 change
            last = float(df["Close"].iloc[-1])
            return last, last

        closes = df["Close"].values
        return float(closes[-1]), float(closes[-2])
    except Exception:
        logger.debug("yfinance download failed for %s", symbol, exc_info=True)
        return 0.0, 0.0


def _fetch_index(symbol: str) -> dict[str, float]:
    current, prev = _safe_download(symbol)
    return {
        "price": round(current, 2),
        "change_pct": _pct_change(current, prev),
    }


def _fetch_vix() -> dict[str, Any]:
    """Fetch VIX value, trying multiple tickers with a stale fallback."""
    for ticker in ("^VIX", "VIXY"):
        current, prev = _safe_download(ticker)
        if current > 0:
            return {
                "value": round(current, 2),
                "change_pct": _pct_change(current, prev),
                "stale": False,
            }

    # All tickers failed — return a hardcoded recent value so fear/greed
    # and the frontend still have something useful to display.
    logger.warning("VIX fetch failed for all tickers, using stale fallback")
    return {
        "value": 23.9,
        "change_pct": 0.0,
        "stale": True,
    }


def _extract_last_close(symbol: str) -> float | None:
    """Download a single symbol and return its last close, handling MultiIndex."""
    try:
        import yfinance as yf

        df = yf.download(symbol, period="5d", progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        return round(float(df["Close"].iloc[-1]), 3)
    except Exception:
        logger.debug("_extract_last_close failed for %s", symbol, exc_info=True)
        return None


def _fetch_yields() -> dict[str, float | int | None]:
    """Fetch US 10-year and 2-year treasury yields.

    yfinance tickers:
      ^TNX  = CBOE 10-Year Treasury Note Yield (value is already in %)
      ^IRX  = 13-Week Treasury Bill Rate (3-month, value already in %)
      ^FVX  = 5-Year Treasury Yield
      ^TYX  = 30-Year Treasury Yield

    We report 10Y and 2Y.  For the 2-year there is no direct yfinance
    ticker so we try ^IRX (3-month) as a proxy; the spread still gives a
    useful curve-inversion signal.
    """
    try:
        us10y = _extract_last_close("^TNX")
        us02y = _extract_last_close("^IRX")  # 3-month as proxy for 2Y

        spread_bps: int | None = None
        if us10y is not None and us02y is not None:
            spread_bps = int(round((us10y - us02y) * 100))

        return {"us10y": us10y, "us02y": us02y, "spread_bps": spread_bps}
    except Exception:
        logger.debug("yield fetch failed", exc_info=True)
        return {"us10y": None, "us02y": None, "spread_bps": None}


def _fetch_commodity(symbol: str) -> dict[str, float]:
    current, prev = _safe_download(symbol)
    return {
        "price": round(current, 2),
        "change_pct": _pct_change(current, prev),
    }


def _fetch_sectors() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, etf in _SECTOR_MAP:
        current, prev = _safe_download(etf)
        results.append({
            "name": name,
            "etf": etf,
            "change_pct": _pct_change(current, prev),
        })
    # Sort best-performing first
    results.sort(key=lambda s: s["change_pct"], reverse=True)
    return results


def _compute_fear_greed(vix_value: float) -> dict[str, int | str]:
    """Mock fear/greed index based on VIX level."""
    if vix_value <= 0:
        return {"value": 50, "label": "Neutral"}
    if vix_value < 15:
        return {"value": 75, "label": "Greed"}
    if vix_value <= 20:
        return {"value": 50, "label": "Neutral"}
    if vix_value <= 30:
        return {"value": 30, "label": "Fear"}
    return {"value": 10, "label": "Extreme Fear"}


def _compute_breadth() -> dict[str, Any]:
    """Compute breadth from Nasdaq-100 tickers: how many are up vs down today."""
    try:
        import yfinance as yf

        tickers_str = " ".join(_BREADTH_TICKERS)
        df = yf.download(tickers_str, period="2d", progress=False, group_by="ticker")
        if df is None or df.empty:
            return {"advancing_pct": 0.0, "declining_pct": 0.0, "total": 0, "source": "nasdaq100"}

        advancing = 0
        declining = 0
        for ticker in _BREADTH_TICKERS:
            try:
                if ticker not in df.columns.get_level_values(0):
                    continue
                closes = df[ticker]["Close"].dropna()
                if len(closes) >= 2:
                    if float(closes.iloc[-1]) >= float(closes.iloc[-2]):
                        advancing += 1
                    else:
                        declining += 1
            except Exception:
                continue

        total = advancing + declining
        if total == 0:
            return {"advancing_pct": 0.0, "declining_pct": 0.0, "total": 0, "source": "nasdaq100"}

        return {
            "advancing_pct": round(advancing / total * 100, 1),
            "declining_pct": round(declining / total * 100, 1),
            "total": total,
            "source": "nasdaq100",
        }
    except Exception:
        logger.debug("breadth computation failed", exc_info=True)
        return {"advancing_pct": 0.0, "declining_pct": 0.0, "total": 0, "source": "nasdaq100"}


def _build_overview() -> dict[str, Any]:
    """Build the full market overview payload."""
    vix = _fetch_vix()

    return {
        "indices": {
            "SPY": _fetch_index("SPY"),
            "QQQ": _fetch_index("QQQ"),
            "DIA": _fetch_index("DIA"),
            "IWM": _fetch_index("IWM"),
        },
        "vix": vix,
        "rates": _fetch_yields(),
        "commodities": {
            "gold": _fetch_commodity("GLD"),
            "oil": _fetch_commodity("CL=F"),
            "btc": _fetch_commodity("BTC-USD"),
        },
        "extra": {
            "dxy": _fetch_commodity("DX-Y.NYB"),
            "gold_futures": _fetch_commodity("GC=F"),
            "oil_wti": _fetch_commodity("CL=F"),
        },
        "sectors": _fetch_sectors(),
        "breadth": _compute_breadth(),
        "fear_greed": _compute_fear_greed(vix.get("value", 20)),
        "timestamp": datetime.now().isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/market/overview")
async def get_market_overview() -> dict[str, Any]:
    """Return real-time market overview data, cached for 60 seconds."""
    global _cache, _cache_ts  # noqa: PLW0603

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL_SECONDS:
        return _cache

    try:
        overview = _build_overview()
    except Exception:
        logger.exception("Failed to build market overview, returning mock")
        overview = {
            "indices": {
                sym: {"price": 0.0, "change_pct": 0.0}
                for sym in ("SPY", "QQQ", "DIA", "IWM")
            },
            "vix": {"value": 20.0, "change_pct": 0.0, "stale": True},
            "rates": {"us10y": None, "us02y": None, "spread_bps": None},
            "commodities": {
                k: {"price": 0.0, "change_pct": 0.0}
                for k in ("gold", "oil", "btc")
            },
            "extra": {
                k: {"price": 0.0, "change_pct": 0.0}
                for k in ("dxy", "gold_futures", "oil_wti")
            },
            "sectors": [
                {"name": name, "etf": etf, "change_pct": 0.0}
                for name, etf in _SECTOR_MAP
            ],
            "breadth": {"advancing_pct": 0.0, "declining_pct": 0.0, "total": 0, "source": "nasdaq100"},
            "fear_greed": {"value": 50, "label": "Neutral"},
            "timestamp": datetime.now().isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    _cache = overview
    _cache_ts = now
    return overview
