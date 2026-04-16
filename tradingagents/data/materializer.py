"""TickerBriefing Materializer — Stage 0 of the v3 pipeline.

Fetches real-time market data via yfinance and produces a frozen
TickerBriefing snapshot. All computation is pure Python — no LLM calls.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

from tradingagents.data.sources.fred_macro import fetch_fred_macro
from tradingagents.data.sources.options_analytics import (
    compute_options_analytics,
)
from tradingagents.data.sources.regime_classifier import classify_regime
from tradingagents.schemas.v3 import (
    EventCalendar,
    FundamentalsContext,
    InstitutionalContext,
    KlineBar,
    MacroContext,
    NewsContext,
    OptionsContext,
    PriceContext,
    Regime,
    SocialContext,
    TickerBriefing,
    VolatilityContext,
    VolRegime,
)

# Simple word lists for headline sentiment scoring
_POSITIVE_WORDS = frozenset({
    "up", "gain", "gains", "rise", "rises", "rally", "rallies", "surge",
    "surges", "jump", "jumps", "soar", "soars", "positive", "beat", "beats",
    "bullish", "upgrade", "upgrades", "record", "profit", "profits", "growth",
    "strong", "higher", "boost", "boosts", "recover", "recovers", "recovery",
    "outperform", "outperforms", "optimistic", "buy",
})

_NEGATIVE_WORDS = frozenset({
    "down", "drop", "drops", "fall", "falls", "decline", "declines", "plunge",
    "plunges", "crash", "crashes", "loss", "losses", "negative", "miss",
    "misses", "bearish", "downgrade", "downgrades", "weak", "lower", "cut",
    "cuts", "sell", "selloff", "risk", "fear", "fears", "recession",
    "underperform", "underperforms", "pessimistic", "warning", "warnings",
})


# ------------------------------------------------------------------
# Technical indicator helpers
# ------------------------------------------------------------------


def _compute_sma(closes: list[float], window: int) -> float:
    """Simple moving average over the last *window* values."""
    if len(closes) < window:
        return 0.0
    return sum(closes[-window:]) / window


def _compute_rsi(closes: list[float], period: int = 14) -> float:
    """Relative Strength Index using exponential moving average of gains/losses."""
    if len(closes) < period + 1:
        return 50.0  # neutral default

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[bool, int]:
    """Return (macd_above_signal, crossover_days_ago).

    Uses exponential moving averages.
    """
    if len(closes) < slow + signal_period:
        return False, 0

    def _ema(data: list[float], span: int) -> list[float]:
        k = 2.0 / (span + 1)
        result = [data[0]]
        for val in data[1:]:
            result.append(val * k + result[-1] * (1.0 - k))
        return result

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal_period)

    above = macd_line[-1] > signal_line[-1]

    crossover_days = 0
    for i in range(len(macd_line) - 2, -1, -1):
        prev_above = macd_line[i] > signal_line[i]
        if prev_above != above:
            crossover_days = len(macd_line) - 1 - i
            break

    return above, crossover_days


def _compute_bollinger_position(
    closes: list[float], window: int = 20
) -> Literal["upper_third", "middle_third", "lower_third"]:
    """Where the current price sits relative to Bollinger Bands (20, 2)."""
    if len(closes) < window:
        return "middle_third"

    sma = sum(closes[-window:]) / window
    variance = sum((c - sma) ** 2 for c in closes[-window:]) / window
    std = math.sqrt(variance) if variance > 0 else 0.0001

    upper = sma + 2 * std
    lower = sma - 2 * std

    band_range = upper - lower
    if band_range == 0:
        return "middle_third"

    position = (closes[-1] - lower) / band_range

    if position > 0.6667:
        return "upper_third"
    if position < 0.3333:
        return "lower_third"
    return "middle_third"


def _compute_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float:
    """Average True Range over *period* days."""
    if len(closes) < period + 1:
        return 0.0

    true_ranges: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return 0.0

    return sum(true_ranges[-period:]) / period


def _compute_realized_vol_20d(closes: list[float]) -> float | None:
    """Annualized realized volatility of 20-day log returns, as a percent.

    Computes ``stdev(log(C_t / C_{t-1})) * sqrt(252) * 100`` over the last
    20 log-returns. Returns ``None`` when fewer than 21 closes are available
    (need 21 to form 20 log returns). Returns ``0.0`` when the window has
    zero variance (e.g. flat/halted prices).
    """
    if len(closes) < 21:
        return None
    arr = np.asarray(closes[-21:], dtype=float)
    # Guard against non-positive prices that would break log().
    if np.any(arr <= 0.0):
        return None
    log_returns = np.diff(np.log(arr))
    if log_returns.size < 2:
        return None
    # ddof=1 -> sample stdev, matching pandas' default.
    stdev = float(np.std(log_returns, ddof=1))
    return round(stdev * math.sqrt(252.0) * 100.0, 4)


def _pct_change(old: float, new: float) -> float:
    """Percentage change from *old* to *new*."""
    if old == 0.0:
        return 0.0
    return ((new - old) / abs(old)) * 100.0


# ------------------------------------------------------------------
# Sentiment helper
# ------------------------------------------------------------------


def _score_headline(headline: str) -> float:
    """Score a headline between -1.0 and 1.0 using keyword counting."""
    words = set(headline.lower().split())
    pos = len(words & _POSITIVE_WORDS)
    neg = len(words & _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


# ------------------------------------------------------------------
# Context builders
# ------------------------------------------------------------------


def _get_price_vendor() -> str:
    """Return the configured price vendor, defaulting to ``yfinance``.

    Reads from the runtime config set via ``PUT /api/config/runtime``. If
    the config module is unavailable (e.g. unit tests importing the
    materializer in isolation), defaults to ``"yfinance"`` so the legacy
    code path is preserved.
    """
    try:
        from tradingagents.api.routes.config import get_runtime_config

        return get_runtime_config().data_vendor_price
    except Exception:
        return "yfinance"


def _empty_price_context(fetch_start: float) -> PriceContext:
    """Return a neutral PriceContext used when the history fetch fails."""
    return PriceContext(
        price=0.0,
        change_1d_pct=0.0,
        change_5d_pct=0.0,
        change_20d_pct=0.0,
        sma_20=0.0,
        sma_50=0.0,
        sma_200=0.0,
        rsi_14=50.0,
        macd_above_signal=False,
        macd_crossover_days=0,
        bollinger_position="middle_third",
        volume_vs_avg_20d=1.0,
        atr_14=0.0,
        data_age_seconds=int(time.time() - fetch_start),
    )


def _is_historical_as_of(as_of_date: str | None) -> bool:
    """Return True when ``as_of_date`` is more than 2 days before today UTC.

    Used to decide whether to use "point-in-time" vendor fetches (explicit
    date windows) instead of the default "most recent" behaviour. A 2-day
    buffer avoids bouncing between code paths for the current trading day
    due to timezone edges.
    """
    if not as_of_date:
        return False
    try:
        parsed = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    today = datetime.now(timezone.utc).date()
    return (today - parsed).days > 2


def _fetch_price_history(
    ticker: str,
    ticker_obj: yf.Ticker,
    data_gaps: list[str],
    as_of_date: str | None = None,
) -> pd.DataFrame | None:
    """Fetch 1-year OHLCV history, dispatching to the configured vendor.

    Returns a DataFrame with ``Open/High/Low/Close/Volume`` columns on
    success, or ``None`` when every vendor cascade failed. Failure reasons
    are tagged on ``data_gaps`` using the same namespaced format that
    previously lived inline in :func:`_build_price_context`.

    When ``as_of_date`` is a historical date (more than 2 days in the past)
    the underlying vendor fetches are pinned to that date so no future data
    leaks into backtests. ``None`` or today's date preserves the original
    live behaviour.
    """
    vendor = _get_price_vendor()
    historical = _is_historical_as_of(as_of_date)

    hist: pd.DataFrame | None = None
    if vendor == "polygon":
        from tradingagents.data.sources import polygon_price as polygon_source

        polygon_result = polygon_source.fetch_polygon_price_history(
            ticker, period="1y", as_of_date=as_of_date if historical else None
        )
        if (
            polygon_result.fetched_ok
            and polygon_result.df is not None
            and len(polygon_result.df) >= 50
        ):
            hist = polygon_result.df
        else:
            reason = polygon_result.error or "empty"
            data_gaps.append(f"price:polygon_fallback:{reason}")
    elif vendor == "alpha_vantage":
        from tradingagents.data.sources import (
            alpha_vantage_price as alpha_vantage_source,
        )

        av_result = alpha_vantage_source.fetch_alpha_vantage_price_history(
            ticker, period="1y"
        )
        if (
            av_result.fetched_ok
            and av_result.df is not None
            and len(av_result.df) >= 50
        ):
            hist = av_result.df
            # Alpha Vantage returns full history regardless of period — slice
            # defensively so historical backtests don't leak future bars.
            if historical and as_of_date is not None:
                hist = _slice_to_as_of(hist, as_of_date)
        else:
            reason = av_result.error or "empty"
            data_gaps.append(f"price:alpha_vantage_fallback:{reason}")

    if hist is None:
        try:
            if historical and as_of_date is not None:
                end_dt = datetime.strptime(as_of_date, "%Y-%m-%d").date()
                start_dt = end_dt - timedelta(days=365)
                hist = ticker_obj.history(
                    start=start_dt.isoformat(), end=end_dt.isoformat()
                )
            else:
                hist = ticker_obj.history(period="1y")
            if hist.empty:
                raise ValueError("Empty history")
        except Exception:
            data_gaps.append("price:history")
            return None

    return hist


def _slice_to_as_of(df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """Return rows of ``df`` whose index is on or before ``as_of_date``.

    Guards against vendors that return post-cutoff bars when passed a
    historical backtest date. Assumes a DatetimeIndex — returns ``df``
    unchanged if that precondition is not met.
    """
    try:
        cutoff = pd.Timestamp(as_of_date)
        if df.index.tz is not None and cutoff.tz is None:
            cutoff = cutoff.tz_localize(df.index.tz)
        return df[df.index <= cutoff]
    except Exception:
        return df


def _build_price_context(
    ticker: str,
    ticker_obj: yf.Ticker,
    data_gaps: list[str],
    hist: pd.DataFrame | None = None,
) -> PriceContext:
    """Build PriceContext, dispatching to the configured price vendor.

    If ``hist`` is provided (as happens in :func:`materialize_briefing`
    where the history is fetched once and shared with
    :func:`_build_volatility_context`), it is used directly. Otherwise the
    function calls :func:`_fetch_price_history` to do a full vendor
    cascade — preserving the legacy three-arg call signature used by
    existing unit tests.
    """
    fetch_start = time.time()

    if hist is None:
        hist = _fetch_price_history(ticker, ticker_obj, data_gaps)
    if hist is None:
        return _empty_price_context(fetch_start)

    closes = hist["Close"].tolist()
    highs = hist["High"].tolist()
    lows = hist["Low"].tolist()
    volumes = hist["Volume"].tolist()

    current_price = closes[-1] if closes else 0.0

    change_1d = _pct_change(closes[-2], closes[-1]) if len(closes) >= 2 else 0.0
    change_5d = _pct_change(closes[-6], closes[-1]) if len(closes) >= 6 else 0.0
    change_20d = _pct_change(closes[-21], closes[-1]) if len(closes) >= 21 else 0.0

    sma_20 = _compute_sma(closes, 20)
    sma_50 = _compute_sma(closes, 50)
    sma_200 = _compute_sma(closes, 200)

    rsi_14 = _compute_rsi(closes, 14)

    macd_above, macd_cross_days = _compute_macd(closes)

    boll_pos = _compute_bollinger_position(closes)

    avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1.0
    vol_ratio = volumes[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0

    atr_14 = _compute_atr(highs, lows, closes)

    realized_vol_20d_pct = _compute_realized_vol_20d(closes)
    atr_pct_of_price: float | None = None
    if atr_14 > 0.0 and current_price > 0.0:
        atr_pct_of_price = round((atr_14 / current_price) * 100.0, 4)

    # ------------------------------------------------------------------
    # Intraday (5-min bars, last trading day)
    # ------------------------------------------------------------------
    intraday_rsi: float | None = None
    intraday_macd_above: bool | None = None
    intraday_vwap_pos: str | None = None
    intraday_change: float | None = None

    try:
        intraday = yf.download(ticker, period="1d", interval="5m", progress=False)
        if intraday is not None and not intraday.empty:
            # Flatten MultiIndex columns that yfinance sometimes returns
            if hasattr(intraday.columns, "nlevels") and intraday.columns.nlevels > 1:
                intraday.columns = intraday.columns.droplevel(1)

            intra_closes = intraday["Close"].dropna().tolist()

            # RSI-14 on 5-min bars
            if len(intra_closes) >= 14:
                intraday_rsi = round(_compute_rsi(intra_closes, 14), 4)

            # MACD on 5-min bars
            if len(intra_closes) >= 35:  # need slow(26) + signal(9)
                intraday_macd_above, _ = _compute_macd(intra_closes)

            # VWAP position
            if "Volume" in intraday.columns and len(intra_closes) > 0:
                typical = (
                    intraday["High"] + intraday["Low"] + intraday["Close"]
                ) / 3
                cumvol = intraday["Volume"].cumsum()
                vwap = (typical * intraday["Volume"]).cumsum() / cumvol.replace(
                    0, float("nan")
                )
                last_vwap = vwap.dropna()
                if not last_vwap.empty:
                    intraday_vwap_pos = (
                        "above"
                        if intra_closes[-1] > float(last_vwap.iloc[-1])
                        else "below"
                    )

            # Change from open
            if len(intra_closes) >= 2 and intra_closes[0] > 0:
                intraday_change = round(
                    (intra_closes[-1] - intra_closes[0]) / intra_closes[0] * 100.0,
                    4,
                )
    except Exception:
        logger.debug("Intraday fetch failed for %s; fields will be None", ticker)

    data_age = int(time.time() - fetch_start)

    return PriceContext(
        price=round(current_price, 4),
        change_1d_pct=round(change_1d, 4),
        change_5d_pct=round(change_5d, 4),
        change_20d_pct=round(change_20d, 4),
        sma_20=round(sma_20, 4),
        sma_50=round(sma_50, 4),
        sma_200=round(sma_200, 4),
        rsi_14=round(rsi_14, 4),
        macd_above_signal=macd_above,
        macd_crossover_days=macd_cross_days,
        bollinger_position=boll_pos,
        volume_vs_avg_20d=round(vol_ratio, 4),
        atr_14=round(atr_14, 4),
        realized_vol_20d_pct=realized_vol_20d_pct,
        atr_pct_of_price=atr_pct_of_price,
        intraday_rsi_14=intraday_rsi,
        intraday_macd_above_signal=intraday_macd_above,
        intraday_vwap_position=intraday_vwap_pos,
        intraday_change_pct=intraday_change,
        data_age_seconds=data_age,
    )


# ------------------------------------------------------------------
# Volatility helpers
# ------------------------------------------------------------------


def compute_realized_vol_pct(returns: pd.Series) -> float | None:
    """Annualized realized volatility in percent.

    ``returns`` is a pandas Series of periodic (typically daily) log
    returns. The formula is ``returns.std(ddof=1) * sqrt(252) * 100``.

    Returns ``None`` when there are fewer than 2 observations OR when the
    variance is zero (flat / halted prices). Returning ``None`` on zero
    variance — rather than ``0.0`` — lets callers distinguish "not enough
    data / degenerate" from a genuine low-vol reading.
    """
    if returns is None or len(returns) < 2:
        return None
    clean = returns.dropna()
    if len(clean) < 2:
        return None
    stdev = float(clean.std(ddof=1))
    if not math.isfinite(stdev) or stdev <= 0.0:
        return None
    return round(stdev * math.sqrt(252.0) * 100.0, 4)


def compute_bollinger_width_pct(
    close: pd.Series, period: int = 20
) -> float | None:
    """Bollinger-band width as a percent of the middle band.

    ``width = (upper - lower) / middle * 100`` where
    ``upper = SMA(period) + 2*STD(period)`` and
    ``lower = SMA(period) - 2*STD(period)``.

    Returns ``None`` when there is not enough data, or when the middle
    band is zero (avoids divide-by-zero). A flat series returns ``0.0``
    because ``upper == lower``.
    """
    if close is None or len(close) < period:
        return None
    window = close.iloc[-period:].astype(float)
    middle = float(window.mean())
    if middle == 0.0 or not math.isfinite(middle):
        return None
    stdev = float(window.std(ddof=0))
    if not math.isfinite(stdev):
        return None
    upper = middle + 2.0 * stdev
    lower = middle - 2.0 * stdev
    return round((upper - lower) / middle * 100.0, 4)


def compute_vol_percentile(
    current_vol: float, vol_series: pd.Series
) -> float | None:
    """Percentile rank (0-100) of ``current_vol`` within ``vol_series``.

    Uses the fraction of observations strictly less than or equal to
    ``current_vol``. Returns ``None`` when the series is empty or all NaN.
    """
    if vol_series is None or len(vol_series) == 0:
        return None
    clean = vol_series.dropna()
    if len(clean) == 0:
        return None
    if current_vol is None or not math.isfinite(float(current_vol)):
        return None
    rank = float((clean <= float(current_vol)).sum())
    return round(rank / float(len(clean)) * 100.0, 4)


def classify_vol_regime(realized_vol_20d_pct: float | None) -> VolRegime:
    """Map a 20-day annualized realized vol reading to a VolRegime.

    Thresholds (annualized percent):
        * ``< 15``  -> LOW
        * ``15-30`` -> NORMAL
        * ``30-60`` -> HIGH
        * ``> 60``  -> EXTREME
    ``None`` maps to NORMAL so downstream consumers always see a value.
    """
    if realized_vol_20d_pct is None or not math.isfinite(
        float(realized_vol_20d_pct)
    ):
        return VolRegime.NORMAL
    v = float(realized_vol_20d_pct)
    if v < 15.0:
        return VolRegime.LOW
    if v < 30.0:
        return VolRegime.NORMAL
    if v < 60.0:
        return VolRegime.HIGH
    return VolRegime.EXTREME


def extract_kline_last_n(hist: pd.DataFrame, n: int = 20) -> list[KlineBar]:
    """Convert the last ``n`` rows of ``hist`` into a list of :class:`KlineBar`.

    ``hist`` is expected to have columns ``Open/High/Low/Close/Volume`` and
    a datetime-like index. Returns an empty list if ``hist`` is empty or
    missing required columns.
    """
    if hist is None or len(hist) == 0:
        return []
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(hist.columns)):
        return []
    tail = hist.iloc[-n:]
    bars: list[KlineBar] = []
    for idx, row in tail.iterrows():
        try:
            if hasattr(idx, "strftime"):
                date_str = idx.strftime("%Y-%m-%d")
            else:
                date_str = str(idx)[:10]
            bars.append(
                KlineBar(
                    date=date_str,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
                )
            )
        except Exception:
            # Skip malformed rows rather than failing the whole briefing.
            continue
    return bars


def _align_features_to_model(
    features: pd.DataFrame,
    model: object,
    options_ctx: "OptionsContext | None" = None,
) -> pd.DataFrame:
    """Return a feature frame aligned to ``model.feature_names``.

    Defensive behaviour:

    * Columns the model does not know about are silently dropped (supports
      old smoke-trained models that only carry the 10 legacy HAR factors).
    * Columns the model requires but which are missing in ``features`` are
      filled with NaN (``predict`` will then drop the row via its own
      ``dropna`` -- callers should treat an empty result as "no prediction"
      rather than crashing).
    * When ``options_ctx`` is provided, known options fields are attached to
      the feature row under their canonical names; only fields the model
      expects are kept, everything else is discarded.

    This helper never raises: it is called from inside a try/except that
    already tags failures via ``data_gaps``.
    """
    model_features = tuple(getattr(model, "feature_names", ()) or ())
    if not model_features:
        return features

    aligned = features.copy()

    # Try-attach options features the model may know about. Missing
    # attributes fall through to NaN so predict() can drop the row instead
    # of crashing.
    if options_ctx is not None:
        options_field_map: dict[str, object] = {
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

    # Fill missing model columns with NaN rather than raising KeyError in
    # predict(). This also keeps old extended models loadable against a
    # factor module that has not yet shipped every expected column.
    for col in model_features:
        if col not in aligned.columns:
            aligned[col] = float("nan")

    # Project down to exactly the columns the model expects. predict() will
    # run preprocessing on these columns only.
    return aligned[list(model_features)]


def _invert_target_transform(raw_pred: float, model: object) -> float:
    """Apply the inverse of the model's training-time target transform.

    Supported ``target_transform`` values:

    * ``"log"`` -- the model was trained on ``log(y)``, so the inference
      output is inverted via :func:`numpy.exp` before downstream
      annualization.
    * ``"raw"``, ``None``, or missing attribute -- returns the raw
      prediction unchanged (legacy behaviour).

    Unknown transform strings are treated as raw with a warning so inference
    never crashes on a model generation that introduced a new transform
    without updating the inference path.
    """
    transform = getattr(model, "target_transform", None)
    if transform is None or transform == "raw":
        return float(raw_pred)
    if transform == "log":
        return float(np.exp(raw_pred))
    logger.warning(
        "Unknown target_transform=%r on model; returning raw prediction",
        transform,
    )
    return float(raw_pred)


def _compute_rv_forecast(
    ticker: str,
    hist: pd.DataFrame | None,
    data_gaps: list[str],
    options_ctx: "OptionsContext | None" = None,
) -> tuple[
    float | None,
    float | None,
    str | None,
    float | None,
    str | None,
]:
    """Compute 1d + 5d RV forecasts using the HAR-RV Ridge baseline model.

    Returns a tuple
    ``(pred_1d_pct, pred_5d_pct, model_version, delta_1d_pct, feature_set_version)``
    where each element may be ``None`` when the model or features are
    unavailable. Never raises: every failure path is tagged via
    ``data_gaps`` so the briefing still materializes.

    The delta is returned as ``None`` here; the caller is expected to compute
    it against the already-built :class:`VolatilityContext` so we don't
    double-count the realized-vol calculation.

    When ``options_ctx`` is supplied, the function will try to attach the
    standard options analytics columns (``iv_skew_25d``,
    ``iv_rank_percentile``, ``put_call_ratio``, ``iv_level_30d``) to the
    feature row, but only if the loaded model was trained on them. Old
    smoke-trained models (10 legacy factors only) remain fully supported.
    """
    try:
        from tradingagents.models.har_rv_ridge import load_model, predict  # type: ignore
        from tradingagents.factors.har_rv_factors import (  # type: ignore
            compute_har_factors,
        )
        # FEATURE_NAMES may include Tier 0 extended columns in newer versions
        # of har_rv_factors; fall back to the legacy subset on import error.
        try:
            from tradingagents.factors.har_rv_factors import (  # type: ignore
                FEATURE_NAMES,
            )
        except Exception:  # noqa: BLE001
            FEATURE_NAMES = (
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
    except Exception:  # noqa: BLE001 - module may not exist yet in Round 1
        data_gaps.append("rv_forecast:module_import_failed")
        return None, None, None, None, None

    if hist is None or len(hist) < 60:
        data_gaps.append("rv_forecast:insufficient_history")
        return None, None, None, None, None

    try:
        ohlc = hist.rename(columns=str.lower)
        required = {"open", "high", "low", "close"}
        if not required.issubset(set(ohlc.columns)):
            data_gaps.append("rv_forecast:missing_ohlc_columns")
            return None, None, None, None, None

        features = compute_har_factors(ohlc)

        # Drop NaN only on the legacy subset that the old smoke-trained
        # model relies on. This keeps Tier 0 rows that may legitimately be
        # all-NaN early in the history.
        legacy_subset = [
            c for c in FEATURE_NAMES if c in features.columns
        ]
        last = features.tail(1).dropna(subset=legacy_subset) if legacy_subset else features.tail(1)
        if last.empty:
            data_gaps.append("rv_forecast:features_all_nan")
            return None, None, None, None, None

        # predict() expects a MultiIndex panel (date, ticker). Wrap the
        # single-row feature frame so inference matches training layout.
        last_date = last.index[0]
        last = last.copy()
        last.index = pd.MultiIndex.from_tuples(
            [(last_date, ticker.upper())], names=["date", "ticker"]
        )

        model_1d = load_model(horizon=1)
        model_5d = load_model(horizon=5)

        pred_1d: float | None = None
        pred_5d: float | None = None
        model_version: str | None = None
        feature_set_version: str | None = None

        # Model output is daily Garman-Klass RV in return space (e.g. 0.015
        # = 1.5%/day). Annualize: daily_vol * sqrt(252) * 100 to match
        # realized_vol_20d_pct units.
        _ANNUALIZE = math.sqrt(252.0) * 100.0

        if model_1d is not None:
            aligned_1d = _align_features_to_model(last, model_1d, options_ctx)
            pred_series_1d = predict(model_1d, aligned_1d)
            if len(pred_series_1d) > 0:
                raw_1d = float(pred_series_1d.iloc[0])
                inverted_1d = _invert_target_transform(raw_1d, model_1d)
                pred_1d = round(inverted_1d * _ANNUALIZE, 4)
            trained_at = getattr(model_1d, "trained_at", "") or ""
            model_version = (
                f"har_rv_ridge_v1_{trained_at[:10]}"
                if trained_at
                else "har_rv_ridge_v1"
            )
            feature_set_version = getattr(model_1d, "feature_set_version", None)

        if model_5d is not None:
            aligned_5d = _align_features_to_model(last, model_5d, options_ctx)
            pred_series_5d = predict(model_5d, aligned_5d)
            if len(pred_series_5d) > 0:
                raw_5d = float(pred_series_5d.iloc[0])
                inverted_5d = _invert_target_transform(raw_5d, model_5d)
                pred_5d = round(inverted_5d * _ANNUALIZE, 4)
            if model_version is None:
                trained_at = getattr(model_5d, "trained_at", "") or ""
                model_version = (
                    f"har_rv_ridge_v1_{trained_at[:10]}"
                    if trained_at
                    else "har_rv_ridge_v1"
                )
            if feature_set_version is None:
                feature_set_version = getattr(
                    model_5d, "feature_set_version", None
                )

        if pred_1d is None and pred_5d is None:
            data_gaps.append("rv_forecast:no_models_loaded")
            return None, None, None, None, None

        return pred_1d, pred_5d, model_version, None, feature_set_version
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.warning("RV forecast computation failed for %s: %s", ticker, exc)
        data_gaps.append(f"rv_forecast:error:{exc}")
        return None, None, None, None, None


def _build_volatility_context(
    hist: pd.DataFrame | None,
    options_iv_rank: float | None,
    data_gaps: list[str],
    ticker: str | None = None,
    options_ctx: OptionsContext | None = None,
) -> VolatilityContext:
    """Build a :class:`VolatilityContext` from the shared price history.

    ``hist`` is the same DataFrame consumed by :func:`_build_price_context`
    so we avoid a second upstream fetch. On any failure we append
    ``volatility:*`` entries to ``data_gaps`` and return a default
    VolatilityContext with ``options_iv_rank`` propagated so the UI can
    still surface IV rank alongside realized-vol columns.
    """
    fetch_start = time.time()
    default = VolatilityContext(
        iv_rank_percentile=options_iv_rank,
        data_age_seconds=int(time.time() - fetch_start),
    )
    if hist is None or len(hist) == 0:
        data_gaps.append("volatility:no_history")
        return default
    if "Close" not in hist.columns:
        data_gaps.append("volatility:missing_close")
        return default

    try:
        close = hist["Close"].astype(float)
        close = close[close > 0.0]  # guard log()
        if len(close) < 2:
            data_gaps.append("volatility:insufficient_data")
            return default

        log_returns = np.log(close / close.shift(1)).dropna()

        rv_5d = (
            compute_realized_vol_pct(log_returns.iloc[-5:])
            if len(log_returns) >= 5
            else None
        )
        rv_20d = (
            compute_realized_vol_pct(log_returns.iloc[-20:])
            if len(log_returns) >= 20
            else None
        )
        rv_60d = (
            compute_realized_vol_pct(log_returns.iloc[-60:])
            if len(log_returns) >= 60
            else None
        )

        # ATR % of price using the shared history — reuse _compute_atr.
        atr_pct: float | None = None
        try:
            highs = hist["High"].tolist()
            lows = hist["Low"].tolist()
            closes_list = hist["Close"].tolist()
            atr_14 = _compute_atr(highs, lows, closes_list, period=14)
            last_price = float(closes_list[-1]) if closes_list else 0.0
            if atr_14 > 0.0 and last_price > 0.0:
                atr_pct = round(atr_14 / last_price * 100.0, 4)
        except Exception:
            atr_pct = None

        bb_width = compute_bollinger_width_pct(close, period=20)

        # 1-year percentile of the current 20d realized vol. We build a
        # rolling 20d-realized-vol series and rank the latest value.
        vol_pct_1y: float | None = None
        if rv_20d is not None and len(log_returns) >= 40:
            rolling_stdev = log_returns.rolling(window=20).std(ddof=1)
            rolling_vol = rolling_stdev * math.sqrt(252.0) * 100.0
            rolling_vol = rolling_vol.dropna()
            # Take up to the last 252 trading days (~1y).
            history_window = rolling_vol.iloc[-252:] if len(rolling_vol) > 0 else rolling_vol
            vol_pct_1y = compute_vol_percentile(rv_20d, history_window)

        regime = classify_vol_regime(rv_20d)
        kline = extract_kline_last_n(hist, n=20)

        # HAR-RV Ridge forecast integration. Failures are tagged in
        # ``data_gaps`` via _compute_rv_forecast; we never raise here.
        pred_1d_pct: float | None = None
        pred_5d_pct: float | None = None
        model_version: str | None = None
        forecast_delta_pct: float | None = None
        feature_set_version: str | None = None
        if ticker:
            (
                pred_1d_pct,
                pred_5d_pct,
                model_version,
                _,
                feature_set_version,
            ) = _compute_rv_forecast(ticker, hist, data_gaps, options_ctx=options_ctx)
            if pred_1d_pct is not None and rv_20d is not None:
                forecast_delta_pct = round(float(pred_1d_pct) - float(rv_20d), 4)

        return VolatilityContext(
            realized_vol_5d_pct=rv_5d,
            realized_vol_20d_pct=rv_20d,
            realized_vol_60d_pct=rv_60d,
            atr_14_pct_of_price=atr_pct,
            bollinger_band_width_pct=bb_width,
            iv_rank_percentile=options_iv_rank,
            vol_regime=regime,
            vol_percentile_1y=vol_pct_1y,
            kline_last_20=kline,
            data_age_seconds=int(time.time() - fetch_start),
            predicted_rv_1d_pct=pred_1d_pct,
            predicted_rv_5d_pct=pred_5d_pct,
            rv_forecast_model_version=model_version,
            rv_forecast_delta_pct=forecast_delta_pct,
            rv_forecast_feature_set_version=feature_set_version,
        )
    except Exception as exc:  # noqa: BLE001 - defensive: never break briefing
        data_gaps.append(f"volatility:compute_failed:{exc}")
        return default


def _build_options_context(
    ticker: str,
    ticker_obj: yf.Ticker,
    price_context: PriceContext,
    data_gaps: list[str],
) -> OptionsContext:
    """Build OptionsContext from nearest-expiration option chain.

    Primary path delegates to ``compute_options_analytics`` which populates
    all five analytics fields (PCR, IV rank, 25-delta skew, max pain, and
    unusual-activity summary).  If that call reports ``fetched_ok=False``
    we fall back to the legacy yfinance volume-based put/call ratio and tag
    ``options:analytics_fallback`` in ``data_gaps``.
    """
    fetch_start = time.time()
    spot_price = float(price_context.price or 0.0)

    analytics = compute_options_analytics(ticker, spot_price)
    if analytics.fetched_ok:
        return OptionsContext(
            put_call_ratio=analytics.put_call_ratio,
            iv_rank_percentile=analytics.iv_rank_percentile,
            iv_skew_25d=analytics.iv_skew_25d,
            max_pain_price=analytics.max_pain_price,
            unusual_activity_summary=analytics.unusual_activity_summary or "",
            data_age_seconds=int(time.time() - fetch_start),
            flow_put_call_ratio=analytics.flow_put_call_ratio,
            large_trade_bias=analytics.large_trade_bias,
            trade_flow_source=analytics.trade_flow_source,
        )

    # Analytics pipeline failed — mark and try the legacy yfinance path.
    data_gaps.append("options:analytics_fallback")
    try:
        expirations = ticker_obj.options
        if not expirations:
            raise ValueError("No option expirations available")

        chain = ticker_obj.option_chain(expirations[0])
        calls_vol = chain.calls["volume"].sum()
        puts_vol = chain.puts["volume"].sum()

        pcr = float(puts_vol / calls_vol) if calls_vol > 0 else None

        data_age = int(time.time() - fetch_start)
        return OptionsContext(
            put_call_ratio=round(pcr, 4) if pcr is not None else None,
            data_age_seconds=data_age,
        )
    except Exception:
        data_gaps.append("options:chain")
        return OptionsContext(data_age_seconds=int(time.time() - fetch_start))


def _build_news_context_yfinance(
    ticker_obj: yf.Ticker, data_gaps: list[str], fetch_start: float
) -> NewsContext:
    """Fallback NewsContext builder that uses yfinance's news feed.

    Returns a best-effort NewsContext; on failure appends ``news:headlines``
    to ``data_gaps`` and returns an empty NewsContext with a data_age stamp.
    """
    try:
        news_items = ticker_obj.news
        if not news_items:
            raise ValueError("No news available")

        # Filter stale headlines (older than 24 hours)
        max_age_seconds = 24 * 3600
        now_ts = time.time()
        fresh_items: list[dict] = []
        for item in news_items:
            pub_ts = item.get("providerPublishTime")
            if pub_ts is not None:
                try:
                    if (now_ts - float(pub_ts)) <= max_age_seconds:
                        fresh_items.append(item)
                except (ValueError, TypeError):
                    fresh_items.append(item)  # Keep if timestamp unparseable
            else:
                fresh_items.append(item)  # Keep if no timestamp
        if not fresh_items:
            fresh_items = list(news_items[:5])  # Fallback: keep newest 5

        headlines: list[str] = []
        for item in fresh_items[:5]:
            title = item.get("title", "")
            if not title:
                content = item.get("content", {})
                if isinstance(content, dict):
                    title = content.get("title", "")
            if title:
                headlines.append(title)

        if not headlines:
            raise ValueError("No headlines extracted")

        scores = [_score_headline(h) for h in headlines]
        avg_sentiment = sum(scores) / len(scores) if scores else 0.0

        data_age = int(time.time() - fetch_start)
        return NewsContext(
            top_headlines=headlines[:5],
            headline_sentiment_avg=round(avg_sentiment, 4),
            data_age_seconds=data_age,
        )
    except Exception:
        data_gaps.append("news:headlines")
        return NewsContext(data_age_seconds=int(time.time() - fetch_start))


def _build_news_context(
    ticker_obj: yf.Ticker,
    ticker: str,
    date: str,
    data_gaps: list[str],
) -> NewsContext:
    """Build NewsContext, preferring Finnhub (structured events + sentiment)
    and falling back to yfinance headlines if Finnhub is unavailable.
    """
    # Import lazily so tests can monkeypatch ``fetch_finnhub_news`` on the
    # source module without circular-import concerns.
    from tradingagents.data.sources import finnhub_news as finnhub_news_source

    fetch_start = time.time()
    try:
        finnhub_result = finnhub_news_source.fetch_finnhub_news(ticker, date)
    except Exception as exc:
        # Defensive: ``fetch_finnhub_news`` is designed never to raise, but
        # we never want the materializer to crash on news.
        data_gaps.append(f"news:finnhub_fallback:exception:{exc}")
        return _build_news_context_yfinance(ticker_obj, data_gaps, fetch_start)

    if not finnhub_result.fetched_ok:
        reason = finnhub_result.error or "unknown_error"
        data_gaps.append(f"news:finnhub_fallback:{reason}")
        return _build_news_context_yfinance(ticker_obj, data_gaps, fetch_start)

    data_age = int(time.time() - fetch_start)
    return NewsContext(
        top_headlines=list(finnhub_result.headlines[:5]),
        headline_sentiment_avg=round(float(finnhub_result.sentiment_avg), 4),
        event_flags=list(finnhub_result.event_flags),
        data_age_seconds=data_age,
    )


def _build_social_context(
    ticker: str, data_gaps: list[str]
) -> SocialContext:
    """Build SocialContext from CNN Fear & Greed + ApeWisdom WSB.

    Both sources are free (no API key). On any failure a neutral
    SocialContext is returned and the reason is appended to ``data_gaps``.
    """
    # Import lazily so tests can monkeypatch ``fetch_social_sentiment`` on
    # the source module without circular-import concerns.
    from tradingagents.data.sources import social_sentiment as social_source

    try:
        result = social_source.fetch_social_sentiment(ticker)
    except Exception as exc:  # noqa: BLE001 - defensive belt-and-braces
        data_gaps.append(f"social:sentiment_fetch_failed:unexpected:{exc}")
        return SocialContext(
            mention_volume_vs_avg=1.0,
            sentiment_score=0.0,
            trending_narratives=[],
            data_age_seconds=86400,
        )

    if not result.fetched_ok:
        reason = result.error or "unknown_error"
        data_gaps.append(f"social:sentiment_fetch_failed:{reason}")
        return SocialContext(
            mention_volume_vs_avg=1.0,
            sentiment_score=0.0,
            trending_narratives=[],
            data_age_seconds=86400,
        )

    if result.error:
        # Partial failure (one upstream degraded) — still usable but record.
        data_gaps.append(f"social:partial:{result.error}")

    return SocialContext(
        mention_volume_vs_avg=float(result.mention_volume_vs_avg),
        sentiment_score=float(result.sentiment_score),
        trending_narratives=list(result.trending_narratives)[:3],
        data_age_seconds=0,
    )


def _build_institutional_context(
    ticker: str, data_gaps: list[str]
) -> InstitutionalContext:
    """Build InstitutionalContext from QuiverQuant.

    On any failure (missing API key, all endpoints failing, unexpected
    exception) returns a default :class:`InstitutionalContext` and tags
    ``data_gaps`` with a namespaced reason string.
    """
    # Import lazily so tests can monkeypatch ``fetch_quiver_institutional``
    # on the source module without circular-import concerns.
    from tradingagents.data.sources import quiver_institutional as quiver_source

    try:
        result = quiver_source.fetch_quiver_institutional(ticker)
    except Exception as exc:  # noqa: BLE001 - defensive belt-and-braces
        data_gaps.append(f"institutional:quiver_fallback:unexpected:{exc}")
        return InstitutionalContext()

    if not result.fetched_ok:
        reason = result.error or "unknown_error"
        data_gaps.append(f"institutional:quiver_fallback:{reason}")
        return InstitutionalContext()

    if result.error:
        # Partial failure (one upstream degraded) — still usable but record.
        data_gaps.append(f"institutional:partial:{result.error}")

    return InstitutionalContext(
        congressional_net_buys_30d=int(result.congressional_net_buys_30d),
        congressional_top_buyers=list(result.congressional_top_buyers),
        congressional_top_sellers=list(result.congressional_top_sellers),
        govt_contracts_count_90d=int(result.govt_contracts_count_90d),
        govt_contracts_total_usd=float(result.govt_contracts_total_usd),
        lobbying_usd_last_quarter=float(result.lobbying_usd_last_quarter),
        insider_net_txns_90d=int(result.insider_net_txns_90d),
        insider_top_buyers=list(result.insider_top_buyers),
        data_age_seconds=int(result.data_age_seconds),
        fetched_ok=True,
    )


def _build_macro_context(data_gaps: list[str], as_of_date: str) -> MacroContext:
    """Build MacroContext from yfinance (VIX + SPY) and FRED (rates).

    Combines:
      * VIX level via yfinance (``^VIX``).
      * SPY 5-day and 20-day returns via yfinance (``SPY``) used as the
        broad-market proxy for ``sector_etf_*_pct`` fields.
      * Fed funds rate and 2y-10y yield curve via FRED.
      * A deterministic regime classification over the above signals.

    Failure semantics:
      * yfinance VIX failure appends ``"macro:vix"`` to ``data_gaps``.
      * yfinance SPY failure appends ``"macro:spy"`` to ``data_gaps``.
      * FRED failure appends ``"macro:fred_fallback"`` to ``data_gaps``.
    """
    fetch_start = time.time()

    # --- VIX ----------------------------------------------------------------
    vix_level: float | None = None
    try:
        vix_hist = yf.Ticker("^VIX").history(period="5d")
        if vix_hist.empty:
            raise ValueError("Empty VIX history")
        vix_level = round(float(vix_hist["Close"].iloc[-1]), 2)
    except Exception:
        data_gaps.append("macro:vix")

    # --- SPY 5d / 20d returns ----------------------------------------------
    spy_5d_pct: float | None = None
    spy_20d_pct: float | None = None
    try:
        # ~30 calendar days covers 20 trading days with a buffer.
        spy_hist = yf.Ticker("SPY").history(period="2mo")
        if spy_hist.empty or len(spy_hist) < 21:
            raise ValueError("Insufficient SPY history")
        closes = spy_hist["Close"].tolist()
        last = float(closes[-1])
        prev_5 = float(closes[-6])
        prev_20 = float(closes[-21])
        if prev_5 > 0:
            spy_5d_pct = round((last / prev_5 - 1.0) * 100.0, 2)
        if prev_20 > 0:
            spy_20d_pct = round((last / prev_20 - 1.0) * 100.0, 2)
    except Exception:
        data_gaps.append("macro:spy")

    # --- FRED macro ---------------------------------------------------------
    fred = fetch_fred_macro(as_of_date)
    if not fred.fetched_ok:
        data_gaps.append("macro:fred_fallback")

    yield_curve_int: int | None = None
    if fred.yield_curve_2y10y_bps is not None:
        yield_curve_int = int(round(fred.yield_curve_2y10y_bps))

    regime = classify_regime(
        vix_level=vix_level,
        yield_curve_2y10y_bps=fred.yield_curve_2y10y_bps,
        spy_20d_pct=spy_20d_pct,
    )

    data_age = int(time.time() - fetch_start)
    return MacroContext(
        regime=regime,
        fed_funds_rate=fred.fed_funds_rate,
        vix_level=vix_level,
        yield_curve_2y10y_bps=yield_curve_int,
        sector_etf_5d_pct=spy_5d_pct,
        sector_etf_20d_pct=spy_20d_pct,
        data_age_seconds=data_age,
    )


def _build_event_calendar(
    ticker_obj: yf.Ticker, data_gaps: list[str]
) -> EventCalendar:
    """Build EventCalendar from yfinance calendar data."""
    try:
        cal = ticker_obj.calendar
        if cal is None or (isinstance(cal, dict) and not cal):
            raise ValueError("No calendar data")

        next_earnings_days: int | None = None
        ex_div_within_30 = False

        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
            if earnings_date is not None:
                if isinstance(earnings_date, list) and earnings_date:
                    earnings_date = earnings_date[0]
                try:
                    from datetime import date as date_type

                    if hasattr(earnings_date, "date"):
                        ed = earnings_date.date()
                    elif isinstance(earnings_date, date_type):
                        ed = earnings_date
                    else:
                        ed = None

                    if ed is not None:
                        today = datetime.now(timezone.utc).date()
                        delta = (ed - today).days
                        if delta >= 0:
                            next_earnings_days = delta
                except Exception:
                    pass

            ex_div_date = cal.get("Ex-Dividend Date")
            if ex_div_date is not None:
                try:
                    from datetime import date as date_type

                    if hasattr(ex_div_date, "date"):
                        dd = ex_div_date.date()
                    elif isinstance(ex_div_date, date_type):
                        dd = ex_div_date
                    else:
                        dd = None

                    if dd is not None:
                        today = datetime.now(timezone.utc).date()
                        delta = (dd - today).days
                        ex_div_within_30 = 0 <= delta <= 30
                except Exception:
                    pass

        return EventCalendar(
            next_earnings_days=next_earnings_days,
            ex_dividend_within_30d=ex_div_within_30,
        )
    except Exception:
        data_gaps.append("events:calendar")
        return EventCalendar()


# ------------------------------------------------------------------
# Fundamentals (yfinance .info)
# ------------------------------------------------------------------


def _build_fundamentals_context(
    ticker: str,
    ticker_obj: yf.Ticker,
    data_gaps: list[str],
) -> FundamentalsContext | None:
    """Pull basic fundamental metrics from yfinance .info dict.

    Returns ``None`` when the lookup fails entirely so the briefing
    remains backward-compatible with consumers that predate this field.
    """
    try:
        info = ticker_obj.info or {}
        if not info:
            data_gaps.append("fundamentals:no_info")
            return None
        return FundamentalsContext(
            market_cap=info.get("marketCap"),
            pe_ratio=info.get("trailingPE"),
            forward_pe=info.get("forwardPE"),
            eps_ttm=info.get("trailingEps"),
            revenue_ttm=info.get("totalRevenue"),
            profit_margin=info.get("profitMargins"),
            debt_to_equity=info.get("debtToEquity"),
            dividend_yield=info.get("dividendYield"),
            sector=info.get("sector"),
            industry=info.get("industry"),
        )
    except Exception:
        logger.warning("Failed to fetch fundamentals for %s", ticker, exc_info=True)
        data_gaps.append("fundamentals:fetch_error")
        return None


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def materialize_briefing(ticker: str, date: str) -> TickerBriefing:
    """Fetch real-time data and produce a frozen TickerBriefing.

    Uses yfinance for price, options, news, holders.
    Uses sensible defaults for any field that fails to fetch.
    The snapshot_id is: f"snap_{ticker}_{date}_{timestamp}"
    """
    timestamp = int(time.time())
    snapshot_id = f"snap_{ticker}_{date}_{timestamp}"
    data_gaps: list[str] = []

    ticker_obj = yf.Ticker(ticker)

    # Fetch the 1-year OHLCV history ONCE and share it across the
    # price and volatility builders so we don't pay upstream twice.
    # ``date`` is propagated so historical backtests pin their vendor
    # requests to the as-of date and never leak future data.
    hist = _fetch_price_history(ticker, ticker_obj, data_gaps, as_of_date=date)

    price_ctx = _build_price_context(ticker, ticker_obj, data_gaps, hist=hist)
    options_ctx = _build_options_context(ticker, ticker_obj, price_ctx, data_gaps)
    volatility_ctx = _build_volatility_context(
        hist,
        options_ctx.iv_rank_percentile,
        data_gaps,
        ticker=ticker,
        options_ctx=options_ctx,
    )
    news_ctx = _build_news_context(ticker_obj, ticker, date, data_gaps)
    social_ctx = _build_social_context(ticker, data_gaps)
    institutional_ctx = _build_institutional_context(ticker, data_gaps)
    macro_ctx = _build_macro_context(data_gaps, date)
    events_ctx = _build_event_calendar(ticker_obj, data_gaps)
    fundamentals_ctx = _build_fundamentals_context(ticker, ticker_obj, data_gaps)

    return TickerBriefing(
        ticker=ticker,
        date=date,
        snapshot_id=snapshot_id,
        price=price_ctx,
        options=options_ctx,
        news=news_ctx,
        social=social_ctx,
        institutional=institutional_ctx,
        macro=macro_ctx,
        events=events_ctx,
        volatility=volatility_ctx,
        fundamentals=fundamentals_ctx,
        data_gaps=data_gaps,
    )


if __name__ == "__main__":
    # Test 1: Basic materialization
    briefing = materialize_briefing("AAPL", "2026-04-05")
    assert isinstance(briefing, TickerBriefing)
    assert briefing.ticker == "AAPL"
    assert briefing.price.price > 0
    assert 0 <= briefing.price.rsi_14 <= 100
    assert briefing.snapshot_id.startswith("snap_AAPL_")
    print("Test 1 PASSED: Basic materialization")

    # Test 2: All contexts populated
    assert isinstance(briefing.price, PriceContext)
    assert isinstance(briefing.options, OptionsContext)
    assert isinstance(briefing.news, NewsContext)
    assert isinstance(briefing.social, SocialContext)
    assert isinstance(briefing.macro, MacroContext)
    assert isinstance(briefing.events, EventCalendar)
    print("Test 2 PASSED: All contexts populated")

    # Test 3: Invalid ticker gracefully handled
    bad = materialize_briefing("XXXINVALID999", "2026-04-05")
    assert isinstance(bad, TickerBriefing)
    assert len(bad.data_gaps) > 0
    print("Test 3 PASSED: Invalid ticker handled gracefully")

    print("\nAll tests PASSED")
