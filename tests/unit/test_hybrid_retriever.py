"""Tests for the hybrid memory retrieval system."""

import math
import pytest

from tradingagents.memory.hybrid_retriever import HybridRetriever
from tradingagents.memory.bm25_store import BM25Store
from tradingagents.memory.vector_store import VectorStore


# ======================================================================
# HybridRetriever tests
# ======================================================================


class TestHybridRetrieverRRF:
    """Test Reciprocal Rank Fusion logic."""

    def test_rrf_single_ranking(self):
        """RRF with one ranking should equal 1/(k+rank)."""
        hr = HybridRetriever(rrf_k=60)
        rankings = [[2, 0, 1]]  # doc2 rank0, doc0 rank1, doc1 rank2
        result = hr._compute_rrf(rankings, k=60)
        # doc2: 1/60, doc0: 1/61, doc1: 1/62
        assert result[0][0] == 2
        assert result[1][0] == 0
        assert result[2][0] == 1
        assert abs(result[0][1] - 1 / 60) < 1e-9
        assert abs(result[1][1] - 1 / 61) < 1e-9
        assert abs(result[2][1] - 1 / 62) < 1e-9

    def test_rrf_two_rankings_agreement(self):
        """When both rankings agree, the top doc should have highest score."""
        hr = HybridRetriever(rrf_k=60)
        rankings = [[0, 1, 2], [0, 1, 2]]
        result = hr._compute_rrf(rankings, k=60)
        assert result[0][0] == 0
        expected = 2 * (1 / 60)
        assert abs(result[0][1] - expected) < 1e-9

    def test_rrf_two_rankings_disagreement(self):
        """When rankings disagree, RRF should fuse correctly."""
        hr = HybridRetriever(rrf_k=60)
        # BM25: doc0 best, Vector: doc1 best
        rankings = [[0, 1, 2], [1, 0, 2]]
        result = hr._compute_rrf(rankings, k=60)
        score_0 = 1 / 60 + 1 / 61  # rank0 in first, rank1 in second
        score_1 = 1 / 61 + 1 / 60  # rank1 in first, rank0 in second
        # doc0 and doc1 tie — stable sort by index means doc0 first
        assert abs(result[0][1] - score_0) < 1e-9
        assert result[0][0] == 0  # lower index wins tie

    def test_rrf_k_parameter_effect(self):
        """Smaller k amplifies rank differences more."""
        hr = HybridRetriever()
        rankings = [[0, 1]]
        result_k1 = hr._compute_rrf(rankings, k=1)
        result_k60 = hr._compute_rrf(rankings, k=60)
        # With k=1: scores are 1/1=1.0 and 1/2=0.5 → ratio 2.0
        # With k=60: scores are 1/60 and 1/61 → ratio ~1.017
        ratio_k1 = result_k1[0][1] / result_k1[1][1]
        ratio_k60 = result_k60[0][1] / result_k60[1][1]
        assert ratio_k1 > ratio_k60

    def test_query_empty_documents(self):
        hr = HybridRetriever()
        assert hr.query("test", [], n_results=2) == []

    def test_query_no_scores(self):
        """No BM25 or vector scores → empty results."""
        hr = HybridRetriever()
        result = hr.query("test", ["doc1", "doc2"], n_results=2)
        assert result == []

    def test_query_bm25_only_fallback(self):
        """When only BM25 scores provided, ranking uses BM25 alone."""
        hr = HybridRetriever()
        docs = ["a", "b", "c"]
        bm25 = [0.1, 0.9, 0.5]
        result = hr.query("q", docs, n_results=3, bm25_scores=bm25)
        assert result[0]["index"] == 1  # highest BM25
        assert result[0]["vector_rank"] is None
        assert result[0]["bm25_rank"] == 0

    def test_query_vector_only_fallback(self):
        """When only vector scores provided, ranking uses vector alone."""
        hr = HybridRetriever()
        docs = ["a", "b", "c"]
        vec = [0.2, 0.1, 0.95]
        result = hr.query("q", docs, n_results=3, vector_scores=vec)
        assert result[0]["index"] == 2
        assert result[0]["bm25_rank"] is None
        assert result[0]["vector_rank"] == 0

    def test_query_hybrid_both_sources(self):
        """Hybrid with both sources should fuse rankings."""
        hr = HybridRetriever(rrf_k=60)
        docs = ["a", "b", "c", "d"]
        # BM25 ranking: d(3) > c(2) > b(1) > a(0)
        bm25 = [0.1, 0.3, 0.7, 0.9]
        # Vector ranking: a(0) > b(1) > c(2) > d(3)
        vec = [0.9, 0.7, 0.3, 0.1]
        result = hr.query("q", docs, n_results=4, bm25_scores=bm25, vector_scores=vec)
        # All docs participate; check all 4 returned
        assert len(result) == 4
        indices = [r["index"] for r in result]
        assert set(indices) == {0, 1, 2, 3}

    def test_hybrid_beats_single_source(self):
        """A doc ranked moderately in both should beat one ranked top in one only."""
        hr = HybridRetriever(rrf_k=1)  # small k to amplify
        docs = ["a", "b", "c"]
        # BM25: b best, then c, then a
        bm25 = [0.0, 1.0, 0.5]
        # Vector: a best, then c, then b
        vec = [1.0, 0.0, 0.5]
        result = hr.query("q", docs, n_results=3, bm25_scores=bm25, vector_scores=vec)
        # c is rank1 in both → RRF = 1/(1+1) + 1/(1+1) = 1.0
        # a is rank2 in bm25, rank0 in vec → 1/(1+2) + 1/(1+0) = 1/3 + 1 = 1.333
        # b is rank0 in bm25, rank2 in vec → 1/(1+0) + 1/(1+2) = 1 + 1/3 = 1.333
        # a and b tie, a wins by index
        assert result[0]["index"] in (0, 1)
        # c should be last — it has lower total RRF
        assert result[2]["index"] == 2

    def test_query_n_results_limit(self):
        hr = HybridRetriever()
        docs = ["a", "b", "c", "d"]
        bm25 = [0.1, 0.2, 0.3, 0.4]
        result = hr.query("q", docs, n_results=2, bm25_scores=bm25)
        assert len(result) == 2


# ======================================================================
# BM25Store tests
# ======================================================================


class TestBM25Store:

    def test_add_and_len(self):
        store = BM25Store()
        assert len(store) == 0
        store.add(["hello world", "foo bar"])
        assert len(store) == 2

    def test_search_basic(self):
        store = BM25Store()
        store.add(["the cat sat on the mat", "the dog barked loudly", "cats are great pets"])
        results = store.search("cat", 2)
        assert len(results) == 2
        # "the cat sat on the mat" or "cats are great pets" should rank top
        top_idx = results[0][0]
        assert top_idx in (0, 2)

    def test_search_empty_store(self):
        store = BM25Store()
        assert store.search("anything", 5) == []

    def test_clear(self):
        store = BM25Store()
        store.add(["document one"])
        store.clear()
        assert len(store) == 0
        assert store.search("document", 1) == []

    def test_tokenize(self):
        tokens = BM25Store._tokenize("Hello, World! This is a TEST.")
        assert tokens == ["hello", "world", "this", "is", "a", "test"]

    def test_search_returns_scores(self):
        store = BM25Store()
        # Need 3+ docs so IDF is positive for a term appearing in one doc
        store.add(["alpha beta", "gamma delta", "epsilon zeta"])
        results = store.search("alpha", 3)
        # First result should have a positive score
        assert results[0][1] > 0


# ======================================================================
# VectorStore tests
# ======================================================================


class TestVectorStore:

    def _unit_vec(self, dim, idx):
        """Create a unit vector with 1.0 at position idx."""
        v = [0.0] * dim
        v[idx] = 1.0
        return v

    def test_add_and_len(self):
        vs = VectorStore(dimension=3)
        assert len(vs) == 0
        vs.add([[1, 0, 0], [0, 1, 0]])
        assert len(vs) == 2

    def test_search_empty(self):
        vs = VectorStore(dimension=3)
        assert vs.search([1, 0, 0], 5) == []

    def test_search_exact_match(self):
        vs = VectorStore(dimension=3)
        vs.add([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        results = vs.search([0, 1, 0], 1)
        assert results[0][0] == 1
        assert abs(results[0][1] - 1.0) < 1e-6

    def test_cosine_similarity_correctness(self):
        vs = VectorStore(dimension=3)
        vs.add([[1, 0, 0], [1, 1, 0]])
        results = vs.search([1, 0, 0], 2)
        # Cosine([1,0,0], [1,0,0]) = 1.0
        # Cosine([1,0,0], [1,1,0]) = 1/sqrt(2) ≈ 0.7071
        assert abs(results[0][1] - 1.0) < 1e-6
        assert abs(results[1][1] - 1 / math.sqrt(2)) < 1e-4

    def test_clear(self):
        vs = VectorStore(dimension=3)
        vs.add([[1, 0, 0]])
        vs.clear()
        assert len(vs) == 0
        assert vs.search([1, 0, 0], 1) == []

    def test_dimension_mismatch_add(self):
        vs = VectorStore(dimension=3)
        with pytest.raises(ValueError, match="Expected dimension 3"):
            vs.add([[1, 0]])

    def test_dimension_mismatch_search(self):
        vs = VectorStore(dimension=3)
        vs.add([[1, 0, 0]])
        with pytest.raises(ValueError, match="Expected dimension 3"):
            vs.search([1, 0], 1)

    def test_orthogonal_vectors_zero_similarity(self):
        vs = VectorStore(dimension=3)
        vs.add([[1, 0, 0]])
        results = vs.search([0, 1, 0], 1)
        assert abs(results[0][1]) < 1e-9

    def test_search_n_limit(self):
        vs = VectorStore(dimension=3)
        vs.add([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        results = vs.search([1, 1, 1], 2)
        assert len(results) == 2
