"""Persistent cost tracker backed by SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class PersistentCostTracker:
    """Records LLM costs in SQLite for cross-session persistence."""

    def __init__(self, db_path: str = "./data/costs.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cost_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL,
                agent_name  TEXT NOT NULL,
                model       TEXT NOT NULL,
                input_tokens  INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd    REAL NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cost_recorded_at ON cost_records(recorded_at)"
        )
        self._conn.commit()

    # -- recording -----------------------------------------------------------

    def record(
        self,
        analysis_id: str,
        agent_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Record a single LLM call cost."""
        self._conn.execute(
            """
            INSERT INTO cost_records
                (analysis_id, agent_name, model, input_tokens, output_tokens, cost_usd, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                agent_name,
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        self._conn.commit()

    # -- queries -------------------------------------------------------------

    def daily_total(self, date: str | None = None) -> float:
        """Sum of costs for a given date (YYYY-MM-DD). Defaults to today."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM cost_records WHERE recorded_at LIKE ?",
            (f"{date}%",),
        ).fetchone()
        return float(row["total"])

    def monthly_total(self, month: str | None = None) -> float:
        """Sum of costs for a given month (YYYY-MM). Defaults to current month."""
        if month is None:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM cost_records WHERE recorded_at LIKE ?",
            (f"{month}%",),
        ).fetchone()
        return float(row["total"])

    def by_model(self, days: int = 30) -> dict[str, float]:
        """Cost breakdown by model over the last N days."""
        rows = self._conn.execute(
            """
            SELECT model, SUM(cost_usd) AS total
            FROM cost_records
            WHERE recorded_at >= datetime('now', ?)
            GROUP BY model
            ORDER BY total DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        return {row["model"]: float(row["total"]) for row in rows}

    def by_agent(self, days: int = 30) -> dict[str, float]:
        """Cost breakdown by agent over the last N days."""
        rows = self._conn.execute(
            """
            SELECT agent_name, SUM(cost_usd) AS total
            FROM cost_records
            WHERE recorded_at >= datetime('now', ?)
            GROUP BY agent_name
            ORDER BY total DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        return {row["agent_name"]: float(row["total"]) for row in rows}

    def summary(self, days: int = 30) -> dict:
        """Complete cost summary for the last N days."""
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0.0) AS total,
                   COUNT(*) AS call_count,
                   COALESCE(SUM(input_tokens), 0) AS total_input,
                   COALESCE(SUM(output_tokens), 0) AS total_output
            FROM cost_records
            WHERE recorded_at >= datetime('now', ?)
            """,
            (f"-{days} days",),
        ).fetchone()
        return {
            "total_cost_usd": float(row["total"]),
            "call_count": row["call_count"],
            "total_input_tokens": row["total_input"],
            "total_output_tokens": row["total_output"],
            "by_model": self.by_model(days),
            "by_agent": self.by_agent(days),
            "daily_total": self.daily_total(),
            "monthly_total": self.monthly_total(),
        }

    def budget_check(
        self,
        daily_limit: float | None = None,
        monthly_limit: float | None = None,
    ) -> dict:
        """Check whether current spend is within budget limits."""
        daily_used = self.daily_total()
        monthly_used = self.monthly_total()

        within = True
        if daily_limit is not None and daily_used > daily_limit:
            within = False
        if monthly_limit is not None and monthly_used > monthly_limit:
            within = False

        return {
            "within_budget": within,
            "daily_used": daily_used,
            "monthly_used": monthly_used,
        }

    def close(self) -> None:
        self._conn.close()
