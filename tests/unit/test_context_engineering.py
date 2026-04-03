"""Tests for the context engineering module."""

from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.context.token_counter import TokenCounter
from tradingagents.context.budget_manager import TokenBudgetManager, DEFAULT_ALLOCATIONS
from tradingagents.context.pre_filter import ContextPreFilter


# ======================================================================
# TokenCounter tests
# ======================================================================


class TestTokenCounter:
    def test_approximate_count_basic(self):
        counter = TokenCounter(method="approximate")
        text = "hello world test"  # 16 chars -> 4 tokens
        assert counter.count(text) == 4

    def test_approximate_count_longer(self):
        counter = TokenCounter(method="approximate")
        text = "a" * 100  # 100 chars -> 25 tokens
        assert counter.count(text) == 25

    def test_empty_string_returns_zero(self):
        counter = TokenCounter(method="approximate")
        assert counter.count("") == 0

    def test_short_string_returns_at_least_one(self):
        counter = TokenCounter(method="approximate")
        # "hi" is 2 chars -> 0 via //4, but min is 1
        assert counter.count("hi") >= 1

    def test_count_messages(self):
        counter = TokenCounter(method="approximate")
        messages = [
            {"role": "user", "content": "a" * 40},
            {"role": "assistant", "content": "b" * 80},
        ]
        total = counter.count_messages(messages)
        # Each message: content_tokens + role_tokens + 4 overhead
        assert total > 0
        # 40/4=10 + 1(user~4chars->1) + 4 = 15; 80/4=20 + 2(assistant~9chars->2) + 4 = 26; total=41
        assert total == 15 + 26

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError, match="Unknown method"):
            TokenCounter(method="invalid")

    def test_tiktoken_fallback(self):
        """tiktoken method should work (or fall back to approximate)."""
        counter = TokenCounter(method="tiktoken")
        assert counter.method in ("tiktoken", "approximate")
        assert counter.count("hello world") > 0


# ======================================================================
# TokenBudgetManager tests
# ======================================================================


class TestTokenBudgetManager:
    def test_default_allocations_sum_to_one(self):
        total = sum(DEFAULT_ALLOCATIONS.values())
        assert abs(total - 1.0) < 1e-9

    def test_allocate_returns_correct_budget(self):
        mgr = TokenBudgetManager(total_budget=10000)
        assert mgr.allocate("market_data") == 2000  # 0.2 * 10000
        assert mgr.allocate("news") == 2000
        assert mgr.allocate("other") == 500

    def test_allocate_unknown_category_uses_other(self):
        mgr = TokenBudgetManager(total_budget=10000)
        assert mgr.allocate("unknown_category") == 500  # falls back to "other"

    def test_fit_to_budget_no_truncation(self):
        mgr = TokenBudgetManager()
        short = "This is fine."
        assert mgr.fit_to_budget(short, 100) == short

    def test_fit_to_budget_truncates(self):
        mgr = TokenBudgetManager()
        long_text = "First sentence. Second sentence. Third sentence. Fourth sentence. " * 20
        result = mgr.fit_to_budget(long_text, 10)  # ~40 chars budget
        assert result.endswith("[truncated]")
        assert len(result) < len(long_text)

    def test_fit_to_budget_empty_string(self):
        mgr = TokenBudgetManager()
        assert mgr.fit_to_budget("", 100) == ""

    def test_prepare_context_within_budget(self):
        mgr = TokenBudgetManager(total_budget=500)
        data = {
            "market_data": "Stock price went up today. " * 50,
            "news": "Breaking news about the market. " * 50,
        }
        result = mgr.prepare_context(data)
        counter = TokenCounter(method="approximate")
        assert counter.count(result) <= 500

    def test_prepare_context_with_custom_priorities(self):
        mgr = TokenBudgetManager(total_budget=1000)
        data = {
            "market_data": "Price data. " * 100,
            "news": "News content. " * 100,
        }
        priorities = {"market_data": 0.8, "news": 0.2}
        result = mgr.prepare_context(data, priorities=priorities)
        assert "market_data" in result
        assert "news" in result

    def test_stats_after_prepare(self):
        mgr = TokenBudgetManager(total_budget=2000)
        data = {"market_data": "Hello world. " * 10, "news": "Some news. " * 10}
        mgr.prepare_context(data)
        s = mgr.stats()
        assert s["total_budget"] == 2000
        assert "market_data" in s["last_usage"]
        assert "news" in s["last_usage"]
        assert s["total_used"] > 0


# ======================================================================
# ContextPreFilter tests
# ======================================================================


class TestContextPreFilter:
    def test_filter_by_recency_keeps_recent(self):
        pf = ContextPreFilter()
        now = datetime.now(timezone.utc)
        items = [
            {"title": "Recent", "timestamp": (now - timedelta(hours=1)).isoformat()},
            {"title": "Old", "timestamp": (now - timedelta(hours=200)).isoformat()},
        ]
        result = pf.filter_by_recency(items, max_age_hours=168)
        assert len(result) == 1
        assert result[0]["title"] == "Recent"

    def test_filter_by_recency_keeps_items_without_timestamp(self):
        pf = ContextPreFilter()
        items = [{"title": "No TS"}]
        result = pf.filter_by_recency(items, max_age_hours=24)
        assert len(result) == 1

    def test_filter_by_relevance_exact_match(self):
        pf = ContextPreFilter()
        items = [
            {"title": "AAPL earnings report", "content": "Apple posted strong results."},
            {"title": "MSFT update", "content": "Microsoft news."},
        ]
        result = pf.filter_by_relevance(items, ticker="AAPL")
        assert len(result) == 1
        assert result[0]["title"] == "AAPL earnings report"

    def test_filter_by_relevance_substring_match(self):
        pf = ContextPreFilter()
        items = [
            {"title": "Report", "content": "The AAPL-related fund performed well."},
        ]
        # "AAPL" appears as substring inside "AAPL-related" -- word boundary may match
        result = pf.filter_by_relevance(items, ticker="AAPL", min_score=0.3)
        assert len(result) >= 1

    def test_filter_by_relevance_no_match(self):
        pf = ContextPreFilter()
        items = [{"title": "Weather report", "content": "Sunny skies ahead."}]
        result = pf.filter_by_relevance(items, ticker="TSLA", min_score=0.3)
        assert len(result) == 0

    def test_deduplicate_removes_duplicates(self):
        pf = ContextPreFilter()
        items = [
            {"title": "Stock market rallies on strong earnings"},
            {"title": "Stock market rallies on strong earnings report"},
            {"title": "Completely different article about weather"},
        ]
        result = pf.deduplicate(items, similarity_threshold=0.8)
        assert len(result) == 2

    def test_deduplicate_keeps_all_unique(self):
        pf = ContextPreFilter()
        items = [
            {"title": "Apple earnings beat expectations"},
            {"title": "Federal Reserve holds rates steady"},
            {"title": "Oil prices surge on supply concerns"},
        ]
        result = pf.deduplicate(items, similarity_threshold=0.8)
        assert len(result) == 3

    def test_filter_by_recency_datetime_objects(self):
        pf = ContextPreFilter()
        now = datetime.now(timezone.utc)
        items = [
            {"title": "A", "timestamp": now - timedelta(hours=5)},
            {"title": "B", "timestamp": now - timedelta(days=30)},
        ]
        result = pf.filter_by_recency(items, max_age_hours=24)
        assert len(result) == 1
        assert result[0]["title"] == "A"
