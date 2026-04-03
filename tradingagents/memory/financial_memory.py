"""HybridFinancialMemory -- drop-in replacement for FinancialSituationMemory.

Combines BM25 lexical search with TF-IDF vector search via Reciprocal Rank
Fusion (RRF).  Falls back gracefully to BM25-only when the vector pipeline
encounters errors.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from .bm25_store import BM25Store
from .hybrid_retriever import HybridRetriever
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Embedding provider (TF-IDF by default)
# -----------------------------------------------------------------------


class _TfidfEmbeddingProvider:
    """Generates document embeddings using scikit-learn TfidfVectorizer."""

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._vectorizer = TfidfVectorizer()
        self._is_fitted = False

    def embed_all(self, texts: list[str]) -> list[list[float]]:
        """Fit on texts and return one embedding vector per text."""
        if not texts:
            return []
        matrix = self._vectorizer.fit_transform(texts)
        self._is_fitted = True
        return [row.toarray().flatten().tolist() for row in matrix]

    def embed_query(self, query: str) -> list[float]:
        """Transform a single query using the already-fitted vectoriser."""
        if not self._is_fitted:
            raise RuntimeError("Vectorizer not fitted -- call embed_all first")
        vec = self._vectorizer.transform([query])
        return vec.toarray().flatten().tolist()

    @property
    def dimension(self) -> int:
        if not self._is_fitted:
            return 0
        return len(self._vectorizer.vocabulary_)


# -----------------------------------------------------------------------
# HybridFinancialMemory
# -----------------------------------------------------------------------


class HybridFinancialMemory:
    """Memory system combining BM25 and vector search for financial situations.

    API-compatible with FinancialSituationMemory so it can be used as a
    drop-in replacement.

    Parameters
    ----------
    name : str
        Identifier for this memory instance.
    config : dict, optional
        Configuration overrides.  Recognised keys:
        - retrieval_mode -- "hybrid" (default), "bm25", or "vector"
        - bm25_weight    -- weight for BM25 ranking in RRF (default 0.5)
        - vector_weight  -- weight for vector ranking in RRF (default 0.5)
    """

    def __init__(self, name: str, config: dict = None) -> None:
        self.name = name
        cfg = config or {}

        self._mode: str = cfg.get("retrieval_mode", "hybrid")
        bm25_w: float = cfg.get("bm25_weight", 0.5)
        vector_w: float = cfg.get("vector_weight", 0.5)

        # Internal stores
        self._bm25 = BM25Store()
        self._embedder = _TfidfEmbeddingProvider()
        self._vector_store: VectorStore | None = None
        self._retriever = HybridRetriever(
            bm25_weight=bm25_w, vector_weight=vector_w
        )

        # Parallel storage of raw data
        self._situations: list[str] = []
        self._recommendations: list[str] = []

    # Backward-compatible property aliases (FinancialSituationMemory uses these)
    @property
    def documents(self) -> list[str]:
        return self._situations

    @property
    def recommendations(self) -> list[str]:
        return self._recommendations

    # ------------------------------------------------------------------
    # Public API (matches FinancialSituationMemory exactly)
    # ------------------------------------------------------------------

    def add_situations(self, situations_and_advice: List[Tuple[str, str]]) -> None:
        """Add financial situations and their corresponding advice."""
        new_situations = [s for s, _ in situations_and_advice]
        new_recs = [r for _, r in situations_and_advice]

        self._situations.extend(new_situations)
        self._recommendations.extend(new_recs)

        # ---- BM25 ----
        self._bm25.clear()
        self._bm25.add(list(self._situations))

        # ---- Vector ----
        if self._mode != "bm25":
            try:
                embeddings = self._embedder.embed_all(self._situations)
                dim = len(embeddings[0]) if embeddings else 0
                vs = VectorStore(dimension=dim)
                vs.add(embeddings)
                self._vector_store = vs
            except Exception:
                logger.warning(
                    "Vector embedding failed; falling back to BM25-only",
                    exc_info=True,
                )
                self._vector_store = None

    def get_memories(
        self, current_situation: str, n_matches: int = 1
    ) -> List[dict]:
        """Retrieve the top matching memories for current_situation.

        Returns a list of dicts with keys matched_situation,
        recommendation, and similarity_score (normalised 0-1).
        """
        if not self._situations:
            return []

        n = min(n_matches, len(self._situations))

        # ---- Gather scores ------------------------------------------------
        bm25_scores: list[float] | None = None
        vector_scores: list[float] | None = None

        use_bm25 = self._mode in ("hybrid", "bm25")
        use_vector = self._mode in ("hybrid", "vector") and self._vector_store is not None

        if use_bm25:
            bm25_pairs = self._bm25.search(current_situation, len(self._situations))
            score_map = {idx: sc for idx, sc in bm25_pairs}
            bm25_scores = [score_map.get(i, 0.0) for i in range(len(self._situations))]

        if use_vector:
            try:
                q_vec = self._embedder.embed_query(current_situation)
                vec_pairs = self._vector_store.search(q_vec, len(self._situations))
                vscore_map = {idx: sc for idx, sc in vec_pairs}
                vector_scores = [vscore_map.get(i, 0.0) for i in range(len(self._situations))]
            except Exception:
                logger.warning(
                    "Vector search failed; using BM25-only for this query",
                    exc_info=True,
                )
                vector_scores = None
                # If we were in vector-only mode, fall back to bm25
                if bm25_scores is None:
                    bm25_pairs = self._bm25.search(current_situation, len(self._situations))
                    score_map = {idx: sc for idx, sc in bm25_pairs}
                    bm25_scores = [score_map.get(i, 0.0) for i in range(len(self._situations))]

        # ---- Fuse via HybridRetriever -------------------------------------
        fused = self._retriever.query(
            query_text=current_situation,
            documents=self._situations,
            n_results=n,
            bm25_scores=bm25_scores,
            vector_scores=vector_scores,
        )

        if not fused:
            return []

        # ---- Normalise RRF scores to [0, 1] -------------------------------
        max_rrf = fused[0]["rrf_score"] if fused else 1.0
        if max_rrf == 0:
            max_rrf = 1.0

        results: list[dict] = []
        for entry in fused:
            idx = entry["index"]
            results.append(
                {
                    "matched_situation": self._situations[idx],
                    "recommendation": self._recommendations[idx],
                    "similarity_score": entry["rrf_score"] / max_rrf,
                }
            )
        return results

    def clear(self) -> None:
        """Clear all stored memories."""
        self._situations.clear()
        self._recommendations.clear()
        self._bm25.clear()
        if self._vector_store is not None:
            self._vector_store.clear()
            self._vector_store = None
