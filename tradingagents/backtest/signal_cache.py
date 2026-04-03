"""Signal cache for avoiding redundant LLM agent calls during backtesting.

Stores signals as JSON files on disk keyed by (ticker, date).
Uses only Python stdlib.
"""

from __future__ import annotations

import json
import os
import shutil


class SignalCache:
    """Disk-backed cache for trading signals."""

    def __init__(self, cache_dir: str = "./data/signal_cache") -> None:
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _path(self, ticker: str, date: str) -> str:
        safe_ticker = ticker.replace("/", "_").replace("\\", "_")
        safe_date = date.replace("/", "-")
        return os.path.join(self.cache_dir, f"{safe_ticker}_{safe_date}.json")

    def save(self, ticker: str, date: str, signal: dict) -> None:
        """Persist a signal to the cache."""
        path = self._path(ticker, date)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(signal, f, indent=2)

    def load(self, ticker: str, date: str) -> dict | None:
        """Load a cached signal, or return ``None`` if not present."""
        path = self._path(ticker, date)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def has(self, ticker: str, date: str) -> bool:
        """Check whether a signal is cached."""
        return os.path.isfile(self._path(ticker, date))

    def clear(self) -> None:
        """Remove all cached signals."""
        if os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir, exist_ok=True)
