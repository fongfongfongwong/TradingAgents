"""Tests for SQLiteMemoryStore persistence layer."""

import os
import tempfile
import threading

import pytest

from tradingagents.memory.persistence import SQLiteMemoryStore


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def store():
    """In-memory store for fast isolated tests."""
    s = SQLiteMemoryStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a temporary SQLite file."""
    return str(tmp_path / "test_memories.db")


# ------------------------------------------------------------------
# Basic CRUD
# ------------------------------------------------------------------

class TestSaveAndLoad:
    def test_roundtrip(self, store):
        pairs = [("bull market", "buy equities"), ("bear market", "hedge")]
        store.save("analyst", pairs)
        loaded = store.load("analyst")
        assert loaded == pairs

    def test_load_empty(self, store):
        assert store.load("nonexistent") == []

    def test_save_empty_list(self, store):
        store.save("empty", [])
        assert store.load("empty") == []

    def test_multiple_names_isolation(self, store):
        store.save("alpha", [("s1", "r1")])
        store.save("beta", [("s2", "r2"), ("s3", "r3")])
        assert store.load("alpha") == [("s1", "r1")]
        assert store.load("beta") == [("s2", "r2"), ("s3", "r3")]

    def test_append_preserves_order(self, store):
        store.save("log", [("first", "a")])
        store.save("log", [("second", "b")])
        loaded = store.load("log")
        assert loaded == [("first", "a"), ("second", "b")]


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------

class TestDelete:
    def test_delete_existing(self, store):
        store.save("tmp", [("x", "y")])
        store.delete("tmp")
        assert store.load("tmp") == []

    def test_delete_nonexistent_is_noop(self, store):
        store.delete("ghost")  # should not raise


# ------------------------------------------------------------------
# Listing and counting
# ------------------------------------------------------------------

class TestListAndCount:
    def test_list_names_empty(self, store):
        assert store.list_names() == []

    def test_list_names(self, store):
        store.save("b_name", [("s", "r")])
        store.save("a_name", [("s", "r")])
        assert store.list_names() == ["a_name", "b_name"]

    def test_count(self, store):
        store.save("counter", [("a", "1"), ("b", "2"), ("c", "3")])
        assert store.count("counter") == 3

    def test_count_zero(self, store):
        assert store.count("nothing") == 0


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------

class TestExport:
    def test_export_all(self, store):
        store.save("x", [("s1", "r1")])
        store.save("y", [("s2", "r2"), ("s3", "r3")])
        exported = store.export_all()
        assert exported == {
            "x": [("s1", "r1")],
            "y": [("s2", "r2"), ("s3", "r3")],
        }

    def test_export_empty(self, store):
        assert store.export_all() == {}


# ------------------------------------------------------------------
# File-based persistence
# ------------------------------------------------------------------

class TestFilePersistence:
    def test_write_close_reopen(self, tmp_db):
        store = SQLiteMemoryStore(db_path=tmp_db)
        store.save("persist", [("situation", "advice")])
        store.close()

        store2 = SQLiteMemoryStore(db_path=tmp_db)
        assert store2.load("persist") == [("situation", "advice")]
        store2.close()


# ------------------------------------------------------------------
# Table prefix
# ------------------------------------------------------------------

class TestTablePrefix:
    def test_prefix_isolation(self, tmp_db):
        a = SQLiteMemoryStore(db_path=tmp_db, table_prefix="a_")
        b = SQLiteMemoryStore(db_path=tmp_db, table_prefix="b_")
        a.save("shared_name", [("sa", "ra")])
        b.save("shared_name", [("sb", "rb")])
        assert a.load("shared_name") == [("sa", "ra")]
        assert b.load("shared_name") == [("sb", "rb")]
        a.close()
        b.close()


# ------------------------------------------------------------------
# Thread safety
# ------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_writes(self, tmp_db):
        store = SQLiteMemoryStore(db_path=tmp_db)
        errors: list[Exception] = []

        def writer(thread_id: int):
            try:
                for i in range(50):
                    store.save(f"thread_{thread_id}", [(f"sit_{i}", f"rec_{i}")])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent write errors: {errors}"
        for t_id in range(4):
            assert store.count(f"thread_{t_id}") == 50
        store.close()

    def test_concurrent_read_write(self, tmp_db):
        store = SQLiteMemoryStore(db_path=tmp_db)
        store.save("shared", [("init", "val")])
        errors: list[Exception] = []

        def reader():
            try:
                for _ in range(100):
                    store.load("shared")
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(100):
                    store.save("shared", [(f"s{i}", f"r{i}")])
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent read/write errors: {errors}"
        store.close()


# ------------------------------------------------------------------
# Context manager
# ------------------------------------------------------------------

class TestContextManager:
    def test_context_manager(self, tmp_db):
        with SQLiteMemoryStore(db_path=tmp_db) as store:
            store.save("ctx", [("a", "b")])
            assert store.load("ctx") == [("a", "b")]
        # connection closed; reopen to verify persistence
        with SQLiteMemoryStore(db_path=tmp_db) as store2:
            assert store2.load("ctx") == [("a", "b")]
