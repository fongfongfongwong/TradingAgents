"""BM25 lexical search store, extracted from the original FinancialSituationMemory."""

from __future__ import annotations

import re
from rank_bm25 import BM25Okapi


class BM25Store:
    """Stores documents and retrieves them using BM25Okapi scoring."""

    def __init__(self) -> None:
        self._texts: list[str] = []
        self._tokenized: list[list[str]] = []
        self._index: BM25Okapi | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, texts: list[str]) -> None:
        """Add texts and rebuild the BM25 index."""
        for t in texts:
            tokens = self._tokenize(t)
            self._texts.append(t)
            self._tokenized.append(tokens)
        self._rebuild()

    def search(self, query: str, n: int) -> list[tuple[int, float]]:
        """Return top-n (index, score) pairs sorted by descending BM25 score."""
        if not self._texts or self._index is None:
            return []
        tokens = self._tokenize(query)
        scores = self._index.get_scores(tokens)
        top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]
        return [(i, float(scores[i])) for i in top]

    def clear(self) -> None:
        self._texts.clear()
        self._tokenized.clear()
        self._index = None

    def __len__(self) -> int:
        return len(self._texts)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text — same logic as existing memory.py."""
        return re.findall(r"\b\w+\b", text.lower())

    def _rebuild(self) -> None:
        if self._tokenized:
            self._index = BM25Okapi(self._tokenized)
        else:
            self._index = None
