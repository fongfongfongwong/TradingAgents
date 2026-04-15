"""Social sentiment source for the TickerBriefing materializer.

Combines two free, no-auth public APIs:

* **CNN Fear & Greed Index** — market-wide sentiment gauge (0-100). Used as a
  baseline sentiment score via a piecewise mapping.
* **ApeWisdom r/wallstreetbets** — retail mention ranks for the top ~50
  tickers discussed on WSB. Provides ticker-specific mention volume and
  crude bullish/bearish sentiment.

All functions are safe to call without any API key and never raise — on any
error a :class:`SocialSentimentResult` with ``fetched_ok=False`` and an
informative ``error`` message is returned so the materializer can fall back
to defaults.

Results are cached per-ticker for 15 minutes in a module-level dict to keep
materialization fast when briefings are built back-to-back.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_FEAR_GREED_URL = (
    "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
)
_APEWISDOM_WSB_URL = (
    "https://apewisdom.io/api/v1.0/filter/wallstreetbets"
)
_HTTP_TIMEOUT_SECONDS = 10.0
_CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
_USER_AGENT = "Mozilla/5.0 (compatible; TradingAgents/1.0)"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SocialSentimentResult:
    """Immutable result of a combined Fear & Greed + ApeWisdom fetch.

    Attributes:
        mention_volume_vs_avg: Normalized WSB mention volume. ``1.0`` means
            "not in top 50" (baseline). Values > 1 indicate a ticker is
            trending; higher rank (lower number) yields a larger value.
        sentiment_score: Combined sentiment in ``[-1.0, 1.0]`` weighted
            40% Fear & Greed, 60% ApeWisdom.
        trending_narratives: Short narrative tags derived from the raw
            metrics (e.g. ``"meme_momentum"``, ``"extreme_greed_environment"``).
        fear_greed_index: CNN Fear & Greed raw value ``0-100`` or ``None``.
        apewisdom_rank: WSB rank (1 = top) or ``None`` if not in top 50.
        apewisdom_mentions: Raw WSB mention count or ``None``.
        fetched_ok: True if at least one upstream source succeeded.
        error: Human-readable error summary when no source succeeded,
            otherwise ``None``.
    """

    mention_volume_vs_avg: float = 1.0
    sentiment_score: float = 0.0
    trending_narratives: list[str] = field(default_factory=list)
    fear_greed_index: int | None = None
    apewisdom_rank: int | None = None
    apewisdom_mentions: int | None = None
    fetched_ok: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Module-level cache (thread-safe)
# ---------------------------------------------------------------------------


_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, SocialSentimentResult]] = {}


def _cache_get(ticker: str) -> SocialSentimentResult | None:
    with _cache_lock:
        entry = _cache.get(ticker)
        if entry is None:
            return None
        stored_at, result = entry
        if time.time() - stored_at > _CACHE_TTL_SECONDS:
            _cache.pop(ticker, None)
            return None
        return result


def _cache_put(ticker: str, result: SocialSentimentResult) -> None:
    with _cache_lock:
        _cache[ticker] = (time.time(), result)


def _clear_cache() -> None:
    """Test hook — clears the module-level cache."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Fear & Greed helpers
# ---------------------------------------------------------------------------


def _fear_greed_to_score(value: float) -> float:
    """Map a 0-100 CNN Fear & Greed value to a score in ``[-1.0, 1.0]``.

    Piecewise mapping per spec:

    * 0-25   -> -1.0 (extreme fear)
    * 25-45  -> -0.5 (fear)
    * 45-55  ->  0.0 (neutral)
    * 55-75  -> +0.5 (greed)
    * 75-100 -> +1.0 (extreme greed)
    """
    if value <= 25:
        return -1.0
    if value <= 45:
        return -0.5
    if value <= 55:
        return 0.0
    if value <= 75:
        return 0.5
    return 1.0


def _fetch_fear_greed(
    session: requests.Session,
) -> tuple[int | None, float, str | None]:
    """Fetch CNN Fear & Greed index.

    Returns ``(raw_value_or_none, score_in_range, error_or_none)``.
    """
    try:
        resp = session.get(_FEAR_GREED_URL, timeout=_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        return None, 0.0, f"fear_greed_http:{exc}"
    except ValueError as exc:
        return None, 0.0, f"fear_greed_json:{exc}"

    try:
        fg = data.get("fear_and_greed") or {}
        raw = fg.get("score")
        if raw is None:
            return None, 0.0, "fear_greed_missing_score"
        value = float(raw)
    except (TypeError, ValueError) as exc:
        return None, 0.0, f"fear_greed_parse:{exc}"

    return int(round(value)), _fear_greed_to_score(value), None


# ---------------------------------------------------------------------------
# ApeWisdom helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ApeWisdomRow:
    rank: int | None
    rank_24h_ago: int | None
    mentions: int | None
    sentiment: float | None  # ApeWisdom optional sentiment field
    found: bool


def _fetch_apewisdom_row(
    session: requests.Session, ticker: str
) -> tuple[_ApeWisdomRow, str | None]:
    """Fetch ApeWisdom WSB row for ``ticker``.

    Returns the matched row (or an empty row) and an error string (or
    ``None`` on success — an empty row with no error means the API
    responded but the ticker wasn't in the top 50).
    """
    empty = _ApeWisdomRow(
        rank=None,
        rank_24h_ago=None,
        mentions=None,
        sentiment=None,
        found=False,
    )
    try:
        resp = session.get(
            _APEWISDOM_WSB_URL, timeout=_HTTP_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        return empty, f"apewisdom_http:{exc}"
    except ValueError as exc:
        return empty, f"apewisdom_json:{exc}"

    results = data.get("results") or []
    target = ticker.upper()
    for item in results:
        if not isinstance(item, dict):
            continue
        if str(item.get("ticker", "")).upper() != target:
            continue
        try:
            rank = int(item["rank"]) if item.get("rank") is not None else None
        except (TypeError, ValueError):
            rank = None
        try:
            rank_24h = (
                int(item["rank_24h_ago"])
                if item.get("rank_24h_ago") is not None
                else None
            )
        except (TypeError, ValueError):
            rank_24h = None
        try:
            mentions = (
                int(item["mentions"])
                if item.get("mentions") is not None
                else None
            )
        except (TypeError, ValueError):
            mentions = None
        sentiment_raw = item.get("sentiment_score")
        if sentiment_raw is None:
            sentiment_raw = item.get("sentiment")
        try:
            sentiment = (
                float(sentiment_raw) if sentiment_raw is not None else None
            )
        except (TypeError, ValueError):
            sentiment = None
        return (
            _ApeWisdomRow(
                rank=rank,
                rank_24h_ago=rank_24h,
                mentions=mentions,
                sentiment=sentiment,
                found=True,
            ),
            None,
        )

    return empty, None


def _apewisdom_mention_volume(rank: int | None) -> float:
    """Map an ApeWisdom WSB rank to a mention-volume multiplier.

    Not in top 50 -> ``1.0`` (baseline). Rank 1 -> ``50/50 = 1.0 + 1.0 = 2.0``
    (51 - 1) / 50 = 1.0 -> bounded below; we use the spec formula directly:
    ``(51 - rank) / 50``. A rank of 1 yields 1.0, which we *offset* by the
    baseline of 1.0 (not ranked) per the spec note "baseline 1.0 = not ranked"
    so present-in-list values are strictly > 1.0.
    """
    if rank is None:
        return 1.0
    # Spec: "use (51 - rank) / 50 as mention_volume_vs_avg". We interpret
    # the baseline 1.0 = not ranked as meaning: not-in-list -> 1.0, and a
    # ranked ticker produces 1.0 + (51 - rank) / 50 so being top-of-list is
    # clearly above baseline.
    return 1.0 + max(0.0, (51 - rank) / 50.0)


def _apewisdom_sentiment_component(
    row: _ApeWisdomRow, mention_volume: float
) -> float:
    """Derive the ApeWisdom sentiment sub-score in ``[-1, 1]``.

    If the API provides a sentiment field we scale it by mention volume
    (higher volume = more confident signal). If no explicit sentiment is
    present, a ticker appearing in WSB top 50 is interpreted as mildly
    bullish (+0.5) scaled by the normalized mention volume above baseline.
    """
    if not row.found:
        return 0.0

    # Normalize mention volume contribution into [0, 1].
    # mention_volume for a ranked ticker is in (1.0, 2.0].
    volume_weight = min(1.0, max(0.0, mention_volume - 1.0))

    if row.sentiment is not None:
        if row.sentiment > 0:
            return 0.5 * volume_weight
        if row.sentiment < 0:
            return -0.5 * volume_weight
        return 0.0

    # No explicit sentiment field: treat presence in WSB top 50 as a
    # mildly bullish retail signal.
    return 0.5 * volume_weight


def _derive_narratives(
    fear_greed_value: int | None,
    rank: int | None,
    rank_24h_ago: int | None,
) -> list[str]:
    """Build short narrative tags from raw metrics."""
    narratives: list[str] = []

    if rank is not None and rank <= 10:
        narratives.append("meme_momentum")

    if rank is not None and rank_24h_ago is not None:
        # "moved up > 20 positions" means rank decreased by more than 20.
        delta = rank_24h_ago - rank
        if delta > 20:
            narratives.append("retail_surge")

    if fear_greed_value is not None:
        if fear_greed_value > 80:
            narratives.append("extreme_greed_environment")
        elif fear_greed_value < 20:
            narratives.append("extreme_fear_environment")

    return narratives


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_social_sentiment(ticker: str) -> SocialSentimentResult:
    """Fetch combined retail sentiment for ``ticker``.

    Never raises. On total failure returns a result with ``fetched_ok=False``
    and default neutral values (``sentiment_score=0.0``,
    ``mention_volume_vs_avg=1.0``).
    """
    if not ticker or not isinstance(ticker, str):
        return SocialSentimentResult(
            fetched_ok=False, error="invalid_ticker"
        )

    normalized = ticker.upper().strip()
    cached = _cache_get(normalized)
    if cached is not None:
        return cached

    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})

    errors: list[str] = []

    try:
        fg_value, fg_score, fg_err = _fetch_fear_greed(session)
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.exception("Unexpected Fear & Greed error for %s", normalized)
        fg_value, fg_score, fg_err = None, 0.0, f"fear_greed_unexpected:{exc}"
    if fg_err:
        errors.append(fg_err)

    try:
        ape_row, ape_err = _fetch_apewisdom_row(session, normalized)
    except Exception as exc:  # noqa: BLE001 - defensive
        logger.exception("Unexpected ApeWisdom error for %s", normalized)
        ape_row = _ApeWisdomRow(None, None, None, None, False)
        ape_err = f"apewisdom_unexpected:{exc}"
    if ape_err:
        errors.append(ape_err)

    try:
        session.close()
    except Exception:  # noqa: BLE001 - best effort
        pass

    # At least one source must have succeeded (no error) to count as OK.
    fg_ok = fg_err is None
    ape_ok = ape_err is None
    fetched_ok = fg_ok or ape_ok

    mention_volume = _apewisdom_mention_volume(ape_row.rank)
    ape_component = _apewisdom_sentiment_component(ape_row, mention_volume)

    # Weighted combination: 40% Fear & Greed, 60% ApeWisdom. If one source
    # failed, its component is already 0.0 — but we still clamp to [-1, 1].
    combined = (fg_score * 0.4) + (ape_component * 0.6)
    combined = max(-1.0, min(1.0, combined))

    narratives = _derive_narratives(
        fg_value, ape_row.rank, ape_row.rank_24h_ago
    )

    result = SocialSentimentResult(
        mention_volume_vs_avg=round(mention_volume, 4),
        sentiment_score=round(combined, 4),
        trending_narratives=narratives,
        fear_greed_index=fg_value,
        apewisdom_rank=ape_row.rank,
        apewisdom_mentions=ape_row.mentions,
        fetched_ok=fetched_ok,
        error="; ".join(errors) if errors and not fetched_ok else (
            "; ".join(errors) if errors else None
        ),
    )

    if fetched_ok:
        _cache_put(normalized, result)
    return result
