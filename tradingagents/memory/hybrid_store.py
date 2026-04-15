"""Hybrid Memory Store with BM25 keyword matching.

Phase 1: BM25-only retrieval (vector embeddings added later).
Stores and retrieves agent reflections, semantic lessons,
trade records, and trade outcomes in a per-agent SQLite database.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from tradingagents.schemas.v3 import (
    AgentReflection,
    SemanticLesson,
    TradeOutcome,
    TradeRecord,
)

_VALID_TYPES = frozenset({"reflection", "lesson", "trade", "outcome"})

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id  TEXT PRIMARY KEY,
    agent_id   TEXT    NOT NULL,
    type       TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    tags       TEXT    NOT NULL DEFAULT '',
    importance REAL    NOT NULL DEFAULT 0.0,
    stored_at  TEXT    NOT NULL
);
"""

_CREATE_INDEX_TYPE = """
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories (type);
"""

_CREATE_INDEX_AGENT = """
CREATE INDEX IF NOT EXISTS idx_memories_agent_id ON memories (agent_id);
"""

_CREATE_INDEX_STORED = """
CREATE INDEX IF NOT EXISTS idx_memories_stored_at ON memories (stored_at);
"""


def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into word tokens."""
    return re.findall(r"[a-z0-9_]+", text.lower())


def _bm25_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """Simple TF-based score: count of matching query terms / total query terms.

    Returns a float in [0.0, 1.0].
    """
    if not query_tokens:
        return 0.0

    doc_token_set = set(doc_tokens)
    matches = sum(1 for qt in query_tokens if qt in doc_token_set)
    return matches / len(query_tokens)


class HybridMemoryStore:
    """Per-agent memory store with BM25 keyword matching.

    Phase 1: BM25 only (vector embeddings added later).
    Stores and retrieves agent reflections and semantic lessons.
    """

    def __init__(self, agent_id: str, db_path: str = "./data/memory.db") -> None:
        """Initialize store for a specific agent.

        Args:
            agent_id: Unique identifier for the agent owning this store.
            db_path: Path to the SQLite database file.
        """
        self._agent_id = agent_id
        self._db_path = db_path

        # Ensure parent directory exists.
        db_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(db_dir, exist_ok=True)

        # Initialize schema.
        self._execute_ddl()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection (thread-safe: each call gets its own)."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _execute_ddl(self) -> None:
        """Create tables and indexes if they do not exist."""
        conn = self._connect()
        try:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX_TYPE)
            conn.execute(_CREATE_INDEX_AGENT)
            conn.execute(_CREATE_INDEX_STORED)
            conn.commit()
        finally:
            conn.close()

    def _store(
        self,
        memory_type: str,
        content_json: str,
        tags: list[str],
        importance: float,
    ) -> str:
        """Insert a memory row and return its unique memory_id."""
        memory_id = str(uuid.uuid4())
        stored_at = datetime.now(timezone.utc).isoformat()
        tags_str = ",".join(tags) if tags else ""

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO memories (memory_id, agent_id, type, content, tags, importance, stored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (memory_id, self._agent_id, memory_type, content_json, tags_str, importance, stored_at),
            )
            conn.commit()
        finally:
            conn.close()

        return memory_id

    # ------------------------------------------------------------------
    # Public store methods
    # ------------------------------------------------------------------

    def store_reflection(self, reflection: AgentReflection) -> str:
        """Store an agent reflection. Return a unique memory_id."""
        return self._store(
            memory_type="reflection",
            content_json=reflection.model_dump_json(),
            tags=list(reflection.tags),
            importance=reflection.importance_score,
        )

    def store_lesson(self, lesson: SemanticLesson) -> str:
        """Store a semantic lesson. Return a unique memory_id."""
        return self._store(
            memory_type="lesson",
            content_json=lesson.model_dump_json(),
            tags=list(lesson.tags),
            importance=lesson.importance,
        )

    def store_trade(self, record: TradeRecord) -> str:
        """Store a trade record. Return a unique memory_id."""
        return self._store(
            memory_type="trade",
            content_json=record.model_dump_json(),
            tags=[record.ticker, record.direction.value],
            importance=0.5,
        )

    def store_outcome(self, outcome: TradeOutcome) -> str:
        """Store a trade outcome. Return a unique memory_id."""
        importance = min(abs(outcome.pnl_pct) / 10.0, 1.0)
        return self._store(
            memory_type="outcome",
            content_json=outcome.model_dump_json(),
            tags=[outcome.ticker],
            importance=importance,
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = 5,
        memory_type: str | None = None,
    ) -> list[dict]:
        """BM25 search across stored memories.

        Args:
            query: Free-text search query.
            n_results: Maximum number of results to return.
            memory_type: Optional filter -- "reflection", "lesson", "trade",
                         "outcome", or None for all types.

        Returns:
            List of dicts with keys: memory_id, type, content, score, stored_at.
            Sorted by BM25 score descending.
        """
        if memory_type is not None and memory_type not in _VALID_TYPES:
            raise ValueError(f"Invalid memory_type: {memory_type!r}. Must be one of {_VALID_TYPES}")

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        conn = self._connect()
        try:
            if memory_type is not None:
                cursor = conn.execute(
                    "SELECT memory_id, type, content, tags, stored_at FROM memories WHERE agent_id = ? AND type = ?",
                    (self._agent_id, memory_type),
                )
            else:
                cursor = conn.execute(
                    "SELECT memory_id, type, content, tags, stored_at FROM memories WHERE agent_id = ?",
                    (self._agent_id,),
                )

            scored: list[dict] = []
            for row in cursor:
                # Tokenize content + tags for matching.
                doc_text = row["content"] + " " + row["tags"]
                doc_tokens = _tokenize(doc_text)
                score = _bm25_score(query_tokens, doc_tokens)
                if score > 0.0:
                    scored.append(
                        {
                            "memory_id": row["memory_id"],
                            "type": row["type"],
                            "content": row["content"],
                            "score": score,
                            "stored_at": row["stored_at"],
                        }
                    )
        finally:
            conn.close()

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:n_results]

    def get_recent(
        self,
        n: int = 10,
        memory_type: str | None = None,
    ) -> list[dict]:
        """Get most recent memories, optionally filtered by type.

        Args:
            n: Maximum number of results.
            memory_type: Optional type filter.

        Returns:
            List of dicts with keys: memory_id, type, content, stored_at.
            Sorted by stored_at descending (most recent first).
        """
        if memory_type is not None and memory_type not in _VALID_TYPES:
            raise ValueError(f"Invalid memory_type: {memory_type!r}. Must be one of {_VALID_TYPES}")

        conn = self._connect()
        try:
            if memory_type is not None:
                cursor = conn.execute(
                    "SELECT memory_id, type, content, stored_at FROM memories WHERE agent_id = ? AND type = ? ORDER BY stored_at DESC LIMIT ?",
                    (self._agent_id, memory_type, n),
                )
            else:
                cursor = conn.execute(
                    "SELECT memory_id, type, content, stored_at FROM memories WHERE agent_id = ? ORDER BY stored_at DESC LIMIT ?",
                    (self._agent_id, n),
                )

            return [
                {
                    "memory_id": row["memory_id"],
                    "type": row["type"],
                    "content": row["content"],
                    "stored_at": row["stored_at"],
                }
                for row in cursor
            ]
        finally:
            conn.close()

    def count(self) -> dict[str, int]:
        """Return count of memories by type."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT type, COUNT(*) as cnt FROM memories WHERE agent_id = ? GROUP BY type",
                (self._agent_id,),
            )
            counts: dict[str, int] = {t: 0 for t in _VALID_TYPES}
            for row in cursor:
                counts[row["type"]] = row["cnt"]
            return counts
        finally:
            conn.close()


# ======================================================================
# Inline tests
# ======================================================================

if __name__ == "__main__":
    import sys
    import tempfile

    sys.path.insert(0, "/Users/fongyeungwong/Documents/Trading-Agent/TradingAgents")

    db = os.path.join(tempfile.mkdtemp(), "test_memory.db")
    store = HybridMemoryStore(agent_id="thesis", db_path=db)

    # Test 1: Store and retrieve a reflection
    ref = AgentReflection(
        agent="thesis",
        trade_ticker="AAPL",
        trade_date="2026-04-01",
        prediction_correct=True,
        what_i_got_right="Momentum alignment predicted correctly",
        what_i_missed="Underestimated earnings impact",
        lesson="Weight earnings catalysts higher when RSI is neutral",
        confidence_was_calibrated=True,
        tags=["earnings", "momentum", "AAPL"],
        importance_score=0.8,
    )
    mid = store.store_reflection(ref)
    assert mid is not None
    results = store.search("earnings momentum AAPL", n_results=5)
    assert len(results) >= 1
    assert results[0]["type"] == "reflection"
    print(f"Test 1 PASSED: Store + search reflection (score={results[0]['score']:.2f})")

    # Test 2: Store a lesson
    lesson = SemanticLesson(
        lesson="When VIX > 25 and RSI neutral, reduce position size by 30%",
        evidence_count=5,
        first_observed="2026-01-15",
        last_observed="2026-04-01",
        tags=["vix", "position_sizing", "volatility"],
        importance=0.9,
    )
    store.store_lesson(lesson)
    results = store.search("VIX volatility position sizing")
    assert len(results) >= 1
    print("Test 2 PASSED: Store + search lesson")

    # Test 3: Count
    counts = store.count()
    assert counts["reflection"] >= 1
    assert counts["lesson"] >= 1
    print(f"Test 3 PASSED: Counts {counts}")

    # Test 4: Get recent
    recent = store.get_recent(n=5)
    assert len(recent) >= 2
    print("Test 4 PASSED: Get recent")

    print("\nAll tests PASSED")
