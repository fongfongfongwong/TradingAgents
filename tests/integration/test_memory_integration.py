"""Integration tests for memory factory + memory backends."""

import pytest

from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.memory.factory import create_memory


# -----------------------------------------------------------------------
# Shared fixtures
# -----------------------------------------------------------------------

EXAMPLE_DATA = [
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


# -----------------------------------------------------------------------
# Integration: factory -> add -> get -> verify
# -----------------------------------------------------------------------


class TestFactoryEndToEnd:
    """Create memory via factory, add situations, retrieve, verify format."""

    @pytest.fixture(params=["bm25", "hybrid"])
    def loaded_memory(self, request):
        """Return a memory loaded with example data."""
        mem = create_memory("integration_test", {"memory_backend": request.param})
        mem.add_situations(EXAMPLE_DATA)
        return mem

    def test_add_then_get(self, loaded_memory):
        """add_situations -> get_memories returns valid results."""
        results = loaded_memory.get_memories(
            "Rising interest rates affecting consumer spending", n_matches=2
        )
        assert len(results) == 2
        for r in results:
            assert "matched_situation" in r
            assert "recommendation" in r
            assert "similarity_score" in r
            assert isinstance(r["similarity_score"], (int, float))

    def test_top_match_is_relevant(self, loaded_memory):
        """Top match for an inflation query should be the inflation situation."""
        results = loaded_memory.get_memories(
            "High inflation with rising rates", n_matches=1
        )
        assert len(results) == 1
        assert "inflation" in results[0]["matched_situation"].lower()


# -----------------------------------------------------------------------
# Integration: backend switching compatibility
# -----------------------------------------------------------------------


class TestBackendSwitching:
    """Switching backends produces compatible results."""

    def test_same_format_across_backends(self):
        """Both backends return dicts with identical key sets."""
        query = "volatility in tech sector with institutional selling"

        results_by_backend = {}
        for backend in ("bm25", "hybrid"):
            mem = create_memory("switch_test", {"memory_backend": backend})
            mem.add_situations(EXAMPLE_DATA)
            results_by_backend[backend] = mem.get_memories(query, n_matches=2)

        # Both return same number of results
        assert len(results_by_backend["bm25"]) == len(results_by_backend["hybrid"])

        # Both have identical key sets
        for bm25_r, hybrid_r in zip(
            results_by_backend["bm25"], results_by_backend["hybrid"]
        ):
            assert set(bm25_r.keys()) == set(hybrid_r.keys())

    def test_incremental_add(self):
        """Adding data in multiple calls works for both backends."""
        for backend in ("bm25", "hybrid"):
            mem = create_memory("inc_test", {"memory_backend": backend})
            mem.add_situations(EXAMPLE_DATA[:2])
            mem.add_situations(EXAMPLE_DATA[2:])
            results = mem.get_memories("inflation", n_matches=1)
            assert len(results) == 1


# -----------------------------------------------------------------------
# Integration: original FinancialSituationMemory unchanged
# -----------------------------------------------------------------------


class TestOriginalMemoryUnchanged:
    """The original FinancialSituationMemory still works as before."""

    def test_direct_instantiation(self):
        """Creating FinancialSituationMemory directly still works."""
        mem = FinancialSituationMemory("direct_test")
        mem.add_situations(EXAMPLE_DATA)
        results = mem.get_memories("inflation and interest rates", n_matches=2)
        assert len(results) == 2
        assert "matched_situation" in results[0]
        assert "recommendation" in results[0]
        assert "similarity_score" in results[0]

    def test_direct_clear(self):
        """Clearing the original memory works."""
        mem = FinancialSituationMemory("clear_test")
        mem.add_situations(EXAMPLE_DATA)
        mem.clear()
        assert mem.get_memories("anything") == []

    def test_direct_empty(self):
        """Empty original memory returns empty list."""
        mem = FinancialSituationMemory("empty_test")
        assert mem.get_memories("anything") == []

    def test_factory_bm25_matches_direct(self):
        """Factory with bm25 backend produces same results as direct instantiation."""
        query = "inflation and interest rates"

        direct = FinancialSituationMemory("direct")
        direct.add_situations(EXAMPLE_DATA)
        direct_results = direct.get_memories(query, n_matches=2)

        factory = create_memory("factory", {"memory_backend": "bm25"})
        factory.add_situations(EXAMPLE_DATA)
        factory_results = factory.get_memories(query, n_matches=2)

        # Same number of results
        assert len(direct_results) == len(factory_results)

        # Same matched situations (order should be identical for BM25)
        for d, f in zip(direct_results, factory_results):
            assert d["matched_situation"] == f["matched_situation"]
            assert d["recommendation"] == f["recommendation"]
            assert abs(d["similarity_score"] - f["similarity_score"]) < 1e-6
