"""Unit tests for the memory factory."""

import pytest

from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.memory.factory import create_memory


# -----------------------------------------------------------------------
# Shared test data
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
]


# -----------------------------------------------------------------------
# Tests: backend selection
# -----------------------------------------------------------------------


class TestFactoryBackendSelection:
    """Test that factory returns the correct backend class."""

    def test_bm25_backend(self):
        """Factory with 'bm25' returns FinancialSituationMemory."""
        mem = create_memory("test", {"memory_backend": "bm25"})
        assert isinstance(mem, FinancialSituationMemory)

    def test_hybrid_backend(self):
        """Factory with 'hybrid' returns HybridFinancialMemory (if available)."""
        try:
            from tradingagents.memory.financial_memory import HybridFinancialMemory

            mem = create_memory("test", {"memory_backend": "hybrid"})
            assert isinstance(mem, HybridFinancialMemory)
        except ImportError:
            # If hybrid not available, should still return a working memory
            mem = create_memory("test", {"memory_backend": "hybrid"})
            assert isinstance(mem, FinancialSituationMemory)

    def test_no_config_returns_bm25(self):
        """Factory with no config returns FinancialSituationMemory (backward compat)."""
        mem = create_memory("test")
        assert isinstance(mem, FinancialSituationMemory)

    def test_empty_config_returns_bm25(self):
        """Factory with empty dict returns FinancialSituationMemory."""
        mem = create_memory("test", {})
        assert isinstance(mem, FinancialSituationMemory)

    def test_unknown_backend_returns_bm25(self):
        """Unknown backend value falls back to BM25."""
        mem = create_memory("test", {"memory_backend": "unknown_backend"})
        assert isinstance(mem, FinancialSituationMemory)


# -----------------------------------------------------------------------
# Tests: API compatibility
# -----------------------------------------------------------------------


class TestIdenticalAPI:
    """Both backends must expose the same public methods."""

    REQUIRED_METHODS = ["add_situations", "get_memories", "clear"]

    def test_bm25_has_required_api(self):
        mem = create_memory("test", {"memory_backend": "bm25"})
        for method in self.REQUIRED_METHODS:
            assert hasattr(mem, method), f"BM25 backend missing method: {method}"
            assert callable(getattr(mem, method))

    def test_hybrid_has_required_api(self):
        mem = create_memory("test", {"memory_backend": "hybrid"})
        for method in self.REQUIRED_METHODS:
            assert hasattr(mem, method), f"Hybrid backend missing method: {method}"
            assert callable(getattr(mem, method))

    def test_both_have_name_attribute(self):
        bm25 = create_memory("test_bm25", {"memory_backend": "bm25"})
        hybrid = create_memory("test_hybrid", {"memory_backend": "hybrid"})
        assert bm25.name == "test_bm25"
        assert hybrid.name == "test_hybrid"


# -----------------------------------------------------------------------
# Tests: output format compatibility
# -----------------------------------------------------------------------


class TestOutputFormat:
    """Both backends must produce the same output format from get_memories."""

    REQUIRED_KEYS = {"matched_situation", "recommendation", "similarity_score"}

    @pytest.fixture(params=["bm25", "hybrid"])
    def memory(self, request):
        mem = create_memory("test", {"memory_backend": request.param})
        mem.add_situations(EXAMPLE_DATA)
        return mem

    def test_get_memories_returns_list(self, memory):
        results = memory.get_memories("inflation and interest rates", n_matches=2)
        assert isinstance(results, list)

    def test_get_memories_dict_keys(self, memory):
        results = memory.get_memories("inflation and interest rates", n_matches=1)
        assert len(results) >= 1
        for result in results:
            assert isinstance(result, dict)
            assert set(result.keys()) == self.REQUIRED_KEYS

    def test_similarity_score_is_numeric(self, memory):
        results = memory.get_memories("inflation and interest rates", n_matches=1)
        for result in results:
            assert isinstance(result["similarity_score"], (int, float))

    def test_empty_memory_returns_empty_list(self):
        for backend in ("bm25", "hybrid"):
            mem = create_memory("empty", {"memory_backend": backend})
            assert mem.get_memories("anything") == []

    def test_clear_then_get_returns_empty(self, memory):
        memory.clear()
        assert memory.get_memories("inflation") == []
