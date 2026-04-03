"""Lightweight vector store using cosine similarity — no external dependencies beyond numpy."""

from __future__ import annotations

import math


class VectorStore:
    """In-memory vector store with cosine-similarity search.

    Uses pure Python math when numpy is unavailable, but prefers numpy for speed.
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self._vectors: list[list[float]] = []
        self._np = None
        try:
            import numpy as _np  # noqa: N811

            self._np = _np
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, vectors: list[list[float]]) -> None:
        """Append vectors to the store."""
        for v in vectors:
            if len(v) != self.dimension:
                raise ValueError(
                    f"Expected dimension {self.dimension}, got {len(v)}"
                )
            self._vectors.append(list(v))

    def search(self, query_vector: list[float], n: int) -> list[tuple[int, float]]:
        """Return top-n (index, cosine_similarity) pairs, descending."""
        if not self._vectors:
            return []
        if len(query_vector) != self.dimension:
            raise ValueError(
                f"Expected dimension {self.dimension}, got {len(query_vector)}"
            )

        if self._np is not None:
            return self._search_numpy(query_vector, n)
        return self._search_pure(query_vector, n)

    def clear(self) -> None:
        self._vectors.clear()

    def __len__(self) -> int:
        return len(self._vectors)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _search_numpy(
        self, query_vector: list[float], n: int
    ) -> list[tuple[int, float]]:
        np = self._np
        mat = np.array(self._vectors, dtype=np.float64)
        q = np.array(query_vector, dtype=np.float64)

        # Cosine similarity: dot(a,b) / (||a|| * ||b||)
        dots = mat @ q
        norms = np.linalg.norm(mat, axis=1) * np.linalg.norm(q)
        # Avoid division by zero
        norms = np.where(norms == 0, 1.0, norms)
        sims = dots / norms

        top_n = min(n, len(sims))
        top_idx = np.argsort(sims)[::-1][:top_n]
        return [(int(i), float(sims[i])) for i in top_idx]

    def _search_pure(
        self, query_vector: list[float], n: int
    ) -> list[tuple[int, float]]:
        q_norm = math.sqrt(sum(x * x for x in query_vector))
        results: list[tuple[int, float]] = []
        for idx, vec in enumerate(self._vectors):
            dot = sum(a * b for a, b in zip(vec, query_vector))
            v_norm = math.sqrt(sum(x * x for x in vec))
            denom = v_norm * q_norm
            sim = dot / denom if denom > 0 else 0.0
            results.append((idx, sim))
        results.sort(key=lambda x: -x[1])
        return results[:n]
