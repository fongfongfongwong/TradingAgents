"""
Lightweight embedding provider for TradingAgents vector store.

Strategy: use sentence-transformers if available, otherwise fall back to
a pure-Python TF-IDF implementation (zero external dependencies).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional


# ---------------------------------------------------------------------------
# TF-IDF Embedder (pure Python, no external deps)
# ---------------------------------------------------------------------------

class TFIDFEmbedder:
    """Pure-Python TF-IDF vectoriser.  No sklearn or numpy required."""

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}       # token -> index
        self._idf: dict[str, float] = {}       # token -> idf weight
        self._fitted = False

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lowercase + split on non-alphanumeric characters."""
        return re.findall(r"[a-z0-9]+", text.lower())

    # -- public API -------------------------------------------------------

    def fit(self, texts: list[str]) -> "TFIDFEmbedder":
        """Build vocabulary and IDF weights from *texts*."""
        if not texts:
            self._vocab = {}
            self._idf = {}
            self._fitted = True
            return self

        doc_tokens = [self._tokenize(t) for t in texts]
        n_docs = len(doc_tokens)

        # document frequency
        df: Counter[str] = Counter()
        for tokens in doc_tokens:
            df.update(set(tokens))

        # build vocab (sorted for determinism)
        self._vocab = {tok: idx for idx, tok in enumerate(sorted(df))}

        # IDF: log((1 + n) / (1 + df)) + 1  (smooth variant)
        self._idf = {
            tok: math.log((1 + n_docs) / (1 + freq)) + 1
            for tok, freq in df.items()
        }

        self._fitted = True
        return self

    def transform(self, texts: list[str]) -> list[list[float]]:
        """Convert *texts* to TF-IDF vectors.  Unseen tokens are ignored."""
        if not self._fitted:
            raise RuntimeError("TFIDFEmbedder must be fit() before transform()")

        dim = self.dimension
        if dim == 0:
            return [[0.0] for _ in texts]

        vectors: list[list[float]] = []
        for text in texts:
            tokens = self._tokenize(text)
            tf: Counter[str] = Counter(tokens)
            vec = [0.0] * dim
            for tok, count in tf.items():
                if tok in self._vocab:
                    idx = self._vocab[tok]
                    vec[idx] = count * self._idf.get(tok, 1.0)
            # L2-normalise
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors

    def fit_transform(self, texts: list[str]) -> list[list[float]]:
        return self.fit(texts).transform(texts)

    @property
    def dimension(self) -> int:
        return max(len(self._vocab), 1) if self._fitted else 0


# ---------------------------------------------------------------------------
# SentenceTransformer Embedder (optional dependency)
# ---------------------------------------------------------------------------

class SentenceTransformerEmbedder:
    """Thin wrapper around ``sentence_transformers.SentenceTransformer``."""

    MODEL_NAME = "all-MiniLM-L6-v2"
    DIMENSION = 384

    def __init__(self) -> None:
        # Import lazily so the module loads even without the package.
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        self._model = SentenceTransformer(self.MODEL_NAME)

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [vec.tolist() for vec in embeddings]

    def embed_query(self, query: str) -> list[float]:
        return self.embed([query])[0]

    @property
    def dimension(self) -> int:
        return self.DIMENSION


# ---------------------------------------------------------------------------
# Unified Embedding Provider
# ---------------------------------------------------------------------------

class EmbeddingProvider:
    """Unified embedding interface.

    Parameters
    ----------
    method : str
        ``"auto"``  -- try sentence-transformers, fall back to TF-IDF.
        ``"tfidf"`` -- always use TF-IDF.
        ``"sentence_transformers"`` -- require sentence-transformers.
    """

    def __init__(self, method: str = "auto") -> None:
        if method not in ("auto", "tfidf", "sentence_transformers"):
            raise ValueError(f"Unknown embedding method: {method!r}")

        self._method = method
        self._st: Optional[SentenceTransformerEmbedder] = None
        self._tfidf: Optional[TFIDFEmbedder] = None
        self._using: str = ""  # "sentence_transformers" or "tfidf"

        if method in ("auto", "sentence_transformers"):
            try:
                self._st = SentenceTransformerEmbedder()
                self._using = "sentence_transformers"
            except ImportError:
                if method == "sentence_transformers":
                    raise
                # auto mode: fall through to tfidf

        if self._st is None:
            self._tfidf = TFIDFEmbedder()
            self._using = "tfidf"

    # -- public API -------------------------------------------------------

    @property
    def backend(self) -> str:
        """Which backend is active: ``"sentence_transformers"`` or ``"tfidf"``."""
        return self._using

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a list of texts."""
        if not texts:
            return []

        if self._st is not None:
            return self._st.embed(texts)

        assert self._tfidf is not None
        # TF-IDF needs to (re)fit on the corpus to have a vocabulary.
        return self._tfidf.fit_transform(texts)

    def embed_query(self, query: str) -> list[float]:
        """Return the embedding vector for a single query string."""
        if self._st is not None:
            return self._st.embed_query(query)

        assert self._tfidf is not None
        if not self._tfidf._fitted or self._tfidf.dimension == 0:
            # No corpus seen yet; fit on the query itself.
            self._tfidf.fit([query])
        return self._tfidf.transform([query])[0]

    @property
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        if self._st is not None:
            return self._st.dimension

        assert self._tfidf is not None
        return self._tfidf.dimension
