"""Tests for the lightweight embedding provider."""

from __future__ import annotations

import math
import sys
from unittest import mock

import pytest

from tradingagents.memory.embeddings import (
    EmbeddingProvider,
    TFIDFEmbedder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


CORPUS = [
    "the stock market rose sharply today",
    "bond yields fell as investors sought safety",
    "the stock market crashed and investors panicked",
    "apple released a new iphone model",
    "technology companies reported strong earnings",
]


# ---------------------------------------------------------------------------
# TFIDFEmbedder unit tests
# ---------------------------------------------------------------------------

class TestTFIDFEmbedder:

    def test_fit_builds_vocabulary(self):
        emb = TFIDFEmbedder()
        emb.fit(CORPUS)
        assert emb.dimension > 0
        assert emb._fitted is True

    def test_transform_returns_correct_shape(self):
        emb = TFIDFEmbedder()
        emb.fit(CORPUS)
        vectors = emb.transform(CORPUS)
        assert len(vectors) == len(CORPUS)
        for vec in vectors:
            assert len(vec) == emb.dimension

    def test_dimension_matches_vocab(self):
        emb = TFIDFEmbedder()
        emb.fit(CORPUS)
        assert emb.dimension == len(emb._vocab)

    def test_different_texts_produce_different_vectors(self):
        emb = TFIDFEmbedder()
        vecs = emb.fit_transform(CORPUS)
        # First and fourth texts are quite different topics
        assert vecs[0] != vecs[3]

    def test_similar_texts_higher_cosine(self):
        emb = TFIDFEmbedder()
        vecs = emb.fit_transform(CORPUS)
        # texts 0 and 2 both mention "stock market" and "investors"
        sim_related = _cosine_similarity(vecs[0], vecs[2])
        # texts 0 and 3 are stock-market vs apple-iphone
        sim_unrelated = _cosine_similarity(vecs[0], vecs[3])
        assert sim_related > sim_unrelated

    def test_vectors_are_l2_normalised(self):
        emb = TFIDFEmbedder()
        vecs = emb.fit_transform(CORPUS)
        for vec in vecs:
            norm = math.sqrt(sum(v * v for v in vec))
            assert abs(norm - 1.0) < 1e-6

    def test_unseen_words_handled_gracefully(self):
        emb = TFIDFEmbedder()
        emb.fit(CORPUS)
        # Query contains words not in the corpus
        result = emb.transform(["xyz_unknown_token qqq_nothing"])
        assert len(result) == 1
        assert len(result[0]) == emb.dimension
        # All zeros (normalised to zeros since no known tokens)
        assert all(v == 0.0 for v in result[0])

    def test_transform_before_fit_raises(self):
        emb = TFIDFEmbedder()
        with pytest.raises(RuntimeError, match="fit"):
            emb.transform(["hello"])

    def test_fit_empty_corpus(self):
        emb = TFIDFEmbedder()
        emb.fit([])
        assert emb._fitted is True
        assert emb.dimension == 1  # minimum dimension
        vecs = emb.transform(["anything"])
        assert len(vecs) == 1

    def test_fit_transform_shortcut(self):
        emb = TFIDFEmbedder()
        vecs = emb.fit_transform(CORPUS)
        assert len(vecs) == len(CORPUS)
        assert emb._fitted is True


# ---------------------------------------------------------------------------
# EmbeddingProvider tests
# ---------------------------------------------------------------------------

class TestEmbeddingProvider:

    def test_auto_falls_back_to_tfidf(self):
        """When sentence-transformers is not installed, auto uses tfidf."""
        with mock.patch.dict(sys.modules, {"sentence_transformers": None}):
            provider = EmbeddingProvider(method="auto")
            assert provider.backend == "tfidf"

    def test_tfidf_method_explicit(self):
        provider = EmbeddingProvider(method="tfidf")
        assert provider.backend == "tfidf"

    def test_embed_returns_vectors(self):
        provider = EmbeddingProvider(method="tfidf")
        vecs = provider.embed(CORPUS)
        assert len(vecs) == len(CORPUS)
        for vec in vecs:
            assert isinstance(vec, list)
            assert all(isinstance(v, float) for v in vec)

    def test_embed_query_returns_single_vector(self):
        provider = EmbeddingProvider(method="tfidf")
        provider.embed(CORPUS)  # fit first
        vec = provider.embed_query("stock market today")
        assert isinstance(vec, list)
        assert all(isinstance(v, float) for v in vec)
        assert len(vec) == provider.dimension

    def test_embed_query_correct_dimension(self):
        provider = EmbeddingProvider(method="tfidf")
        provider.embed(CORPUS)
        vec = provider.embed_query("test query about stocks")
        assert len(vec) == provider.dimension

    def test_dimension_positive(self):
        provider = EmbeddingProvider(method="tfidf")
        provider.embed(CORPUS)
        assert provider.dimension > 0

    def test_embed_empty_list(self):
        provider = EmbeddingProvider(method="tfidf")
        result = provider.embed([])
        assert result == []

    def test_embed_query_before_corpus(self):
        """embed_query should work even if no corpus was embedded yet."""
        provider = EmbeddingProvider(method="tfidf")
        vec = provider.embed_query("hello world")
        assert isinstance(vec, list)
        assert len(vec) > 0

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            EmbeddingProvider(method="bogus")

    def test_sentence_transformers_required_but_missing(self):
        with mock.patch.dict(sys.modules, {"sentence_transformers": None}):
            with pytest.raises(ImportError):
                EmbeddingProvider(method="sentence_transformers")

    def test_cosine_similarity_via_provider(self):
        """End-to-end: similar texts should have higher cosine similarity."""
        provider = EmbeddingProvider(method="tfidf")
        vecs = provider.embed(CORPUS)
        sim_related = _cosine_similarity(vecs[0], vecs[2])
        sim_unrelated = _cosine_similarity(vecs[0], vecs[3])
        assert sim_related > sim_unrelated

    def test_multiple_embeds_work(self):
        """Calling embed() multiple times should not break."""
        provider = EmbeddingProvider(method="tfidf")
        v1 = provider.embed(CORPUS[:2])
        v2 = provider.embed(CORPUS[2:])
        assert len(v1) == 2
        assert len(v2) == 3
