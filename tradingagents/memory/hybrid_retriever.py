"""Hybrid retriever combining BM25 and vector search via Reciprocal Rank Fusion."""

from __future__ import annotations


class HybridRetriever:
    """Combines multiple ranking signals using Reciprocal Rank Fusion (RRF).

    RRF score for document d = sum(1 / (k + rank_i(d))) across all available rankings.
    """

    def __init__(
        self,
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
        rrf_k: int = 60,
    ):
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k

    def query(
        self,
        query_text: str,
        documents: list[str],
        n_results: int = 2,
        bm25_scores: list[float] | None = None,
        vector_scores: list[float] | None = None,
    ) -> list[dict]:
        """Fuse BM25 and vector rankings via RRF and return top results.

        Args:
            query_text: The query string (kept for API consistency).
            documents: The list of documents being ranked.
            n_results: Number of top results to return.
            bm25_scores: Pre-computed BM25 scores per document (same order as documents).
            vector_scores: Pre-computed vector similarity scores per document.

        Returns:
            List of dicts with keys: index, rrf_score, bm25_rank, vector_rank.
        """
        if not documents:
            return []

        n_docs = len(documents)
        rankings: list[list[int]] = []

        # Build BM25 ranking (sorted indices by descending score)
        bm25_rank_map: dict[int, int] = {}
        if bm25_scores is not None:
            bm25_order = sorted(range(n_docs), key=lambda i: bm25_scores[i], reverse=True)
            bm25_rank_map = {doc_idx: rank for rank, doc_idx in enumerate(bm25_order)}
            rankings.append(bm25_order)

        # Build vector ranking
        vector_rank_map: dict[int, int] = {}
        if vector_scores is not None:
            vector_order = sorted(range(n_docs), key=lambda i: vector_scores[i], reverse=True)
            vector_rank_map = {doc_idx: rank for rank, doc_idx in enumerate(vector_order)}
            rankings.append(vector_order)

        if not rankings:
            return []

        # Compute RRF
        rrf_results = self._compute_rrf(rankings, self.rrf_k)

        # Build output
        output: list[dict] = []
        for doc_idx, rrf_score in rrf_results[:n_results]:
            output.append(
                {
                    "index": doc_idx,
                    "rrf_score": rrf_score,
                    "bm25_rank": bm25_rank_map.get(doc_idx),
                    "vector_rank": vector_rank_map.get(doc_idx),
                }
            )
        return output

    def _compute_rrf(
        self, rankings: list[list[int]], k: int
    ) -> list[tuple[int, float]]:
        """Core RRF: for each doc, sum 1/(k + rank) across all rankings.

        Args:
            rankings: List of ranked doc-index lists (each sorted best-first).
            k: RRF constant.

        Returns:
            Sorted list of (doc_index, rrf_score) tuples, descending by score.
        """
        scores: dict[int, float] = {}
        for ranking in rankings:
            for rank, doc_idx in enumerate(ranking):
                scores[doc_idx] = scores.get(doc_idx, 0.0) + 1.0 / (k + rank)

        # Sort descending by score, then ascending by index for stability
        sorted_scores = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return sorted_scores
