"""HAR-RV factor library (adapted from Corsi 2009 for daily OHLCV).

Tier -1 (baseline, 10 factors):
- 8 HAR factors: rv_daily, rv_5d_mean, rv_22d_mean, bpv_daily, rv_momentum,
  vol_surprise, rv_5d_std, rv_22d_std
- 2 AR(1) features: rv_ar1_pred, rv_ar1_resid

Tier 0 extensions (8 additional range-based / decomposition / leverage factors):
- Parkinson (1980) range RV: ``rv_parkinson``
- Rogers-Satchell (1991) drift-independent RV: ``rv_rs``
- Yang-Zhang (2000) composite RV: ``rv_yz``
- Overnight variance: ``rv_overnight`` (close-to-open gap)
- Open-to-close variance: ``rv_oc``
- Corsi-Reno (2012) Leverage-HAR negative-return features:
  ``r_neg_d``, ``r_neg_5d``, ``r_neg_22d``

All features are causal -- no look-ahead bias. AR(1) uses expanding-window OLS
with a 60-day warmup.

The original Corsi (2009) HAR-RV specification uses intraday 1-minute bars to
compute daily realized volatility. This implementation adapts the estimator to
daily OHLC inputs by substituting the Garman-Klass range estimator for intraday
realized volatility, and a close-to-close bipower approximation for bipower
variation. Rolling-window semantics (5-day, 22-day) are identical to the
original spec but applied to the daily-resolution RV series.

References:
    Parkinson, M. (1980). "The Extreme Value Method for Estimating the
        Variance of the Rate of Return." Journal of Business 53(1): 61-65.
    Rogers, L.C.G. & Satchell, S.E. (1991). "Estimating Variance from High,
        Low and Closing Prices." Annals of Applied Probability 1(4): 504-512.
    Yang, D. & Zhang, Q. (2000). "Drift-Independent Volatility Estimation
        Based on High, Low, Open, and Close Prices." Journal of Business
        73(3): 477-491.
    Corsi, F. & Reno, R. (2012). "Discrete-Time Volatility Forecasting with
        Persistent Leverage Effect and the Link with Continuous-Time
        Volatility Modeling." Journal of Business & Economic Statistics
        30(3): 368-380.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Tier -1 (legacy) feature names -- preserved verbatim for backward compatibility.
# Downstream consumers (har_rv_ridge, materializer) may continue to reference
# this subset while the Tier 0 features are wired in separately.
LEGACY_FEATURE_NAMES: tuple[str, ...] = (
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

# Tier 0 feature names (appended in a stable order -- DO NOT reorder).
TIER0_FEATURE_NAMES: tuple[str, ...] = (
    "rv_parkinson",
    "rv_rs",
    "rv_yz",
    "rv_overnight",
    "rv_oc",
    "r_neg_d",
    "r_neg_5d",
    "r_neg_22d",
)

# Public feature name constants.
# Tier 0 extends FEATURE_NAMES at the tail; existing indices 0..9 are preserved.
FEATURE_NAMES: tuple[str, ...] = LEGACY_FEATURE_NAMES + TIER0_FEATURE_NAMES

_AR1_WARMUP: int = 60  # Minimum observations before AR(1) prediction is emitted.
_GK_CLOSE_OPEN_COEF: float = 2.0 * np.log(2.0) - 1.0  # ~0.3862943611198906
_PARKINSON_COEF: float = 1.0 / (4.0 * np.log(2.0))  # ~0.36067376022224085
_YZ_WINDOW: int = 22  # Rolling window used for Yang-Zhang k parameter and variances.


def _yang_zhang_k(n: int) -> float:
    """Yang-Zhang (2000) weighting constant.

    :math:`k = 0.34 / (1.34 + (n+1)/(n-1))`

    Args:
        n: Rolling-window length (must be >= 2).

    Returns:
        The scalar weight applied to the open-to-close variance component.
    """
    if n < 2:
        raise ValueError(f"Yang-Zhang window n must be >= 2 (got {n})")
    return 0.34 / (1.34 + (n + 1.0) / (n - 1.0))


def _resolve_ohlc_columns(ohlc: pd.DataFrame) -> dict[str, str]:
    """Map canonical OHLC names to the actual (case-insensitive) column names.

    Raises:
        ValueError: If any required column is missing.
    """
    lookup = {col.lower(): col for col in ohlc.columns}
    required = ("open", "high", "low", "close")
    missing = [name for name in required if name not in lookup]
    if missing:
        raise ValueError(
            f"ohlc DataFrame is missing required column(s): {missing}. "
            f"Got columns: {list(ohlc.columns)}"
        )
    return {name: lookup[name] for name in required}


def compute_garman_klass_rv(ohlc: pd.DataFrame) -> pd.Series:
    """Garman-Klass realized-volatility estimator from daily OHLC.

    Formula::

        GK_t = 0.5 * (ln(H/L))^2 - (2*ln(2) - 1) * (ln(C/O))^2
        rv_t = sqrt(max(GK_t, 0))

    Negative GK values (a numerical edge case when the close-to-open term
    exceeds the high-low term, e.g. when O == C == H == L within float noise)
    are clamped to zero before the square root.

    Args:
        ohlc: DataFrame with columns 'open', 'high', 'low', 'close'
            (case-insensitive). The original index is preserved in the result.

    Returns:
        A ``pd.Series`` of Garman-Klass realized volatilities, indexed the same
        as ``ohlc`` and named ``"rv_daily"``.
    """
    cols = _resolve_ohlc_columns(ohlc)
    open_ = ohlc[cols["open"]].astype(float)
    high = ohlc[cols["high"]].astype(float)
    low = ohlc[cols["low"]].astype(float)
    close = ohlc[cols["close"]].astype(float)

    log_hl = np.log(high / low)
    log_co = np.log(close / open_)
    gk = 0.5 * log_hl**2 - _GK_CLOSE_OPEN_COEF * log_co**2
    gk_clamped = gk.where(gk > 0.0, other=0.0)
    rv = np.sqrt(gk_clamped)
    rv.name = "rv_daily"
    return rv


def compute_bpv_daily(close: pd.Series) -> pd.Series:
    """Bipower-variation approximation using close-to-close log returns.

    Formula::

        r_t = ln(C_t / C_{t-1})
        bpv_t = (pi / 2) * |r_{t-1}| * |r_t|

    The first two entries of the returned series are NaN (we need two prior
    closes to form ``|r_{t-1}| * |r_t|``).

    Args:
        close: Daily close-price ``pd.Series``.

    Returns:
        A ``pd.Series`` named ``"bpv_daily"`` indexed identically to ``close``.
    """
    close_f = close.astype(float)
    log_ret = np.log(close_f / close_f.shift(1))
    abs_ret = log_ret.abs()
    bpv = (np.pi / 2.0) * abs_ret.shift(1) * abs_ret
    bpv.name = "bpv_daily"
    return bpv


def compute_ar1_expanding(
    rv_series: pd.Series, warmup: int = _AR1_WARMUP
) -> tuple[pd.Series, pd.Series]:
    """Expanding-window AR(1) prediction via closed-form OLS cumulative sums.

    Regresses ``RV_s`` on ``RV_{s-1}`` using all valid pairs ``s = 1..t-1``
    (strictly before ``t``). The closed-form OLS estimators are computed with
    running cumulative sums, so the function is fully vectorized (no
    per-row Python loop):

    .. math::

        \\hat{b}_t = \\frac{n S_{xy} - S_x S_y}{n S_{xx} - S_x^2}
        \\hat{a}_t = (S_y - \\hat{b}_t S_x) / n
        \\text{pred}_t = \\hat{a}_t + \\hat{b}_t \\cdot RV_{t-1}

    The first ``warmup`` observations are forced to NaN to ensure a stable
    estimation window. Observation index ``warmup`` uses pairs from indices
    ``0..warmup-1`` (i.e. the first ``warmup`` valid y-values), giving
    ``warmup`` observations for the regression.

    Args:
        rv_series: Daily realized-volatility series.
        warmup: Minimum valid (x, y) pairs required before a prediction is
            emitted. Defaults to 60.

    Returns:
        Tuple ``(pred_series, resid_series)``. Both series share the input
        index. ``resid_t = RV_t - pred_t`` wherever ``pred_t`` is finite,
        otherwise NaN.
    """
    if warmup < 2:
        raise ValueError(f"warmup must be >= 2 (got {warmup}) for a stable AR(1) fit")

    rv = rv_series.astype(float)
    index = rv.index

    y = rv.to_numpy(copy=False)  # "current" observation
    x = np.concatenate(([np.nan], y[:-1]))  # lag-1

    valid = np.isfinite(x) & np.isfinite(y)
    y_v = np.where(valid, y, 0.0)
    x_v = np.where(valid, x, 0.0)
    ones_v = valid.astype(np.float64)

    # Cumulative sums through index t inclusive.
    cum_n = np.cumsum(ones_v)
    cum_sx = np.cumsum(x_v)
    cum_sy = np.cumsum(y_v)
    cum_sxx = np.cumsum(x_v * x_v)
    cum_sxy = np.cumsum(x_v * y_v)

    # Shift by one so that time-t coefficients use pairs strictly before t.
    def _shift_right(arr: np.ndarray) -> np.ndarray:
        out = np.empty_like(arr)
        out[0] = 0.0
        out[1:] = arr[:-1]
        return out

    n_prev = _shift_right(cum_n)
    sx_prev = _shift_right(cum_sx)
    sy_prev = _shift_right(cum_sy)
    sxx_prev = _shift_right(cum_sxx)
    sxy_prev = _shift_right(cum_sxy)

    denom = n_prev * sxx_prev - sx_prev * sx_prev
    with np.errstate(invalid="ignore", divide="ignore"):
        b_hat = np.where(denom > 0.0, (n_prev * sxy_prev - sx_prev * sy_prev) / denom, np.nan)
        a_hat = np.where(n_prev > 0.0, (sy_prev - b_hat * sx_prev) / n_prev, np.nan)
        pred = a_hat + b_hat * x  # x already holds RV_{t-1}

    # Enforce warmup: require at least `warmup` valid pairs before t.
    pred = np.where(n_prev >= warmup, pred, np.nan)
    # If x (lag) is NaN, pred must also be NaN.
    pred = np.where(np.isfinite(x), pred, np.nan)

    pred_series = pd.Series(pred, index=index, name="rv_ar1_pred")
    resid_series = (rv - pred_series).rename("rv_ar1_resid")
    return pred_series, resid_series


def _safe_log_ratio(numer: pd.Series, denom: pd.Series) -> pd.Series:
    """Return ln(numer/denom), propagating NaN for non-positive / missing inputs.

    Guards against ``ln(0)``, ``ln(negative)``, and divide-by-zero without
    raising, so that one bad bar does not poison the entire series.
    """
    n = numer.astype(float)
    d = denom.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        # Guard non-positive or missing inputs at the source so that
        # divide-by-zero cannot produce +/- inf (which would survive
        # ``ratio > 0`` and bubble through np.log as inf rather than NaN).
        n_safe = n.where(n > 0.0)
        d_safe = d.where(d > 0.0)
        ratio = n_safe / d_safe
        ratio = ratio.where(np.isfinite(ratio))
        return np.log(ratio)


def compute_parkinson_rv(ohlc: pd.DataFrame) -> pd.Series:
    """Parkinson (1980) range-based realized-variance estimator.

    Formula::

        rv_parkinson_t = (ln(H_t / L_t))^2 / (4 * ln(2))

    This is a *variance* estimator (not volatility). It assumes zero drift and
    is more efficient than the close-to-close estimator under that assumption
    (Parkinson 1980). NaN is returned for any bar with non-positive H or L.

    Args:
        ohlc: DataFrame with columns ``'high'`` and ``'low'`` (case-insensitive).

    Returns:
        A ``pd.Series`` of per-bar Parkinson variances, named ``"rv_parkinson"``.
    """
    cols = _resolve_ohlc_columns(ohlc)
    high = ohlc[cols["high"]].astype(float)
    low = ohlc[cols["low"]].astype(float)
    log_hl = _safe_log_ratio(high, low)
    rv = _PARKINSON_COEF * log_hl**2
    rv.name = "rv_parkinson"
    return rv


def compute_rogers_satchell_rv(ohlc: pd.DataFrame) -> pd.Series:
    """Rogers-Satchell (1991) drift-independent realized-variance estimator.

    Formula::

        rv_rs_t = ln(H/C)*ln(H/O) + ln(L/C)*ln(L/O)

    Unlike Parkinson and Garman-Klass, this estimator is unbiased in the
    presence of a non-zero drift (Rogers & Satchell 1991). NaN is returned
    for any bar with a non-positive OHLC component.

    Args:
        ohlc: DataFrame with columns ``'open'``, ``'high'``, ``'low'``,
            ``'close'`` (case-insensitive).

    Returns:
        A ``pd.Series`` of per-bar Rogers-Satchell variances, named ``"rv_rs"``.
    """
    cols = _resolve_ohlc_columns(ohlc)
    open_ = ohlc[cols["open"]].astype(float)
    high = ohlc[cols["high"]].astype(float)
    low = ohlc[cols["low"]].astype(float)
    close = ohlc[cols["close"]].astype(float)

    log_hc = _safe_log_ratio(high, close)
    log_ho = _safe_log_ratio(high, open_)
    log_lc = _safe_log_ratio(low, close)
    log_lo = _safe_log_ratio(low, open_)

    rv = log_hc * log_ho + log_lc * log_lo
    rv.name = "rv_rs"
    return rv


def compute_overnight_variance(ohlc: pd.DataFrame) -> pd.Series:
    """Overnight (close-to-open gap) squared log return.

    Formula::

        rv_overnight_t = (ln(O_t) - ln(C_{t-1}))^2

    The first row is NaN (no previous close). Bars with non-positive O or
    previous C yield NaN.

    Args:
        ohlc: DataFrame with columns ``'open'`` and ``'close'`` (case-insensitive).

    Returns:
        A ``pd.Series`` named ``"rv_overnight"``.
    """
    cols = _resolve_ohlc_columns(ohlc)
    open_ = ohlc[cols["open"]].astype(float)
    close = ohlc[cols["close"]].astype(float)
    prev_close = close.shift(1)
    log_ret = _safe_log_ratio(open_, prev_close)
    rv = log_ret**2
    rv.name = "rv_overnight"
    return rv


def compute_open_to_close_variance(ohlc: pd.DataFrame) -> pd.Series:
    """Open-to-close squared log return.

    Formula::

        rv_oc_t = (ln(C_t) - ln(O_t))^2

    Bars with non-positive O or C yield NaN.

    Args:
        ohlc: DataFrame with columns ``'open'`` and ``'close'`` (case-insensitive).

    Returns:
        A ``pd.Series`` named ``"rv_oc"``.
    """
    cols = _resolve_ohlc_columns(ohlc)
    open_ = ohlc[cols["open"]].astype(float)
    close = ohlc[cols["close"]].astype(float)
    log_ret = _safe_log_ratio(close, open_)
    rv = log_ret**2
    rv.name = "rv_oc"
    return rv


def compute_yang_zhang_rv(
    ohlc: pd.DataFrame, window: int = _YZ_WINDOW
) -> pd.Series:
    """Yang-Zhang (2000) composite realized-variance estimator.

    The Yang-Zhang estimator combines three components computed over a
    rolling window of length ``n``:

    - :math:`\\sigma^2_o`: sample variance of overnight log returns
      :math:`o_i = \\ln(O_i / C_{i-1})`
    - :math:`\\sigma^2_c`: sample variance of open-to-close log returns
      :math:`c_i = \\ln(C_i / O_i)`
    - :math:`\\sigma^2_{RS}`: mean of per-bar Rogers-Satchell variances over
      the window

    Combined as

    .. math::

        \\sigma^2_{YZ} = \\sigma^2_o + k \\sigma^2_c + (1 - k) \\sigma^2_{RS}

    with the weighting constant

    .. math::

        k = \\frac{0.34}{1.34 + (n+1)/(n-1)}

    which Yang & Zhang (2000) showed minimises the estimator's variance. The
    sample variances use an ``N-1`` divisor (``ddof=1``) to match the paper.

    Args:
        ohlc: DataFrame with columns ``'open'``, ``'high'``, ``'low'``,
            ``'close'`` (case-insensitive).
        window: Rolling window length ``n``. Defaults to 22 (~one month of
            trading days).

    Returns:
        A ``pd.Series`` named ``"rv_yz"``. The first ``window`` rows are NaN
        because both the overnight and open-to-close sample variances require
        at least ``window`` valid observations (and the overnight series itself
        starts from index 1).
    """
    cols = _resolve_ohlc_columns(ohlc)
    open_ = ohlc[cols["open"]].astype(float)
    close = ohlc[cols["close"]].astype(float)

    # Overnight and open-to-close log returns (not squared -- we need variances).
    o_ret = _safe_log_ratio(open_, close.shift(1))  # ln(O_t / C_{t-1})
    c_ret = _safe_log_ratio(close, open_)  # ln(C_t / O_t)

    sigma2_o = o_ret.rolling(window=window, min_periods=window).var(ddof=1)
    sigma2_c = c_ret.rolling(window=window, min_periods=window).var(ddof=1)

    rs = compute_rogers_satchell_rv(ohlc)
    sigma2_rs = rs.rolling(window=window, min_periods=window).mean()

    k = _yang_zhang_k(window)
    rv = sigma2_o + k * sigma2_c + (1.0 - k) * sigma2_rs
    rv.name = "rv_yz"
    return rv


def compute_leverage_features(
    close: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Corsi-Reno (2012) LHAR negative-return leverage features.

    Let :math:`r_t = \\ln(C_t / C_{t-1})`. Define the negative-return indicator

    .. math:: r^-_t = \\min(r_t, 0) \\le 0

    Rolling means over 5- and 22-day windows capture the persistent leverage
    effect described in Corsi & Reno (2012).

    Args:
        close: Daily close-price ``pd.Series``.

    Returns:
        Tuple ``(r_neg_d, r_neg_5d, r_neg_22d)`` of ``pd.Series`` named
        accordingly. All values are <= 0 (or NaN).
    """
    close_f = close.astype(float)
    log_ret = _safe_log_ratio(close_f, close_f.shift(1))
    # Preserve NaN, clamp finite values to min(r, 0).
    r_neg = log_ret.where(log_ret.isna(), other=log_ret.clip(upper=0.0))
    r_neg.name = "r_neg_d"
    r_neg_5 = r_neg.rolling(window=5, min_periods=5).mean().rename("r_neg_5d")
    r_neg_22 = r_neg.rolling(window=22, min_periods=22).mean().rename("r_neg_22d")
    return r_neg, r_neg_5, r_neg_22


def compute_har_factors(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Compute all HAR-RV factors (Tier -1 baseline + Tier 0 extensions) for one ticker.

    Args:
        ohlc: DataFrame with a monotonically increasing ``DatetimeIndex`` (one
            row per trading day) and columns ``'open'``, ``'high'``, ``'low'``,
            ``'close'`` (case-insensitive). Additional columns are ignored.

    Returns:
        A DataFrame indexed identically to ``ohlc`` with columns
        :data:`FEATURE_NAMES`. Rows with insufficient history (e.g. the first
        21 rows for 22-day rolling windows) contain NaN for the corresponding
        features.
    """
    cols = _resolve_ohlc_columns(ohlc)
    close = ohlc[cols["close"]].astype(float)

    rv_daily = compute_garman_klass_rv(ohlc)
    bpv_daily = compute_bpv_daily(close)

    rv_5d_mean = rv_daily.rolling(window=5, min_periods=5).mean()
    rv_22d_mean = rv_daily.rolling(window=22, min_periods=22).mean()
    # Population standard deviation (N divisor) to match the HAR-RV spec.
    rv_5d_std = rv_daily.rolling(window=5, min_periods=5).std(ddof=0)
    rv_22d_std = rv_daily.rolling(window=22, min_periods=22).std(ddof=0)

    # Divide-by-zero / NaN-safe: explicit NaN where denominator is not > 0.
    safe_22 = rv_22d_mean.where(rv_22d_mean > 0.0)
    rv_momentum = rv_5d_mean / safe_22
    vol_surprise = rv_daily / safe_22

    ar1_pred, ar1_resid = compute_ar1_expanding(rv_daily, warmup=_AR1_WARMUP)

    # Tier 0 extensions (range-based estimators, overnight/OC decomposition,
    # Corsi-Reno leverage features). These are appended to the output and do
    # not affect any Tier -1 column values.
    rv_parkinson = compute_parkinson_rv(ohlc)
    rv_rs = compute_rogers_satchell_rv(ohlc)
    rv_yz = compute_yang_zhang_rv(ohlc, window=_YZ_WINDOW)
    rv_overnight = compute_overnight_variance(ohlc)
    rv_oc = compute_open_to_close_variance(ohlc)
    r_neg_d, r_neg_5d, r_neg_22d = compute_leverage_features(close)

    features = pd.DataFrame(
        {
            "rv_daily": rv_daily,
            "rv_5d_mean": rv_5d_mean,
            "rv_22d_mean": rv_22d_mean,
            "bpv_daily": bpv_daily,
            "rv_momentum": rv_momentum,
            "vol_surprise": vol_surprise,
            "rv_5d_std": rv_5d_std,
            "rv_22d_std": rv_22d_std,
            "rv_ar1_pred": ar1_pred,
            "rv_ar1_resid": ar1_resid,
            "rv_parkinson": rv_parkinson,
            "rv_rs": rv_rs,
            "rv_yz": rv_yz,
            "rv_overnight": rv_overnight,
            "rv_oc": rv_oc,
            "r_neg_d": r_neg_d,
            "r_neg_5d": r_neg_5d,
            "r_neg_22d": r_neg_22d,
        },
        index=ohlc.index,
    )
    # Guarantee column order matches FEATURE_NAMES for deterministic downstream use.
    return features[list(FEATURE_NAMES)]
