"""Pre-filtering utilities to reduce context before budget allocation."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher


class ContextPreFilter:
    """Filter, deduplicate and rank context items before they reach the LLM."""

    # ------------------------------------------------------------------
    # Recency
    # ------------------------------------------------------------------

    def filter_by_recency(
        self,
        items: list[dict],
        max_age_hours: int = 168,
    ) -> list[dict]:
        """Keep only items whose timestamp is within *max_age_hours*.

        Each item should contain a ``"timestamp"`` key holding either an
        ISO-8601 string or a :class:`~datetime.datetime` instance.
        Items without a parseable timestamp are kept by default.
        """
        now = datetime.now(timezone.utc)
        result: list[dict] = []
        for item in items:
            ts = self._parse_timestamp(item.get("timestamp"))
            if ts is None:
                result.append(item)
                continue
            age_hours = (now - ts).total_seconds() / 3600
            if age_hours <= max_age_hours:
                result.append(item)
        return result

    # ------------------------------------------------------------------
    # Relevance
    # ------------------------------------------------------------------

    def filter_by_relevance(
        self,
        items: list[dict],
        ticker: str,
        min_score: float = 0.3,
    ) -> list[dict]:
        """Keep items that mention *ticker* or closely related terms.

        A simple keyword-scoring approach is used:
        * Exact ticker match in title or content -> 1.0
        * Ticker appears as substring -> 0.5
        * No match -> 0.0

        Items scoring >= *min_score* are returned.
        """
        ticker_upper = ticker.upper()
        result: list[dict] = []
        for item in items:
            score = self._relevance_score(item, ticker_upper)
            if score >= min_score:
                result.append(item)
        return result

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def deduplicate(
        self,
        items: list[dict],
        similarity_threshold: float = 0.8,
    ) -> list[dict]:
        """Remove near-duplicate items based on title/summary similarity.

        Uses :class:`difflib.SequenceMatcher` to compute similarity
        ratios.  The first occurrence of each cluster is kept.
        """
        kept: list[dict] = []
        for item in items:
            text = self._dedup_key(item)
            is_dup = False
            for existing in kept:
                existing_text = self._dedup_key(existing)
                ratio = SequenceMatcher(None, text, existing_text).ratio()
                if ratio >= similarity_threshold:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(item)
        return kept

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(value) -> datetime | None:
        """Try to coerce *value* into an aware UTC datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            # Try fromisoformat first (handles +00:00, microseconds, etc.)
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                pass
            # Fallback to common strptime formats.
            for fmt in (
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(value, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
        return None

    @staticmethod
    def _relevance_score(item: dict, ticker_upper: str) -> float:
        """Compute a simple relevance score for *item* against *ticker_upper*."""
        searchable = " ".join(
            str(item.get(k, "")) for k in ("title", "content", "summary", "text")
        ).upper()

        # Exact word match (surrounded by non-alpha chars).
        import re

        if re.search(rf"\b{re.escape(ticker_upper)}\b", searchable):
            return 1.0
        if ticker_upper in searchable:
            return 0.5
        return 0.0

    @staticmethod
    def _dedup_key(item: dict) -> str:
        """Build a string used for duplicate comparison."""
        parts = [str(item.get(k, "")) for k in ("title", "summary", "content")]
        return " ".join(parts).strip().lower()
