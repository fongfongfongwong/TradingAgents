"""Options analytics computations for the v3 materializer.

Pulls an option chain via yfinance (primary source) and derives a compact
set of risk / regime signals used by OptionsContext:

- Put/Call ratio  (open-interest weighted)
- IV rank percentile (current ATM IV vs. a 52-week rolling history)
- 25-delta skew  (put 25d IV - call 25d IV, in vol points)
- Max pain strike  (OI-weighted pin strike)
- Unusual activity summary  (volume >> open interest screen)

All network interactions are wrapped so that failures never propagate to the
caller; callers receive an OptionsAnalyticsResult with ``fetched_ok=False``
and a populated ``error`` field instead.

Design notes
------------
* No new runtime dependencies are introduced — the normal CDF used for the
  25-delta strike approximation is implemented with ``math.erf``.
* A process-local cache keyed by ``(ticker, YYYY-MM-DD)`` memoises results so
  the expensive option-chain pulls are only performed once per ticker per day.
* All returned objects are frozen dataclasses to preserve immutability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

__all__ = [
    "OptionsAnalyticsResult",
    "compute_options_analytics",
    "compute_max_pain",
    "find_unusual_activity",
]


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionsAnalyticsResult:
    """Immutable container for option-chain derived analytics.

    OI-based fields (``put_call_ratio`` etc.) come from yfinance; the
    trade-flow fields (``flow_put_call_ratio``, ``large_trade_bias``,
    ``trade_flow_source``) are populated when the paid Databento OPRA feed
    succeeds. All trade-flow fields default to ``None`` so the result stays
    compatible with callers that only care about the OI path.
    """

    put_call_ratio: float | None
    iv_rank_percentile: float | None
    iv_skew_25d: float | None
    max_pain_price: float | None
    unusual_activity_summary: str | None
    fetched_ok: bool
    error: str | None
    # Trade-flow enrichment (Databento OPRA, optional)
    flow_put_call_ratio: float | None = None
    large_trade_bias: float | None = None
    trade_flow_source: str | None = None


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

# Per-day memo of fully computed analytics to avoid re-fetching.
# Key: (ticker, YYYY-MM-DD)  Value: OptionsAnalyticsResult
_RESULT_CACHE: dict[tuple[str, str], OptionsAnalyticsResult] = {}

# Per-day memo of the 52-week IV rank percentile.  Computing it requires
# pulling weekly historical option chains, which is expensive.
# Key: (ticker, YYYY-MM-DD)  Value: float percentile or None
_IV_RANK_CACHE: dict[tuple[str, str], float | None] = {}


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_call_delta(
    spot: float, strike: float, t_years: float, sigma: float
) -> float:
    """Black-Scholes call delta (zero rate, zero dividend).

    Falls back to 0.5 if any input is degenerate.
    """
    if spot <= 0.0 or strike <= 0.0 or t_years <= 0.0 or sigma <= 0.0:
        return 0.5
    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * t_years) / (
        sigma * math.sqrt(t_years)
    )
    return _norm_cdf(d1)


# ---------------------------------------------------------------------------
# Max pain
# ---------------------------------------------------------------------------


def compute_max_pain(
    calls: list[tuple[float, float]],
    puts: list[tuple[float, float]],
) -> float | None:
    """Compute the max-pain strike.

    Parameters
    ----------
    calls, puts:
        Lists of ``(strike, open_interest)`` tuples.

    The loss incurred by option writers if the underlying settles at strike
    ``k`` is::

        pain(k) = Σ_{j < k} call_OI_j * (k - j)  +  Σ_{j > k} put_OI_j * (j - k)

    The returned strike is the one that *minimises* pain (i.e. writers lose
    the least, which is the magnet for spot at expiry under the max-pain
    hypothesis).
    """
    strikes: set[float] = set()
    for strike, _ in calls:
        strikes.add(float(strike))
    for strike, _ in puts:
        strikes.add(float(strike))
    if not strikes:
        return None

    ordered = sorted(strikes)
    best_strike: float | None = None
    best_pain: float | None = None

    for k in ordered:
        pain = 0.0
        for strike, oi in calls:
            if strike < k and oi > 0:
                pain += float(oi) * (k - float(strike))
        for strike, oi in puts:
            if strike > k and oi > 0:
                pain += float(oi) * (float(strike) - k)
        if best_pain is None or pain < best_pain:
            best_pain = pain
            best_strike = k

    return best_strike


# ---------------------------------------------------------------------------
# Unusual activity
# ---------------------------------------------------------------------------


def find_unusual_activity(
    ticker: str,
    calls_rows: list[dict[str, Any]],
    puts_rows: list[dict[str, Any]],
    *,
    volume_multiple: float = 5.0,
    min_open_interest: int = 100,
) -> str:
    """Flag option strikes where volume >> open interest.

    Returns a short human-readable summary string, or ``""`` when no strikes
    qualify.
    """
    hits: list[str] = []

    def _scan(rows: list[dict[str, Any]], side: str) -> None:
        for row in rows:
            try:
                vol = float(row.get("volume") or 0.0)
                oi = float(row.get("openInterest") or 0.0)
                strike = float(row.get("strike") or 0.0)
            except (TypeError, ValueError):
                continue
            if oi < min_open_interest or vol <= 0.0:
                continue
            if vol >= volume_multiple * oi:
                hits.append(
                    f"{ticker} {strike:g}{side} vol={int(vol)} oi={int(oi)}"
                )

    _scan(calls_rows, "C")
    _scan(puts_rows, "P")

    if not hits:
        return ""

    preview = "; ".join(hits[:3])
    return f"{len(hits)} unusual: {preview}"


# ---------------------------------------------------------------------------
# Chain helpers
# ---------------------------------------------------------------------------


def _parse_expiry(expiry_str: str) -> date | None:
    try:
        return datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _pick_expiry(expirations: tuple[str, ...], min_days: int = 7) -> str | None:
    """Pick the nearest expiry at least ``min_days`` in the future."""
    today = date.today()
    best: tuple[int, str] | None = None
    for exp in expirations:
        parsed = _parse_expiry(exp)
        if parsed is None:
            continue
        days = (parsed - today).days
        if days < min_days:
            continue
        if best is None or days < best[0]:
            best = (days, exp)
    if best is None and expirations:
        # Fall back to the latest available expiry if nothing is >= min_days.
        latest: tuple[int, str] | None = None
        for exp in expirations:
            parsed = _parse_expiry(exp)
            if parsed is None:
                continue
            days = (parsed - today).days
            if latest is None or days > latest[0]:
                latest = (days, exp)
        return latest[1] if latest is not None else None
    return best[1] if best is not None else None


def _rows_from_df(df: Any) -> list[dict[str, Any]]:
    """Convert a yfinance options DataFrame to a list of row dicts."""
    if df is None:
        return []
    try:
        records = df.to_dict(orient="records")
    except Exception:
        return []
    return list(records)


def _atm_iv(rows: list[dict[str, Any]], spot: float) -> float | None:
    """Return the implied vol of the strike closest to spot."""
    best: tuple[float, float] | None = None
    for row in rows:
        try:
            strike = float(row.get("strike") or 0.0)
            iv = float(row.get("impliedVolatility") or 0.0)
        except (TypeError, ValueError):
            continue
        if strike <= 0.0 or iv <= 0.0:
            continue
        dist = abs(strike - spot)
        if best is None or dist < best[0]:
            best = (dist, iv)
    return best[1] if best is not None else None


def _iv_for_target_call_delta(
    rows: list[dict[str, Any]],
    spot: float,
    t_years: float,
    target_delta: float,
) -> float | None:
    """Find the call IV whose Black-Scholes delta is closest to ``target_delta``."""
    best: tuple[float, float] | None = None
    for row in rows:
        try:
            strike = float(row.get("strike") or 0.0)
            iv = float(row.get("impliedVolatility") or 0.0)
        except (TypeError, ValueError):
            continue
        if strike <= 0.0 or iv <= 0.0:
            continue
        delta = _bs_call_delta(spot, strike, t_years, iv)
        dist = abs(delta - target_delta)
        if best is None or dist < best[0]:
            best = (dist, iv)
    return best[1] if best is not None else None


def _iv_for_target_put_delta(
    rows: list[dict[str, Any]],
    spot: float,
    t_years: float,
    target_delta: float,
) -> float | None:
    """Find the put IV whose delta is closest to ``target_delta`` (negative).

    Put delta = call delta - 1.
    """
    best: tuple[float, float] | None = None
    for row in rows:
        try:
            strike = float(row.get("strike") or 0.0)
            iv = float(row.get("impliedVolatility") or 0.0)
        except (TypeError, ValueError):
            continue
        if strike <= 0.0 or iv <= 0.0:
            continue
        call_delta = _bs_call_delta(spot, strike, t_years, iv)
        put_delta = call_delta - 1.0
        dist = abs(put_delta - target_delta)
        if best is None or dist < best[0]:
            best = (dist, iv)
    return best[1] if best is not None else None


# ---------------------------------------------------------------------------
# IV rank history (expensive, cached)
# ---------------------------------------------------------------------------


def _compute_iv_rank(
    ticker_obj: yf.Ticker,
    ticker: str,
    current_atm_iv: float | None,
    today: date,
) -> float | None:
    """Compute a percentile rank of ``current_atm_iv`` vs. a 52-week ATM IV history.

    Uses the ticker's realized volatility of weekly log returns over the last
    ~252 trading days as a proxy IV series.  This avoids the otherwise
    prohibitively expensive per-week option-chain refetch while still producing
    a reasonable rank signal.  If the underlying history is unavailable we
    return None.
    """
    cache_key = (ticker.upper(), today.isoformat())
    if cache_key in _IV_RANK_CACHE:
        cached = _IV_RANK_CACHE[cache_key]
        if cached is None:
            return None
        if current_atm_iv is None:
            return None
        return cached

    if current_atm_iv is None:
        _IV_RANK_CACHE[cache_key] = None
        return None

    try:
        hist = ticker_obj.history(period="1y")
        if hist is None or hist.empty:
            _IV_RANK_CACHE[cache_key] = None
            return None
        closes = [float(c) for c in hist["Close"].tolist() if c == c]
        if len(closes) < 40:
            _IV_RANK_CACHE[cache_key] = None
            return None

        # Rolling 20-trading-day annualised realised vol as a proxy IV series.
        proxy_ivs: list[float] = []
        window = 20
        for i in range(window, len(closes)):
            window_closes = closes[i - window : i + 1]
            rets = [
                math.log(window_closes[j] / window_closes[j - 1])
                for j in range(1, len(window_closes))
                if window_closes[j - 1] > 0.0 and window_closes[j] > 0.0
            ]
            if len(rets) < 5:
                continue
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
            realised = math.sqrt(var) * math.sqrt(252.0)
            if realised > 0.0:
                proxy_ivs.append(realised)

        if len(proxy_ivs) < 20:
            _IV_RANK_CACHE[cache_key] = None
            return None

        below = sum(1 for v in proxy_ivs if v <= current_atm_iv)
        percentile = (below / len(proxy_ivs)) * 100.0
        percentile = max(0.0, min(100.0, percentile))
        _IV_RANK_CACHE[cache_key] = percentile
        return percentile
    except Exception:
        _IV_RANK_CACHE[cache_key] = None
        return None


# ---------------------------------------------------------------------------
# Core entry point
# ---------------------------------------------------------------------------


def compute_options_analytics(
    ticker: str,
    spot_price: float,
) -> OptionsAnalyticsResult:
    """Fetch ``ticker``'s option chain and derive analytics.

    Parameters
    ----------
    ticker:
        Equity symbol to query (yfinance format).
    spot_price:
        Current underlying price, used for ATM and delta-bucket calculations.

    Returns
    -------
    OptionsAnalyticsResult
        All-optional numeric fields populated on a best-effort basis.  If any
        exception is raised by the data source, ``fetched_ok`` is False and
        ``error`` contains a short description; other fields will be ``None``.
    """
    ticker = (ticker or "").strip().upper()
    today = date.today()
    cache_key = (ticker, today.isoformat())
    if cache_key in _RESULT_CACHE:
        return _RESULT_CACHE[cache_key]

    if not ticker:
        result = OptionsAnalyticsResult(
            put_call_ratio=None,
            iv_rank_percentile=None,
            iv_skew_25d=None,
            max_pain_price=None,
            unusual_activity_summary=None,
            fetched_ok=False,
            error="empty ticker",
        )
        _RESULT_CACHE[cache_key] = result
        return result

    try:
        ticker_obj = yf.Ticker(ticker)
        expirations = tuple(ticker_obj.options or ())
        if not expirations:
            raise ValueError("no option expirations returned")

        expiry = _pick_expiry(expirations, min_days=7)
        if expiry is None:
            raise ValueError("no usable expiry >= 7d and no fallback")

        chain = ticker_obj.option_chain(expiry)
        calls_rows = _rows_from_df(getattr(chain, "calls", None))
        puts_rows = _rows_from_df(getattr(chain, "puts", None))
        if not calls_rows and not puts_rows:
            raise ValueError(f"empty option chain for {expiry}")

        # Put/call ratio — open-interest weighted (more stable than volume).
        calls_oi = sum(
            float(r.get("openInterest") or 0.0) for r in calls_rows
        )
        puts_oi = sum(
            float(r.get("openInterest") or 0.0) for r in puts_rows
        )
        if calls_oi > 0.0:
            pcr: float | None = round(puts_oi / calls_oi, 4)
        else:
            # Fall back to volume-based PCR if OI is zero across the board.
            calls_vol = sum(
                float(r.get("volume") or 0.0) for r in calls_rows
            )
            puts_vol = sum(
                float(r.get("volume") or 0.0) for r in puts_rows
            )
            pcr = (
                round(puts_vol / calls_vol, 4)
                if calls_vol > 0.0
                else None
            )

        # Max pain.
        call_pairs = [
            (float(r.get("strike") or 0.0), float(r.get("openInterest") or 0.0))
            for r in calls_rows
            if r.get("strike") is not None
        ]
        put_pairs = [
            (float(r.get("strike") or 0.0), float(r.get("openInterest") or 0.0))
            for r in puts_rows
            if r.get("strike") is not None
        ]
        max_pain = compute_max_pain(call_pairs, put_pairs)
        if max_pain is not None:
            max_pain = round(float(max_pain), 4)

        # 25-delta skew — requires a valid expiry date & positive spot.
        expiry_date = _parse_expiry(expiry)
        skew: float | None = None
        if expiry_date is not None and spot_price and spot_price > 0.0:
            t_years = max((expiry_date - today).days, 1) / 365.0
            call_iv_25 = _iv_for_target_call_delta(
                calls_rows, float(spot_price), t_years, 0.25
            )
            put_iv_25 = _iv_for_target_put_delta(
                puts_rows, float(spot_price), t_years, -0.25
            )
            if call_iv_25 is not None and put_iv_25 is not None:
                skew = round(put_iv_25 - call_iv_25, 6)

        # ATM IV for IV-rank input.
        atm_iv: float | None = None
        if spot_price and spot_price > 0.0:
            call_atm = _atm_iv(calls_rows, float(spot_price))
            put_atm = _atm_iv(puts_rows, float(spot_price))
            if call_atm is not None and put_atm is not None:
                atm_iv = (call_atm + put_atm) / 2.0
            else:
                atm_iv = call_atm if call_atm is not None else put_atm

        iv_rank = _compute_iv_rank(ticker_obj, ticker, atm_iv, today)
        if iv_rank is not None:
            iv_rank = round(float(iv_rank), 4)

        unusual = find_unusual_activity(ticker, calls_rows, puts_rows)

        # Databento trade-flow enrichment (best-effort, never blocks the
        # OI-based analytics). Returns None if the paid feed isn't wired.
        flow = _fetch_databento_flow(ticker, today)

        result = OptionsAnalyticsResult(
            put_call_ratio=pcr,
            iv_rank_percentile=iv_rank,
            iv_skew_25d=skew,
            max_pain_price=max_pain,
            unusual_activity_summary=unusual if unusual else None,
            fetched_ok=True,
            error=None,
            flow_put_call_ratio=(flow or {}).get("flow_put_call_ratio"),
            large_trade_bias=(flow or {}).get("large_trade_bias"),
            trade_flow_source=(flow or {}).get("trade_flow_source"),
        )
        _RESULT_CACHE[cache_key] = result
        return result
    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        result = OptionsAnalyticsResult(
            put_call_ratio=None,
            iv_rank_percentile=None,
            iv_skew_25d=None,
            max_pain_price=None,
            unusual_activity_summary=None,
            fetched_ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
        _RESULT_CACHE[cache_key] = result
        return result


def _reset_caches_for_tests() -> None:
    """Clear memoisation tables — intended for test isolation only."""
    _RESULT_CACHE.clear()
    _IV_RANK_CACHE.clear()
    _FLOW_CACHE.clear()


# ---------------------------------------------------------------------------
# Databento trade-flow enrichment (paid OPRA feed)
# ---------------------------------------------------------------------------


# Per-day memo of the trade-flow result so each ticker is only fetched once.
# Key: (ticker, YYYY-MM-DD)  Value: dict with {flow_pcr, large_trade_bias, source}
_FLOW_CACHE: dict[tuple[str, str], dict[str, Any] | None] = {}

# A single large trade is >= this many contracts — matches the threshold used
# by DatabentoOptionsConnector._fetch_flow for consistency across the system.
_LARGE_TRADE_THRESHOLD: int = 100


def _fetch_databento_flow(ticker: str, today: date) -> dict[str, Any] | None:
    """Fetch real-time trade-flow PCR and large-trade bias from Databento.

    Returns ``None`` when:

    * ``DATABENTO_API_KEY`` is not configured.
    * The ``databento`` package is not installed.
    * The connector raises for any reason (bad response, rate limit, etc.).

    A ``None`` return is not an error condition — it just means the caller
    should fall back to the yfinance-based OI fields without trade-flow
    enrichment. Success cases return a dict with ``flow_put_call_ratio``,
    ``large_trade_bias`` and ``trade_flow_source`` keys.
    """
    cache_key = (ticker, today.isoformat())
    if cache_key in _FLOW_CACHE:
        return _FLOW_CACHE[cache_key]

    import os

    if not os.environ.get("DATABENTO_API_KEY", "").strip():
        _FLOW_CACHE[cache_key] = None
        return None

    try:
        from tradingagents.dataflows.connectors.databento_options_connector import (
            DatabentoOptionsConnector,
        )

        connector = DatabentoOptionsConnector()
        connector.connect()
        payload = connector._fetch_impl(  # noqa: SLF001 — intentional internal call
            ticker,
            {"data_type": "flow", "large_trade_threshold": _LARGE_TRADE_THRESHOLD},
        )
    except Exception:  # noqa: BLE001 — any failure just disables enrichment
        _FLOW_CACHE[cache_key] = None
        return None

    flow_pcr = payload.get("put_call_ratio")
    if isinstance(flow_pcr, (int, float)):
        flow_pcr = round(float(flow_pcr), 4)
    else:
        flow_pcr = None

    # Large-trade bias in [-1, +1]: positive = call-heavy institutional flow,
    # negative = put-heavy. Normalised by total large-trade volume so the
    # metric is scale-free across tickers.
    large_call = float(payload.get("large_call_volume") or 0.0)
    large_put = float(payload.get("large_put_volume") or 0.0)
    large_total = large_call + large_put
    if large_total > 0.0:
        large_trade_bias: float | None = round(
            (large_call - large_put) / large_total, 4
        )
    else:
        large_trade_bias = None

    if flow_pcr is None and large_trade_bias is None:
        _FLOW_CACHE[cache_key] = None
        return None

    result = {
        "flow_put_call_ratio": flow_pcr,
        "large_trade_bias": large_trade_bias,
        "trade_flow_source": "databento",
    }
    _FLOW_CACHE[cache_key] = result
    return result


# Silence "imported but unused" for timedelta (kept for possible future use).
_ = timedelta
