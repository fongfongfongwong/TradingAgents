"""Deterministic news prioritization scorer.

Scores headlines for a given ticker along four axes:

- ``relevance``    — how directly the item affects the ticker (RavenPack ERS style gating)
- ``direction``    — LONG / SHORT / NEUTRAL (Bloomberg polarity style)
- ``confidence``   — magnitude of the directional signal (AlphaSense style)
- ``impact_score`` — final sort key, combining the above with a recency decay

Recency decay uses a 4-hour half-life — a synthesis of RavenPack's 24h novelty
window and Tetlock's 1-day reversion literature.

The module is pure-Python (regex + math), deterministic, and does not touch the
network. All patterns are compiled once at import time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Sequence

from tradingagents.api.models.responses import ScoredHeadline

Direction = Literal["LONG", "SHORT", "NEUTRAL"]


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawHeadline:
    """Immutable headline input to the scorer."""

    title: str
    source: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    summary: str | None = None


# ---------------------------------------------------------------------------
# Tag taxonomy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TagDefinition:
    """Single tag in the taxonomy."""

    tag: str
    weight: float
    pretty: str
    pattern: re.Pattern[str]


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Order matters only for rationale selection (first match wins ties).
_TAG_DEFINITIONS: tuple[TagDefinition, ...] = (
    TagDefinition(
        "upgrade",
        0.70,
        "Analyst upgrade",
        _compile(
            r"\b(upgrade[sd]?|raise[sd]?\s+(?:rating|target|pt|price\s+target)"
            r"|price\s+target\s+(?:raise|hike)[sd]?|rating\s+raise[sd]?)\b"
        ),
    ),
    TagDefinition(
        "downgrade",
        -0.70,
        "Analyst downgrade",
        _compile(
            r"\b(downgrade[sd]?|cut[s]?\s+(?:rating|target|pt|price\s+target)"
            r"|lower[sd]?\s+price\s+target|rating\s+cut[s]?)\b"
        ),
    ),
    TagDefinition(
        "earnings_beat",
        0.80,
        "Earnings beat",
        _compile(
            r"\b(beat[s]?\s+(?:estimate|expect|forecast|consensus)\w*"
            r"|tops?\s+(?:estimate|expect|forecast|consensus)\w*"
            r"|better[-\s]than[-\s]expected)\b"
        ),
    ),
    TagDefinition(
        "earnings_miss",
        -0.80,
        "Earnings miss",
        _compile(
            r"\b(miss(?:es|ed)?\s+(?:estimate|expect|forecast|consensus)\w*"
            r"|worse[-\s]than[-\s]expected)\b"
        ),
    ),
    TagDefinition(
        "guidance_raise",
        0.75,
        "Guidance raised",
        _compile(
            r"\b(raise[sd]?\s+(?:guidance|outlook|forecast)\w*"
            r"|upbeat\s+outlook|strong\s+outlook|boost[s]?\s+guidance)\b"
        ),
    ),
    TagDefinition(
        "guidance_cut",
        -0.75,
        "Guidance cut",
        _compile(
            r"\b(cut[s]?\s+(?:guidance|outlook|forecast)\w*"
            r"|lower[sd]?\s+(?:guidance|outlook|forecast)\w*"
            r"|slash(?:es|ed)?\s+(?:guidance|outlook)\w*)\b"
        ),
    ),
    TagDefinition(
        "m&a_target",
        0.60,
        "M&A target",
        _compile(
            r"\b(acquired\s+by|takeover\s+target|buyout\s+offer"
            r"|to\s+be\s+acquired|agrees?\s+to\s+be\s+acquired)\b"
        ),
    ),
    TagDefinition(
        "m&a_acquirer",
        0.20,
        "M&A acquirer",
        _compile(r"\b(to\s+acquire|acquiring|agrees?\s+to\s+buy)\b"),
    ),
    TagDefinition(
        "lawsuit",
        -0.40,
        "Lawsuit",
        _compile(r"\b(lawsuit|sued|class\s+action|legal\s+action)\b"),
    ),
    TagDefinition(
        "sec_investigation",
        -0.60,
        "SEC investigation",
        _compile(
            r"\b(sec\s+(?:probe|investigation|subpoena)"
            r"|securities\s+investigation|investigation)\b"
        ),
    ),
    TagDefinition(
        "recall",
        -0.50,
        "Product recall",
        _compile(r"\b(product\s+recall|recall[s]?|faulty)\b"),
    ),
    TagDefinition(
        "buyback",
        0.50,
        "Share buyback",
        _compile(r"\b(buyback|share\s+repurchase|authorized?\s+repurchase)\b"),
    ),
    TagDefinition(
        "dividend_raise",
        0.35,
        "Dividend raised",
        _compile(r"\b(raise[sd]?\s+dividend|dividend\s+(?:hike|increase))\b"),
    ),
    TagDefinition(
        "dividend_cut",
        -0.55,
        "Dividend cut",
        _compile(r"\b(cut[s]?\s+dividend|suspend[s]?\s+dividend|dividend\s+cut)\b"),
    ),
    TagDefinition(
        "insider_buy",
        0.30,
        "Insider buying",
        _compile(
            r"\b(insider\s+(?:buy|buys|buying|purchase[sd]?)"
            r"|bought\s+shares|director\s+bought)\b"
        ),
    ),
    TagDefinition(
        "insider_sell",
        -0.15,
        "Insider selling",
        _compile(
            r"\b(insider\s+(?:sell|sold|selling|sale)"
            r"|sells\s+shares|files\s+to\s+sell)\b"
        ),
    ),
    TagDefinition(
        "ceo_departure",
        -0.40,
        "CEO departure",
        _compile(
            r"\b(ceo\s+(?:resign[sd]?|step[s]?\s+down|depart[s]?|fired|ousted)"
            r"|executive\s+departure)\b"
        ),
    ),
    TagDefinition(
        "ceo_appointment",
        0.0,
        "CEO appointment",
        _compile(r"\b(new\s+ceo|names?\s+(?:new\s+)?ceo|appoints?\s+ceo)\b"),
    ),
    TagDefinition(
        "stock_gains",
        0.40,
        "Stock gains",
        _compile(r"\b(gains|surges?|jumps?|rallies|soars?|climbs?|pops?)\b"),
    ),
    TagDefinition(
        "stock_drops",
        -0.40,
        "Stock drops",
        _compile(r"\b(drops?|falls?|plunges?|tumbles?|sinks?|slides?|dips?|slumps?)\b"),
    ),
    TagDefinition(
        "strong_demand",
        0.50,
        "Strong demand",
        _compile(r"\b(strong demand|record sales|beat expectations|outperforms?|tops? forecast)\b"),
    ),
    TagDefinition(
        "weak_demand",
        -0.50,
        "Weak demand",
        _compile(r"\b(weak demand|disappointing sales|misses expectations|underperforms?)\b"),
    ),
    TagDefinition(
        "price_target_raise",
        0.55,
        "Price target raised",
        _compile(r"\b(raises? (?:price )?target|(?:price )?target (?:raised|hiked|lifted))\b"),
    ),
    TagDefinition(
        "price_target_cut",
        -0.55,
        "Price target cut",
        _compile(r"\b(cuts? (?:price )?target|(?:price )?target (?:cut|lowered|slashed))\b"),
    ),
    TagDefinition(
        "growth",
        0.35,
        "Growth signal",
        _compile(r"\b(revenue growth|growth surge|expanding|acceleration)\b"),
    ),
    TagDefinition(
        "decline",
        -0.35,
        "Decline signal",
        _compile(r"\b(revenue decline|contraction|deceleration|slowdown)\b"),
    ),
    TagDefinition(
        "on_track",
        0.25,
        "On track",
        _compile(r"\b(on track|remains on track|ahead of schedule)\b"),
    ),
    TagDefinition(
        "delay",
        -0.30,
        "Delay",
        _compile(r"\b(delayed?|postponed?|pushed back|setback)\b"),
    ),
    TagDefinition(
        "partnership",
        0.25,
        "Strategic partnership",
        _compile(r"\b(partnership|strategic\s+alliance|teams?\s+up\s+with)\b"),
    ),
    TagDefinition(
        "contract_win",
        0.40,
        "Contract win",
        _compile(r"\b(wins?\s+contract|awarded\s+contract|secures?\s+deal)\b"),
    ),
    TagDefinition(
        "fda_approval",
        0.70,
        "FDA approval",
        _compile(r"\b(fda\s+approv\w*|regulatory\s+approval|approved\s+by\s+fda)\b"),
    ),
    TagDefinition(
        "fda_rejection",
        -0.70,
        "FDA rejection",
        _compile(r"\b(fda\s+reject\w*|complete\s+response\s+letter)\b"),
    ),
)


_TAG_BY_NAME: dict[str, TagDefinition] = {td.tag: td for td in _TAG_DEFINITIONS}


# ---------------------------------------------------------------------------
# Negation handling
# ---------------------------------------------------------------------------


_NEGATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfails?\s+to\s+", re.IGNORECASE),
    re.compile(r"\bfailed\s+to\s+", re.IGNORECASE),
    re.compile(r"\bunable\s+to\s+", re.IGNORECASE),
    re.compile(r"\b(?:does|did|do)\s+not\s+", re.IGNORECASE),
    re.compile(r"\b(?:doesn'?t|didn'?t|don'?t)\s+", re.IGNORECASE),
    re.compile(r"\bwas\s+not\s+", re.IGNORECASE),
    re.compile(r"\bwere\s+not\s+", re.IGNORECASE),
    re.compile(r"\bwasn'?t\s+", re.IGNORECASE),
    re.compile(r"\bweren'?t\s+", re.IGNORECASE),
    re.compile(r"\bno\s+longer\s+", re.IGNORECASE),
    re.compile(r"\bcannot\s+", re.IGNORECASE),
    re.compile(r"\bcan'?t\s+", re.IGNORECASE),
    re.compile(r"\bwon'?t\s+", re.IGNORECASE),
    re.compile(r"\bneither\s+", re.IGNORECASE),
)


# Tags without a clear inverse map to None and are dropped when negated.
_NEGATION_INVERSE_TAGS: dict[str, str | None] = {
    "upgrade": "downgrade",
    "downgrade": "upgrade",
    "earnings_beat": "earnings_miss",
    "earnings_miss": "earnings_beat",
    "guidance_raise": "guidance_cut",
    "guidance_cut": "guidance_raise",
    "buyback": None,
    "dividend_raise": "dividend_cut",
    "dividend_cut": "dividend_raise",
    "insider_buy": "insider_sell",
    "insider_sell": "insider_buy",
    "fda_approval": "fda_rejection",
    "fda_rejection": "fda_approval",
    "lawsuit": None,
    "sec_investigation": None,
    "recall": None,
    "m&a_target": None,
    "m&a_acquirer": None,
    "partnership": None,
    "contract_win": None,
    "ceo_departure": None,
    "ceo_appointment": None,
    "stock_gains": "stock_drops",
    "stock_drops": "stock_gains",
    "strong_demand": "weak_demand",
    "weak_demand": "strong_demand",
    "price_target_raise": "price_target_cut",
    "price_target_cut": "price_target_raise",
    "growth": "decline",
    "decline": "growth",
    "on_track": "delay",
    "delay": "on_track",
}


def _is_negated(text: str, match_start: int, lookback_chars: int = 25) -> bool:
    """Return True if a negation phrase ends within ``lookback_chars`` of ``match_start``.

    Args:
        text: Full headline (and optional summary) text being scanned.
        match_start: Index in ``text`` where a tag regex matched.
        lookback_chars: How far back to search for a negation phrase (default 25 ~= 4-5 words).
    """
    start = max(0, match_start - lookback_chars)
    window = text[start:match_start]
    for pat in _NEGATION_PATTERNS:
        if pat.search(window):
            return True
    return False


# ---------------------------------------------------------------------------
# Ticker-relevance filter
# ---------------------------------------------------------------------------

_COMPANY_NAMES: dict[str, list[str]] = {
    "aapl": ["apple"],
    "msft": ["microsoft"],
    "nvda": ["nvidia"],
    "amzn": ["amazon"],
    "googl": ["google", "alphabet"],
    "goog": ["google", "alphabet"],
    "meta": ["meta", "facebook"],
    "tsla": ["tesla"],
    "avgo": ["broadcom"],
    "amgn": ["amgen"],
    "cost": ["costco"],
    "nflx": ["netflix"],
    "amd": ["amd", "advanced micro"],
    "crm": ["salesforce"],
    "spy": ["s&p 500", "s&p500"],
    "qqq": ["nasdaq", "tech stocks"],
}


def _is_relevant(headline_title: str, ticker: str) -> bool:
    """Check if headline is relevant to the ticker."""
    title_lower = headline_title.lower()
    ticker_lower = ticker.lower()

    # Direct ticker mention
    if ticker_lower in title_lower:
        return True

    # Company name mapping (common tickers)
    names = _COMPANY_NAMES.get(ticker_lower, [])
    for name in names:
        if name in title_lower:
            return True

    return False


_QUALITY_SOURCES: frozenset[str] = frozenset(
    {"bloomberg", "reuters", "wsj", "financial times", "ft", "sec", "finnhub"}
)


_NEUTRAL_TAGS: frozenset[str] = frozenset({"m&a_acquirer", "ceo_appointment"})

_POSITIVE_SINGLE_PRETTY: frozenset[str] = frozenset(
    {
        "upgrade",
        "earnings_beat",
        "guidance_raise",
        "buyback",
        "fda_approval",
        "contract_win",
        "dividend_raise",
        "insider_buy",
        "partnership",
        "m&a_target",
        "stock_gains",
        "strong_demand",
        "price_target_raise",
        "growth",
        "on_track",
    }
)


# ---------------------------------------------------------------------------
# Core scoring primitives
# ---------------------------------------------------------------------------


MAX_HEADLINE_AGE_HOURS = 24  # Reject headlines older than 24 hours

HALF_LIFE_HOURS = 4.0
_DECAY_MIN = 0.05
_DECAY_MAX = 1.0
_DECAY_UNKNOWN = 0.6


def _extract_tags(text: str) -> list[str]:
    """Return deduped list of tag names that match ``text``.

    A tag regex match preceded by a negation phrase (within the lookback window)
    is inverted via ``_NEGATION_INVERSE_TAGS``: the opposite-direction tag is
    emitted if one exists, otherwise the match is dropped.
    """
    tags: list[str] = []
    seen: set[str] = set()
    for td in _TAG_DEFINITIONS:
        match = td.pattern.search(text)
        if match is None:
            continue
        if _is_negated(text, match.start()):
            inverse = _NEGATION_INVERSE_TAGS.get(td.tag)
            if inverse is None:
                # No meaningful inverse — drop the match entirely.
                continue
            if inverse in seen:
                continue
            tags.append(inverse)
            seen.add(inverse)
            continue
        if td.tag in seen:
            continue
        tags.append(td.tag)
        seen.add(td.tag)
    return tags


def _ticker_match(ticker: str, text: str) -> bool:
    """Word-boundary, case-insensitive match of a ticker symbol."""
    if not ticker:
        return False
    return re.search(rf"\b{re.escape(ticker)}\b", text, re.IGNORECASE) is not None


def _compute_relevance(ticker: str, text: str, tags: list[str], source: str | None) -> float:
    base = 0.0
    if _ticker_match(ticker, text):
        base += 0.6
    base += min(0.4, 0.15 * len(tags))
    if source:
        src = source.lower()
        if any(q in src for q in _QUALITY_SOURCES):
            base += 0.1
    relevance = min(1.0, base)
    if relevance == 0.0:
        relevance = 0.1
    return relevance


def _compute_direction(tags: list[str]) -> tuple[Direction, float]:
    net_weight = sum(_TAG_BY_NAME[t].weight for t in tags)
    if net_weight > 0.15:
        return "LONG", min(1.0, abs(net_weight))
    if net_weight < -0.15:
        return "SHORT", min(1.0, abs(net_weight))
    return "NEUTRAL", 0.2 + min(0.3, 0.1 * len(tags))


def _compute_decay(now: datetime, published_at: datetime | None) -> float:
    if published_at is None:
        return _DECAY_UNKNOWN
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours_old = max(0.0, (now - published_at).total_seconds() / 3600.0)
    decay = 0.5 ** (hours_old / HALF_LIFE_HOURS)
    return max(_DECAY_MIN, min(_DECAY_MAX, decay))


def _compute_impact(relevance: float, confidence: float, direction: Direction, decay: float) -> float:
    directional_magnitude = 1.0 if direction != "NEUTRAL" else 0.3
    return round(relevance * confidence * directional_magnitude * decay, 4)


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------


_RATIONALE_MAX = 120


def _truncate(text: str) -> str:
    if len(text) <= _RATIONALE_MAX:
        return text
    # Truncate cleanly with ellipsis, preserve single-sentence feel.
    return text[: _RATIONALE_MAX - 1].rstrip(" ,.-:") + "."


def _pretty(tag: str) -> str:
    return _TAG_BY_NAME[tag].pretty


def _build_rationale(
    ticker: str,
    direction: Direction,
    tags: list[str],
    relevance: float,
) -> str:
    if len(tags) >= 2:
        text = (
            f"Multiple catalysts: {tags[0]}, {tags[1]} — "
            f"{direction} for {ticker}"
        )
        return _truncate(text)

    if len(tags) == 1:
        tag = tags[0]
        pretty = _pretty(tag)
        if direction == "LONG" or tag in _POSITIVE_SINGLE_PRETTY:
            return _truncate(f"{pretty} — bullish for {ticker}")
        if direction == "SHORT":
            return _truncate(f"{pretty} — bearish for {ticker}")
        return _truncate(f"Event noted ({tag}) — limited directional signal")

    # No tags
    if relevance >= 0.5:
        return _truncate("General news mention — limited direct impact")
    return _truncate("Tangential mention — low relevance")


# ---------------------------------------------------------------------------
# Public scorer
# ---------------------------------------------------------------------------


def score_headlines(
    ticker: str,
    headlines: Sequence[RawHeadline],
    now: datetime | None = None,
) -> list[ScoredHeadline]:
    """Score and return headlines sorted by ``impact_score`` descending."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Filter stale headlines (older than MAX_HEADLINE_AGE_HOURS)
    fresh: list[RawHeadline] = []
    for h in headlines:
        if h.published_at is not None:
            pub = h.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age_hours = (now - pub).total_seconds() / 3600
            if age_hours <= MAX_HEADLINE_AGE_HOURS:
                fresh.append(h)
        else:
            fresh.append(h)  # Keep if no timestamp available
    if not fresh:
        fresh = list(headlines[:5])  # Fallback: keep newest 5 if all stale

    # Filter to relevant headlines only
    relevant = [h for h in fresh if _is_relevant(h.title, ticker)]
    if not relevant:
        relevant = list(fresh[:3])  # Fallback: keep top 3 if none match

    scored: list[ScoredHeadline] = []
    for raw in relevant:
        text_parts = [raw.title or ""]
        if raw.summary:
            text_parts.append(raw.summary)
        text = " ".join(text_parts)

        tags = _extract_tags(text)
        relevance = _compute_relevance(ticker, text, tags, raw.source)
        direction, confidence = _compute_direction(tags)
        decay = _compute_decay(now, raw.published_at)
        impact = _compute_impact(relevance, confidence, direction, decay)
        # Ensure minimum impact for relevant articles with clear direction
        if relevance >= 0.5 and direction != "NEUTRAL":
            impact = max(impact, 0.01)
        rationale = _build_rationale(ticker, direction, tags, relevance)

        published_iso: str | None = None
        if raw.published_at is not None:
            pub = raw.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            published_iso = pub.isoformat()

        scored.append(
            ScoredHeadline(
                title=raw.title,
                source=raw.source,
                url=raw.url,
                published_at=published_iso,
                relevance=round(relevance, 4),
                direction=direction,
                confidence=round(confidence, 4),
                impact_score=impact,
                tags=tags,
                rationale=rationale,
            )
        )

    scored.sort(key=lambda s: s.impact_score, reverse=True)
    return scored
