"""Audit trail logger backed by SQLite with 7-year retention (SEC Rule 204-2)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# SEC Rule 204-2 requires 7-year retention for investment advisory records.
RETENTION_YEARS = 7


class AuditLogger:
    """Immutable audit trail for analysis decisions and trades."""

    def __init__(self, db_path: str = "./data/audit.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL UNIQUE,
                ticker      TEXT NOT NULL,
                trade_date  TEXT NOT NULL,
                config      TEXT NOT NULL,
                agents_used TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL,
                decision    TEXT NOT NULL,
                confidence  REAL NOT NULL,
                reasoning_summary TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id)
            );

            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL,
                trade_data  TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (analysis_id) REFERENCES analyses(analysis_id)
            );

            CREATE INDEX IF NOT EXISTS idx_analyses_ticker ON analyses(ticker);
            CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at);
            CREATE INDEX IF NOT EXISTS idx_decisions_analysis ON decisions(analysis_id);
            CREATE INDEX IF NOT EXISTS idx_trades_analysis ON trades(analysis_id);
            """
        )
        self._conn.commit()

    # -- write operations ----------------------------------------------------

    def log_analysis(
        self,
        analysis_id: str,
        ticker: str,
        trade_date: str,
        config: dict,
        agents_used: list[str],
    ) -> None:
        """Record the start of an analysis run."""
        self._conn.execute(
            """
            INSERT INTO analyses (analysis_id, ticker, trade_date, config, agents_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                ticker,
                trade_date,
                json.dumps(config),
                json.dumps(agents_used),
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        self._conn.commit()

    def log_decision(
        self,
        analysis_id: str,
        decision: str,
        confidence: float,
        reasoning_summary: str,
    ) -> None:
        """Record the final decision for an analysis."""
        self._conn.execute(
            """
            INSERT INTO decisions (analysis_id, decision, confidence, reasoning_summary, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                decision,
                confidence,
                reasoning_summary,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        self._conn.commit()

    def log_trade(self, analysis_id: str, trade: dict) -> None:
        """Record an executed trade."""
        self._conn.execute(
            """
            INSERT INTO trades (analysis_id, trade_data, created_at)
            VALUES (?, ?, ?)
            """,
            (
                analysis_id,
                json.dumps(trade),
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        self._conn.commit()

    # -- read operations -----------------------------------------------------

    def get_history(
        self,
        ticker: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query audit history, optionally filtered by ticker."""
        if ticker is not None:
            rows = self._conn.execute(
                """
                SELECT a.analysis_id, a.ticker, a.trade_date, a.config, a.agents_used,
                       a.created_at,
                       d.decision, d.confidence, d.reasoning_summary
                FROM analyses a
                LEFT JOIN decisions d ON a.analysis_id = d.analysis_id
                WHERE a.ticker = ?
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (ticker, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT a.analysis_id, a.ticker, a.trade_date, a.config, a.agents_used,
                       a.created_at,
                       d.decision, d.confidence, d.reasoning_summary
                FROM analyses a
                LEFT JOIN decisions d ON a.analysis_id = d.analysis_id
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "analysis_id": row["analysis_id"],
                    "ticker": row["ticker"],
                    "trade_date": row["trade_date"],
                    "config": json.loads(row["config"]),
                    "agents_used": json.loads(row["agents_used"]),
                    "created_at": row["created_at"],
                    "decision": row["decision"],
                    "confidence": row["confidence"],
                    "reasoning_summary": row["reasoning_summary"],
                }
            )
        return results

    # -- maintenance ---------------------------------------------------------

    def purge_expired(self) -> int:
        """Delete records older than the retention period. Returns deleted count."""
        cutoff = f"-{RETENTION_YEARS} years"
        cursor = self._conn.execute(
            "DELETE FROM trades WHERE created_at < datetime('now', ?)", (cutoff,)
        )
        count = cursor.rowcount
        self._conn.execute(
            "DELETE FROM decisions WHERE created_at < datetime('now', ?)", (cutoff,)
        )
        self._conn.execute(
            "DELETE FROM analyses WHERE created_at < datetime('now', ?)", (cutoff,)
        )
        self._conn.commit()
        return count

    def close(self) -> None:
        self._conn.close()
