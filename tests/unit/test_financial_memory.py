"""Tests for HybridFinancialMemory -- drop-in replacement for FinancialSituationMemory."""

import pytest
from tradingagents.memory.financial_memory import HybridFinancialMemory


# ---- Shared fixtures -------------------------------------------------------

SAMPLE_DATA = [
    (
        "High inflation rate with rising interest rates and declining consumer spending",
        "Consider defensive sectors like consumer staples and utilities.",
    ),
    (
        "Tech sector showing high volatility with increasing institutional selling pressure",
        "Reduce exposure to high-growth tech stocks.",
    ),
    (
        "Strong dollar affecting emerging markets with increasing forex volatility",
        "Hedge currency exposure in international positions.",
    ),
    (
        "Market showing signs of sector rotation with rising yields",
        "Rebalance portfolio to maintain target allocations.",
    ),
]


def _make_memory(mode="hybrid", data=None):
    """Helper to build a pre-loaded memory instance."""
    mem = HybridFinancialMemory("test", config={"retrieval_mode": mode})
    if data is not None:
        mem.add_situations(data)
    return mem


# ---- Core API tests --------------------------------------------------------


class TestAddAndGet:
    def test_add_and_get_returns_correct_format(self):
        mem = _make_memory(data=SAMPLE_DATA)
        results = mem.get_memories("inflation and interest rates", n_matches=1)
        assert len(results) == 1
        r = results[0]
        assert "matched_situation" in r
        assert "recommendation" in r
        assert "similarity_score" in r

    def test_similarity_score_in_range(self):
        mem = _make_memory(data=SAMPLE_DATA)
        results = mem.get_memories("tech volatility", n_matches=4)
        for r in results:
            assert 0.0 <= r["similarity_score"] <= 1.0

    def test_relevant_situation_scores_higher(self):
        mem = _make_memory(data=SAMPLE_DATA)
        results = mem.get_memories("tech sector volatility institutional selling", n_matches=4)
        # The tech-related situation should rank first
        assert "tech" in results[0]["matched_situation"].lower() or "Tech" in results[0]["matched_situation"]

    def test_n_matches_respected(self):
        mem = _make_memory(data=SAMPLE_DATA)
        for n in (1, 2, 3):
            results = mem.get_memories("inflation", n_matches=n)
            assert len(results) == n

    def test_n_matches_capped_at_corpus_size(self):
        mem = _make_memory(data=SAMPLE_DATA)
        results = mem.get_memories("inflation", n_matches=100)
        assert len(results) == len(SAMPLE_DATA)

    def test_empty_memory_returns_empty(self):
        mem = HybridFinancialMemory("empty")
        assert mem.get_memories("anything") == []

    def test_clear_works(self):
        mem = _make_memory(data=SAMPLE_DATA)
        assert mem.get_memories("inflation", n_matches=1) != []
        mem.clear()
        assert mem.get_memories("inflation", n_matches=1) == []


# ---- Mode-specific tests ---------------------------------------------------


class TestBM25OnlyMode:
    def test_bm25_only_returns_results(self):
        mem = _make_memory(mode="bm25", data=SAMPLE_DATA)
        results = mem.get_memories("inflation interest rates", n_matches=2)
        assert len(results) == 2

    def test_bm25_only_relevant_ranking(self):
        mem = _make_memory(mode="bm25", data=SAMPLE_DATA)
        results = mem.get_memories("inflation interest rates", n_matches=4)
        assert "inflation" in results[0]["matched_situation"].lower()


class TestVectorOnlyMode:
    def test_vector_only_returns_results(self):
        mem = _make_memory(mode="vector", data=SAMPLE_DATA)
        results = mem.get_memories("tech sector volatility", n_matches=2)
        assert len(results) == 2


class TestHybridMode:
    def test_hybrid_returns_results(self):
        mem = _make_memory(mode="hybrid", data=SAMPLE_DATA)
        results = mem.get_memories("emerging market forex", n_matches=2)
        assert len(results) == 2

    def test_hybrid_same_or_better_than_bm25(self):
        """Hybrid should rank at least as well as BM25-only for a clear query."""
        query = "tech sector volatility institutional selling"
        bm25_mem = _make_memory(mode="bm25", data=SAMPLE_DATA)
        hybrid_mem = _make_memory(mode="hybrid", data=SAMPLE_DATA)

        bm25_top = bm25_mem.get_memories(query, n_matches=1)[0]["matched_situation"]
        hybrid_top = hybrid_mem.get_memories(query, n_matches=1)[0]["matched_situation"]

        # Both should surface the tech-related situation
        assert "tech" in bm25_top.lower() or "Tech" in bm25_top
        assert "tech" in hybrid_top.lower() or "Tech" in hybrid_top


# ---- Backward compatibility -------------------------------------------------


class TestBackwardCompat:
    """Verify the public API matches FinancialSituationMemory exactly."""

    def test_init_signature(self):
        # name only
        m1 = HybridFinancialMemory("a")
        assert m1.name == "a"
        # name + config
        m2 = HybridFinancialMemory("b", config={"retrieval_mode": "bm25"})
        assert m2.name == "b"

    def test_has_add_situations(self):
        mem = HybridFinancialMemory("c")
        assert callable(getattr(mem, "add_situations", None))

    def test_has_get_memories(self):
        mem = HybridFinancialMemory("d")
        assert callable(getattr(mem, "get_memories", None))

    def test_has_clear(self):
        mem = HybridFinancialMemory("e")
        assert callable(getattr(mem, "clear", None))

    def test_import_from_memory_module(self):
        from tradingagents.memory import HybridFinancialMemory as HFM
        assert HFM is HybridFinancialMemory


# ---- Edge cases -------------------------------------------------------------


class TestEdgeCases:
    def test_single_document(self):
        mem = _make_memory(data=[SAMPLE_DATA[0]])
        results = mem.get_memories("inflation", n_matches=1)
        assert len(results) == 1
        assert results[0]["similarity_score"] == 1.0

    def test_incremental_add(self):
        mem = HybridFinancialMemory("inc")
        mem.add_situations(SAMPLE_DATA[:2])
        assert len(mem.get_memories("inflation", n_matches=2)) == 2
        mem.add_situations(SAMPLE_DATA[2:])
        assert len(mem.get_memories("inflation", n_matches=4)) == 4

    def test_top_result_score_is_one(self):
        """The best match should always have a normalised score of 1.0."""
        mem = _make_memory(data=SAMPLE_DATA)
        results = mem.get_memories("inflation", n_matches=1)
        assert results[0]["similarity_score"] == pytest.approx(1.0)

    def test_config_weights(self):
        mem = HybridFinancialMemory(
            "w", config={"bm25_weight": 0.8, "vector_weight": 0.2}
        )
        mem.add_situations(SAMPLE_DATA)
        results = mem.get_memories("inflation", n_matches=1)
        assert len(results) == 1
