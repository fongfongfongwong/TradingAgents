"""High-volatility US equities + ETFs screener (FLAB MASA v3, Step 1).

Two-stage pipeline that produces a daily curated list of the 20 most volatile
US equities and the 20 most volatile US ETFs for a given date:

    Stage 1 (quant)
      1. Polygon grouped daily endpoint  -> single HTTP call, ~8000 tickers.
      2. Liquidity / penny-stock / volume pre-filter         -> ~800 names.
      3. Sort by grouped-day (high-low)/close proxy          -> top ~200.
      4. Parallel 25-day aggregates fetch (5 workers)        -> OHLC history.
      5. Per-ticker realized_vol_20d, Wilder ATR-14 pct,
         20-day range pct.
      6. Z-score normalise each metric, composite_score.
      7. Split equities / ETFs, take top ``shortlist_size`` each.

    Stage 2 (LLM)
      8. Send both shortlists to Claude Sonnet 4.5 which
         removes illiquid / recently IPO'd / corporate-action
         anomalies and returns the final ``top_n`` per group
         with a one-sentence reason per keeper.

Failures are tolerated at every level:
  * Missing POLYGON_API_KEY        -> ``fetched_ok=False`` with clear error.
  * Per-ticker history failure     -> that ticker is silently skipped.
  * LLM failure                    -> fall back to the pure-quant top ``top_n``
                                      with ``llm_reason=None``.

Results are cached per ``target_date`` in ``~/.tradingagents/screener_cache.db``
(SQLite, same permission model as ``api_key_store.py``). A second call for the
same date returns the cached payload with zero HTTP traffic.

This module never raises on network or LLM errors -- it always returns a
well-formed :class:`ScreenerResult`.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VolRank:
    """Immutable per-ticker ranking row."""

    ticker: str
    name: str | None
    last_close: float
    volume: int
    dollar_volume: float
    realized_vol_20d: float | None
    atr_pct: float | None
    range_20d_pct: float | None
    composite_score: float
    is_etf: bool
    kept_by_llm: bool = False
    llm_reason: str | None = None


@dataclass(frozen=True)
class ScreenerResult:
    """Immutable screener output.

    ``equities`` and ``etfs`` hold the final top-N after the LLM filter.
    ``*_shortlist`` hold the top ``shortlist_size`` produced by the quant
    ranking, preserved for audit / debugging.
    """

    computed_at: datetime
    equities: list[VolRank]
    etfs: list[VolRank]
    equities_shortlist: list[VolRank]
    etfs_shortlist: list[VolRank]
    fetched_ok: bool
    error: str | None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_POLYGON_BASE = "https://api.polygon.io"
_HTTP_TIMEOUT = 15.0
_HISTORY_WORKERS = 5
_HISTORY_DAYS = 25           # calendar window -> ~18 trading days, we want >=21
_HISTORY_LOOKBACK_DAYS = 40  # generous lookback so we always get >=25 rows
_MIN_PRICE = 3.0             # penny-stock filter
_MIN_VOLUME = 500_000        # liquidity filter (shares)
_MIN_DOLLAR_VOL = 10_000_000 # liquidity filter (USD)
_INTERMEDIATE_TOP_K = 200    # how many names enter the expensive history loop


# A conservative hardcoded list of popular/liquid US ETFs. Ticker class is not
# authoritatively distinguishable from the grouped-daily endpoint, so we rely
# on this allow-list + default-to-equity fallback. The list focuses on names
# that are actually likely to top a volatility screen on any given day.
_KNOWN_ETFS: frozenset[str] = frozenset(
    {
        # Broad index / core
        "SPY", "VOO", "IVV", "QQQ", "QQQM", "DIA", "IWM", "IWB", "IWV", "IWN",
        "IWO", "IWS", "IWP", "MDY", "VTI", "VTV", "VUG", "VB", "VBR", "VBK",
        "VO", "VOE", "VOT", "VEA", "VWO", "EFA", "EEM", "ACWI", "SCHD", "SCHB",
        "SCHX", "SCHA", "SCHG", "SCHV",
        # Sector SPDRs
        "XLF", "XLK", "XLE", "XLY", "XLP", "XLV", "XLI", "XLB", "XLRE", "XLU",
        "XLC", "XME", "XOP", "XBI", "XHB", "XRT", "XAR", "XSD", "XPH", "XTL",
        "XES", "XTN", "XHE",
        # Thematic / industry
        "SMH", "SOXX", "IBB", "KRE", "KBE", "KIE", "ITA", "ITB", "IYR", "REM",
        "VNQ", "IYT", "IGV", "HACK", "FINX", "CIBR", "ROBO", "BOTZ", "ICLN",
        "TAN", "FAN", "PBW", "LIT", "URA", "REMX", "COPX", "GDX", "GDXJ", "SIL",
        "SILJ", "GLD", "GLDM", "SLV", "IAU", "PPLT", "PALL", "DBA", "DBC", "USO",
        "UNG", "BNO", "UGA", "WEAT", "CORN", "SOYB", "CANE", "JO", "NIB",
        # International country / regional
        "EWJ", "EWZ", "EWA", "EWC", "EWG", "EWH", "EWI", "EWK", "EWL", "EWM",
        "EWN", "EWO", "EWP", "EWQ", "EWS", "EWT", "EWU", "EWW", "EWY", "EZA",
        "EIS", "EPOL", "EPU", "TUR", "ARGT", "EIDO", "THD", "VNM", "INDA", "EPI",
        "PIN", "FXI", "KWEB", "MCHI", "ASHR", "CQQQ", "YINN", "YANG", "EDC",
        "EDZ", "VPL", "VGK", "IEMG", "IEUR", "ILF", "AAXJ", "FLKR",
        # Volatility / leveraged / inverse (these frequently top vol rankings)
        "VXX", "UVXY", "VIXY", "SVXY", "VIXM", "SVIX",
        "TQQQ", "SQQQ", "UPRO", "SPXU", "SPXS", "SPXL", "TNA", "TZA", "UDOW",
        "SDOW", "SOXL", "SOXS", "LABU", "LABD", "NUGT", "JNUG", "DUST", "JDST",
        "GUSH", "DRIP", "ERX", "ERY", "FAS", "FAZ", "DPST", "DRN", "DRV", "CURE",
        "RETL", "YCL", "YCS", "EUO", "UUP", "UDN", "BOIL", "KOLD", "SCO", "UCO",
        "AGQ", "ZSL", "UGL", "GLL", "BIB", "BIS", "TMF", "TMV", "TTT", "EDV",
        "ZROZ", "URTY", "SRTY",
        # ARK
        "ARKK", "ARKQ", "ARKW", "ARKG", "ARKF", "ARKX", "PRNT", "IZRL",
        # Bonds
        "TLT", "IEF", "SHY", "BND", "AGG", "LQD", "HYG", "JNK", "EMB", "MUB",
        "TIP", "VCIT", "VCSH", "VCLT", "BSV", "BIV", "BLV", "GOVT", "IEI",
        "SHV", "BIL", "SGOV", "FLOT", "USFR", "SJNK", "SRLN", "BKLN",
        # Dividend / factor
        "SCHD", "VYM", "VIG", "NOBL", "DVY", "HDV", "SPHD", "SPLV", "USMV",
        "MTUM", "QUAL", "SIZE", "VLUE", "VMOT", "MOAT", "COWZ", "SPY",
        # Crypto-linked
        "BITO", "BITI", "BTF", "ETHE", "GBTC", "ETHA", "BITB", "IBIT", "FBTC",
        "ARKB", "HODL", "EZBC", "BTCO",
        # Other popular
        "HYG", "JETS", "PAVE", "INFR", "URNM", "REMX", "GDX",
    }
)


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------


_CACHE_DB_PATH = Path.home() / ".tradingagents" / "screener_cache.db"
_CACHE_LOCK = threading.Lock()


def _ensure_cache_db() -> None:
    """Create the cache DB file + schema if missing. Forces 0600 perms."""
    _CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_CACHE_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS screener_cache (
                target_date TEXT PRIMARY KEY,
                payload     TEXT NOT NULL,
                stored_at   TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    try:
        os.chmod(_CACHE_DB_PATH, 0o600)
    except OSError:
        pass


def _cache_get(target_date: date) -> ScreenerResult | None:
    """Return cached result for ``target_date`` or ``None``."""
    with _CACHE_LOCK:
        if not _CACHE_DB_PATH.exists():
            return None
        conn = sqlite3.connect(_CACHE_DB_PATH)
        try:
            row = conn.execute(
                "SELECT payload FROM screener_cache WHERE target_date = ?",
                (target_date.isoformat(),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            return _deserialize(row[0])
        except Exception as exc:  # noqa: BLE001 -- cache corruption is non-fatal
            logger.warning("Screener cache decode failed for %s: %s", target_date, exc)
            return None


def _cache_put(target_date: date, result: ScreenerResult) -> None:
    """Persist ``result`` under ``target_date``."""
    with _CACHE_LOCK:
        _ensure_cache_db()
        conn = sqlite3.connect(_CACHE_DB_PATH)
        try:
            conn.execute(
                "INSERT INTO screener_cache (target_date, payload, stored_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(target_date) DO UPDATE SET payload = excluded.payload, "
                "stored_at = excluded.stored_at",
                (
                    target_date.isoformat(),
                    _serialize(result),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def _clear_cache() -> None:
    """Test hook: wipe the cache DB entries."""
    with _CACHE_LOCK:
        if not _CACHE_DB_PATH.exists():
            return
        conn = sqlite3.connect(_CACHE_DB_PATH)
        try:
            conn.execute("DELETE FROM screener_cache")
            conn.commit()
        finally:
            conn.close()


def _serialize(result: ScreenerResult) -> str:
    """JSON-encode a ``ScreenerResult`` for SQLite storage."""
    def _rank_to_dict(r: VolRank) -> dict[str, Any]:
        return asdict(r)

    payload = {
        "computed_at": result.computed_at.isoformat(),
        "equities": [_rank_to_dict(r) for r in result.equities],
        "etfs": [_rank_to_dict(r) for r in result.etfs],
        "equities_shortlist": [_rank_to_dict(r) for r in result.equities_shortlist],
        "etfs_shortlist": [_rank_to_dict(r) for r in result.etfs_shortlist],
        "fetched_ok": result.fetched_ok,
        "error": result.error,
    }
    return json.dumps(payload)


def _deserialize(raw: str) -> ScreenerResult:
    """Reverse of :func:`_serialize`."""
    data = json.loads(raw)

    def _dict_to_rank(d: dict[str, Any]) -> VolRank:
        return VolRank(**d)

    return ScreenerResult(
        computed_at=datetime.fromisoformat(data["computed_at"]),
        equities=[_dict_to_rank(r) for r in data["equities"]],
        etfs=[_dict_to_rank(r) for r in data["etfs"]],
        equities_shortlist=[_dict_to_rank(r) for r in data["equities_shortlist"]],
        etfs_shortlist=[_dict_to_rank(r) for r in data["etfs_shortlist"]],
        fetched_ok=bool(data["fetched_ok"]),
        error=data.get("error"),
    )


# ---------------------------------------------------------------------------
# Polygon HTTP helpers
# ---------------------------------------------------------------------------


def _polygon_api_key() -> str | None:
    key = os.environ.get("POLYGON_API_KEY")
    return key if key else None


def _fetch_grouped_daily(target_date: date, api_key: str) -> list[dict[str, Any]]:
    """Call Polygon's grouped daily bars endpoint.

    Returns the ``results`` list. Raises :class:`RuntimeError` on any failure
    with a human-readable message.
    """
    url = (
        f"{_POLYGON_BASE}/v2/aggs/grouped/locale/us/market/stocks/"
        f"{target_date.isoformat()}"
    )
    params = {"adjusted": "true", "apiKey": api_key}
    resp = requests.get(url, params=params, timeout=_HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Polygon grouped daily HTTP {resp.status_code}: {resp.text[:200]}"
        )
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("Polygon grouped daily: unexpected payload type")
    results = data.get("results")
    if not isinstance(results, list):
        raise RuntimeError("Polygon grouped daily: missing results list")
    return results


def _fetch_ticker_history(
    ticker: str,
    end_date: date,
    api_key: str,
) -> list[dict[str, float]] | None:
    """Fetch ~``_HISTORY_LOOKBACK_DAYS`` days of daily bars for ``ticker``.

    Returns a list of ``{"o","h","l","c","v"}`` dicts sorted oldest-first, or
    ``None`` on any failure.
    """
    start = end_date - timedelta(days=_HISTORY_LOOKBACK_DAYS)
    url = (
        f"{_POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/day/"
        f"{start.isoformat()}/{end_date.isoformat()}"
    )
    params = {"adjusted": "true", "sort": "asc", "limit": 120, "apiKey": api_key}
    try:
        resp = requests.get(url, params=params, timeout=_HTTP_TIMEOUT)
        if resp.status_code != 200:
            return None
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Polygon history fetch failed for %s: %s", ticker, exc)
        return None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return None
    bars: list[dict[str, float]] = []
    for bar in results:
        if not isinstance(bar, dict):
            continue
        try:
            bars.append(
                {
                    "o": float(bar["o"]),
                    "h": float(bar["h"]),
                    "l": float(bar["l"]),
                    "c": float(bar["c"]),
                    "v": float(bar.get("v", 0.0) or 0.0),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return bars if bars else None


# ---------------------------------------------------------------------------
# Quant math
# ---------------------------------------------------------------------------


def _realized_vol_annualized(closes: list[float]) -> float | None:
    """Return annualized realized vol from daily log returns.

    Needs at least 3 closes. Returns ``None`` otherwise.
    """
    if len(closes) < 3:
        return None
    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev <= 0 or curr <= 0:
            continue
        rets.append(math.log(curr / prev))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _wilder_atr_pct(bars: list[dict[str, float]], period: int = 14) -> float | None:
    """Return Wilder ATR(14) / last_close, i.e. fractional ATR.

    Needs at least ``period + 1`` bars.
    """
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1]["c"]
        h = bars[i]["h"]
        l = bars[i]["l"]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    # Wilder's smoothing: start with simple mean over first `period` TRs, then
    # recursively smooth.
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    last_close = bars[-1]["c"]
    if last_close <= 0:
        return None
    return atr / last_close


def _range_20d_pct(bars: list[dict[str, float]]) -> float | None:
    """Return the mean of ``(high-low)/mid`` over the last 20 bars."""
    if len(bars) < 5:
        return None
    window = bars[-20:]
    pcts: list[float] = []
    for bar in window:
        mid = (bar["h"] + bar["l"]) / 2.0
        if mid <= 0:
            continue
        pcts.append((bar["h"] - bar["l"]) / mid)
    if not pcts:
        return None
    return sum(pcts) / len(pcts)


def _zscore(values: list[float]) -> list[float]:
    """Return z-scores of a list of floats. Constant inputs -> all zeros."""
    if not values:
        return []
    mean = sum(values) / len(values)
    if len(values) < 2:
        return [0.0 for _ in values]
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return [0.0 for _ in values]
    return [(v - mean) / std for v in values]


# ---------------------------------------------------------------------------
# ETF classification
# ---------------------------------------------------------------------------


def _is_etf(ticker: str) -> bool:
    """Classify ``ticker`` as ETF using the hardcoded allow-list."""
    return ticker.upper() in _KNOWN_ETFS


# ---------------------------------------------------------------------------
# Stage 1: grouped daily -> pre-filter -> proxy sort
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GroupedRow:
    ticker: str
    close: float
    volume: int
    dollar_volume: float
    high: float
    low: float
    proxy_range: float  # (h - l) / c, used as coarse vol proxy


def _parse_grouped_rows(results: Iterable[dict[str, Any]]) -> list[_GroupedRow]:
    """Normalise Polygon grouped payload rows into :class:`_GroupedRow`."""
    rows: list[_GroupedRow] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        ticker = r.get("T")
        close = r.get("c")
        volume = r.get("v")
        high = r.get("h")
        low = r.get("l")
        vwap = r.get("vw")
        if not ticker or close is None or volume is None or high is None or low is None:
            continue
        try:
            c = float(close)
            v = float(volume)
            h = float(high)
            lo = float(low)
        except (TypeError, ValueError):
            continue
        if c <= 0 or v < 0:
            continue
        # Skip obviously-not-tickers (warrants, units, weird suffixes are OK --
        # LLM stage will prune them).
        if not isinstance(ticker, str) or len(ticker) > 8:
            continue
        try:
            dv = float(vwap) * v if vwap is not None else c * v
        except (TypeError, ValueError):
            dv = c * v
        proxy = (h - lo) / c if c > 0 else 0.0
        rows.append(
            _GroupedRow(
                ticker=ticker.upper(),
                close=c,
                volume=int(v),
                dollar_volume=dv,
                high=h,
                low=lo,
                proxy_range=proxy,
            )
        )
    return rows


def _prefilter(rows: list[_GroupedRow]) -> list[_GroupedRow]:
    """Apply penny-stock / liquidity / volume filters."""
    out: list[_GroupedRow] = []
    for r in rows:
        if r.close < _MIN_PRICE:
            continue
        if r.volume < _MIN_VOLUME:
            continue
        if r.dollar_volume < _MIN_DOLLAR_VOL:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Stage 1b: per-ticker history + metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Metrics:
    ticker: str
    last_close: float
    volume: int
    dollar_volume: float
    realized_vol_20d: float | None
    atr_pct: float | None
    range_20d_pct: float | None


def _compute_metrics_for_row(
    row: _GroupedRow,
    end_date: date,
    api_key: str,
) -> _Metrics | None:
    """Fetch history + compute all three metrics for a single row."""
    bars = _fetch_ticker_history(row.ticker, end_date, api_key)
    if not bars:
        return None
    closes = [b["c"] for b in bars]
    rv = _realized_vol_annualized(closes[-21:])  # last ~20 returns
    atr = _wilder_atr_pct(bars[-15:])
    rng = _range_20d_pct(bars)
    return _Metrics(
        ticker=row.ticker,
        last_close=row.close,
        volume=row.volume,
        dollar_volume=row.dollar_volume,
        realized_vol_20d=rv,
        atr_pct=atr,
        range_20d_pct=rng,
    )


def _score_and_rank(metrics: list[_Metrics]) -> list[VolRank]:
    """Compute composite z-score for every metric row and build VolRank list.

    Metrics with all-None rows are dropped. Missing individual sub-metrics are
    filled with the group mean before z-scoring (so the row still contributes
    via the metrics it has).
    """
    usable = [
        m
        for m in metrics
        if any(v is not None for v in (m.realized_vol_20d, m.atr_pct, m.range_20d_pct))
    ]
    if not usable:
        return []

    def _col(attr: str) -> list[float]:
        col = [getattr(m, attr) for m in usable]
        present = [v for v in col if v is not None]
        fill = (sum(present) / len(present)) if present else 0.0
        return [v if v is not None else fill for v in col]

    rv_vals = _col("realized_vol_20d")
    atr_vals = _col("atr_pct")
    rng_vals = _col("range_20d_pct")

    rv_z = _zscore(rv_vals)
    atr_z = _zscore(atr_vals)
    rng_z = _zscore(rng_vals)

    ranks: list[VolRank] = []
    for i, m in enumerate(usable):
        score = 0.5 * rv_z[i] + 0.3 * atr_z[i] + 0.2 * rng_z[i]
        ranks.append(
            VolRank(
                ticker=m.ticker,
                name=None,
                last_close=m.last_close,
                volume=m.volume,
                dollar_volume=m.dollar_volume,
                realized_vol_20d=m.realized_vol_20d,
                atr_pct=m.atr_pct,
                range_20d_pct=m.range_20d_pct,
                composite_score=score,
                is_etf=_is_etf(m.ticker),
            )
        )
    return ranks


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _most_recent_weekday(d: date | None) -> date:
    """Return the most recent weekday (Mon-Fri) on or before ``d``."""
    if d is None:
        d = datetime.now(timezone.utc).date()
    while d.weekday() >= 5:  # 5 = Sat, 6 = Sun
        d -= timedelta(days=1)
    return d


def _apply_llm_filter(
    equities_short: list[VolRank],
    etfs_short: list[VolRank],
    top_n: int,
) -> tuple[list[VolRank], list[VolRank]]:
    """Run the LLM filter on both shortlists. Always returns deterministically."""
    try:
        from .llm_filter import llm_filter_shortlist
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_filter import failed: %s -- falling back to quant", exc)
        return equities_short[:top_n], etfs_short[:top_n]

    try:
        filtered_eq = llm_filter_shortlist(equities_short, "US equities", top_n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM filter failed for equities: %s", exc)
        filtered_eq = equities_short[:top_n]
    try:
        filtered_etf = llm_filter_shortlist(etfs_short, "US ETFs", top_n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM filter failed for ETFs: %s", exc)
        filtered_etf = etfs_short[:top_n]
    return filtered_eq, filtered_etf


def run_screener(
    target_date: date | None = None,
    top_n: int = 20,
    shortlist_size: int = 40,
    use_llm_filter: bool = True,
) -> ScreenerResult:
    """Run the daily high-volatility screener.

    See the module docstring for the full pipeline description. This function
    is the only public entry point and never raises on network/LLM failures.

    Args:
        target_date: Trading day to screen. Defaults to the most recent
            weekday (UTC).
        top_n: Final number of names per group after LLM filter.
        shortlist_size: Number of names per group fed into the LLM stage.
        use_llm_filter: When ``False``, the LLM stage is skipped and the top
            ``top_n`` of the quant ranking is returned directly.

    Returns:
        A :class:`ScreenerResult` -- always well-formed, even on failure.
    """
    resolved_date = _most_recent_weekday(target_date)

    # ---- cache lookup ----
    cached = _cache_get(resolved_date)
    if cached is not None:
        return cached

    api_key = _polygon_api_key()
    if not api_key:
        return ScreenerResult(
            computed_at=datetime.now(timezone.utc),
            equities=[],
            etfs=[],
            equities_shortlist=[],
            etfs_shortlist=[],
            fetched_ok=False,
            error="POLYGON_API_KEY is not set in environment",
        )

    # ---- stage 1a: grouped daily ----
    try:
        raw_rows = _fetch_grouped_daily(resolved_date, api_key)
    except Exception as exc:  # noqa: BLE001
        return ScreenerResult(
            computed_at=datetime.now(timezone.utc),
            equities=[],
            etfs=[],
            equities_shortlist=[],
            etfs_shortlist=[],
            fetched_ok=False,
            error=f"grouped daily fetch failed: {exc}",
        )

    grouped = _parse_grouped_rows(raw_rows)
    liquid = _prefilter(grouped)
    if not liquid:
        return ScreenerResult(
            computed_at=datetime.now(timezone.utc),
            equities=[],
            etfs=[],
            equities_shortlist=[],
            etfs_shortlist=[],
            fetched_ok=False,
            error="no liquid tickers after prefilter",
        )

    # ---- stage 1b: proxy-sort to reduce history-fetch fanout ----
    liquid.sort(key=lambda r: r.proxy_range, reverse=True)
    candidates = liquid[:_INTERMEDIATE_TOP_K]

    # ---- stage 1c: parallel 25-day history fetch ----
    metrics: list[_Metrics] = []
    with ThreadPoolExecutor(max_workers=_HISTORY_WORKERS) as pool:
        futures = {
            pool.submit(_compute_metrics_for_row, row, resolved_date, api_key): row
            for row in candidates
        }
        for fut in as_completed(futures):
            try:
                m = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.debug("history worker raised: %s", exc)
                continue
            if m is not None:
                metrics.append(m)

    if not metrics:
        return ScreenerResult(
            computed_at=datetime.now(timezone.utc),
            equities=[],
            etfs=[],
            equities_shortlist=[],
            etfs_shortlist=[],
            fetched_ok=False,
            error="no per-ticker history fetched",
        )

    # ---- stage 1d: composite score, split groups ----
    ranked = _score_and_rank(metrics)
    ranked.sort(key=lambda r: r.composite_score, reverse=True)

    equities_short = [r for r in ranked if not r.is_etf][:shortlist_size]
    etfs_short = [r for r in ranked if r.is_etf][:shortlist_size]

    # ---- stage 2: LLM filter ----
    if use_llm_filter:
        equities_final, etfs_final = _apply_llm_filter(
            equities_short, etfs_short, top_n
        )
    else:
        equities_final = equities_short[:top_n]
        etfs_final = etfs_short[:top_n]

    result = ScreenerResult(
        computed_at=datetime.now(timezone.utc),
        equities=equities_final,
        etfs=etfs_final,
        equities_shortlist=equities_short,
        etfs_shortlist=etfs_short,
        fetched_ok=True,
        error=None,
    )

    try:
        _cache_put(resolved_date, result)
    except Exception as exc:  # noqa: BLE001 -- cache write is best-effort
        logger.warning("screener cache write failed: %s", exc)

    return result
