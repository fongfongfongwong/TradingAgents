"""Snapshot Pinning & Audit Log -- persist and retrieve TickerBriefing snapshots.

Uses a local SQLite database so that every materialised briefing can be
pinned, replayed and audited.  Each function creates its own connection
to keep the interface stateless and thread-friendly.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from tradingagents.schemas.v3 import TickerBriefing

DB_PATH = "./data/snapshots.db"


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Return a new connection to the snapshot database."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create the ``snapshots`` table and ticker index if they do not exist."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                ticker      TEXT NOT NULL,
                date        TEXT NOT NULL,
                stored_at   TEXT NOT NULL,
                data        TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON snapshots (ticker)"
        )
        conn.commit()
    finally:
        conn.close()


def store_snapshot(briefing: TickerBriefing, db_path: str = DB_PATH) -> str:
    """Persist a *TickerBriefing* and return its ``snapshot_id``.

    The ``stored_at`` timestamp is always UTC ISO-8601.
    """
    init_db(db_path)
    stored_at = datetime.now(timezone.utc).isoformat()
    data_json = briefing.model_dump_json()

    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO snapshots
                (snapshot_id, ticker, date, stored_at, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                briefing.snapshot_id,
                briefing.ticker,
                briefing.date,
                stored_at,
                data_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return briefing.snapshot_id


def load_snapshot(
    snapshot_id: str, db_path: str = DB_PATH
) -> Optional[TickerBriefing]:
    """Load a previously stored snapshot by its id, or return *None*."""
    init_db(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT data FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return TickerBriefing.model_validate_json(row["data"])


def list_snapshots(
    ticker: Optional[str] = None, db_path: str = DB_PATH
) -> list[dict]:
    """Return audit-log entries for all (or filtered-by-ticker) snapshots.

    Each entry is a plain dict with keys:
    ``snapshot_id``, ``ticker``, ``date``, ``stored_at``.
    """
    init_db(db_path)
    conn = _connect(db_path)
    try:
        if ticker is not None:
            rows = conn.execute(
                """
                SELECT snapshot_id, ticker, date, stored_at
                FROM snapshots
                WHERE ticker = ?
                ORDER BY stored_at
                """,
                (ticker,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT snapshot_id, ticker, date, stored_at
                FROM snapshots
                ORDER BY stored_at
                """
            ).fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]


# -- Tests -----------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import uuid

    from tradingagents.schemas.v3 import (
        EventCalendar,
        MacroContext,
        NewsContext,
        OptionsContext,
        PriceContext,
        SocialContext,
    )

    def _make_briefing(
        ticker: str = "AAPL", date: str = "2025-01-15"
    ) -> TickerBriefing:
        """Build a minimal TickerBriefing for testing."""
        return TickerBriefing(
            ticker=ticker,
            date=date,
            snapshot_id=str(uuid.uuid4()),
            price=PriceContext(
                price=150.0,
                change_1d_pct=1.5,
                change_5d_pct=3.0,
                change_20d_pct=5.0,
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
            options=OptionsContext(
                put_call_ratio=0.9,
                iv_rank_percentile=45.0,
            ),
            news=NewsContext(
                top_headlines=["AAPL beats earnings"],
                headline_sentiment_avg=0.1,
            ),
            social=SocialContext(
                mention_volume_vs_avg=1.3,
                sentiment_score=0.2,
            ),
            macro=MacroContext(
                fed_funds_rate=5.25,
                vix_level=18.0,
            ),
            events=EventCalendar(
                next_earnings_days=30,
            ),
            data_gaps=[],
        )

    def test_roundtrip() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            briefing = _make_briefing()

            sid = store_snapshot(briefing, db_path=db)
            assert sid == briefing.snapshot_id

            loaded = load_snapshot(sid, db_path=db)
            assert loaded is not None
            assert loaded.ticker == briefing.ticker
            assert loaded.snapshot_id == briefing.snapshot_id
            assert loaded.price.price == briefing.price.price

        print("PASS: test_roundtrip")

    def test_not_found() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            result = load_snapshot("nonexistent-id", db_path=db)
            assert result is None

        print("PASS: test_not_found")

    def test_list() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")

            b1 = _make_briefing(ticker="AAPL", date="2025-01-15")
            b2 = _make_briefing(ticker="GOOG", date="2025-01-15")
            b3 = _make_briefing(ticker="AAPL", date="2025-01-16")

            store_snapshot(b1, db_path=db)
            store_snapshot(b2, db_path=db)
            store_snapshot(b3, db_path=db)

            all_snaps = list_snapshots(db_path=db)
            assert len(all_snaps) == 3

            aapl_snaps = list_snapshots(ticker="AAPL", db_path=db)
            assert len(aapl_snaps) == 2
            assert all(s["ticker"] == "AAPL" for s in aapl_snaps)

            for snap in all_snaps:
                assert "snapshot_id" in snap
                assert "ticker" in snap
                assert "date" in snap
                assert "stored_at" in snap

        print("PASS: test_list")

    test_roundtrip()
    test_not_found()
    test_list()
    print("\nAll snapshot tests passed.")
