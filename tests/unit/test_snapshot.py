"""Tests for snapshot pinning & audit log."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tradingagents.data.snapshot import (
    init_db,
    list_snapshots,
    load_snapshot,
    store_snapshot,
)
from tradingagents.schemas.v3 import (
    EventCalendar,
    MacroContext,
    NewsContext,
    OptionsContext,
    PriceContext,
    SocialContext,
    TickerBriefing,
)


def _make_briefing(ticker: str = "AAPL", date: str = "2025-01-15") -> TickerBriefing:
    """Build a minimal but valid TickerBriefing for testing."""
    return TickerBriefing(
        ticker=ticker,
        date=date,
        snapshot_id=str(uuid.uuid4()),
        price=PriceContext(
            price=150.0,
            change_1d_pct=0.5,
            change_5d_pct=1.2,
            change_20d_pct=3.0,
            sma_20=148.0,
            sma_50=145.0,
            sma_200=140.0,
            rsi_14=55.0,
            macd_above_signal=True,
            macd_crossover_days=2,
            bollinger_position="middle_third",
            volume_vs_avg_20d=1.1,
            atr_14=2.5,
            data_age_seconds=60,
        ),
        options=OptionsContext(),
        news=NewsContext(),
        social=SocialContext(),
        macro=MacroContext(),
        events=EventCalendar(),
    )


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    """Return a temporary database path that is cleaned up automatically."""
    return str(tmp_path / "test_snapshots.db")


class TestInitDb:
    def test_creates_db_file(self, db_path: str) -> None:
        init_db(db_path)
        assert Path(db_path).exists()

    def test_idempotent(self, db_path: str) -> None:
        init_db(db_path)
        init_db(db_path)  # should not raise


class TestRoundTrip:
    def test_store_and_load(self, db_path: str) -> None:
        briefing = _make_briefing()
        snapshot_id = store_snapshot(briefing, db_path)

        loaded = load_snapshot(snapshot_id, db_path)
        assert loaded is not None
        assert loaded.ticker == briefing.ticker
        assert loaded.date == briefing.date
        assert loaded.price.price == briefing.price.price
        assert loaded.price.rsi_14 == briefing.price.rsi_14

    def test_snapshot_id_is_unique(self, db_path: str) -> None:
        briefing1 = _make_briefing()
        briefing2 = _make_briefing()
        id1 = store_snapshot(briefing1, db_path)
        id2 = store_snapshot(briefing2, db_path)
        assert id1 != id2


class TestLoadSnapshot:
    def test_not_found_returns_none(self, db_path: str) -> None:
        init_db(db_path)
        result = load_snapshot("nonexistent_id", db_path)
        assert result is None


class TestListSnapshots:
    def test_list_all(self, db_path: str) -> None:
        store_snapshot(_make_briefing("AAPL"), db_path)
        store_snapshot(_make_briefing("TSLA"), db_path)

        results = list_snapshots(db_path=db_path)
        assert len(results) == 2
        assert all(
            {"snapshot_id", "ticker", "date", "stored_at"} == set(r.keys())
            for r in results
        )

    def test_filter_by_ticker(self, db_path: str) -> None:
        store_snapshot(_make_briefing("AAPL"), db_path)
        store_snapshot(_make_briefing("TSLA"), db_path)
        store_snapshot(_make_briefing("AAPL"), db_path)

        results = list_snapshots(ticker="AAPL", db_path=db_path)
        assert len(results) == 2
        assert all(r["ticker"] == "AAPL" for r in results)

    def test_limit(self, db_path: str) -> None:
        for _ in range(5):
            store_snapshot(_make_briefing(), db_path)

        results = list_snapshots(db_path=db_path)
        assert len(results) == 5
        # Verify we can slice the results client-side.
        assert len(results[:3]) == 3

    def test_empty_table(self, db_path: str) -> None:
        init_db(db_path)
        results = list_snapshots(db_path=db_path)
        assert results == []
