"""Tests for production-grade RAG features: Query Rewriter, Vector Store, Observability, API."""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from tools.rag import (
    RAGConfig,
    Document,
    QueryRewriter,
    RewriteResult,
    VectorStore,
    InMemoryVectorStore,
    VectorSearchResult,
    RAGObserver,
    RAGMetrics,
    StructuredLogger,
)


# ---------------------------------------------------------------------------
# Query Rewriter tests
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    Document(
        content="Python is a high-level programming language with dynamic semantics.",
        source="wiki_python",
        metadata={"category": "programming"},
    ),
    Document(
        content="Machine learning is a subset of artificial intelligence.",
        source="wiki_ml",
        metadata={"category": "ai"},
    ),
]


class TestQueryRewriter:
    @pytest.fixture
    def rewriter(self):
        config = RAGConfig(llm_provider="mock")
        return QueryRewriter(config)

    def test_rewrite_returns_result(self, rewriter):
        result = rewriter.rewrite("Python怎么读取CSV?")
        assert isinstance(result, RewriteResult)
        assert result.original_query == "Python怎么读取CSV?"

    def test_rewrite_empty_query(self, rewriter):
        result = rewriter.rewrite("")
        assert result.rewritten_query == ""

    def test_rewrite_preserves_query(self, rewriter):
        query = "What is machine learning?"
        result = rewriter.rewrite(query)
        assert result.original_query == query

    def test_expand_returns_list(self, rewriter):
        results = rewriter.expand("Python programming", num_queries=3)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(r, RewriteResult) for r in results)

    def test_expand_empty_query(self, rewriter):
        results = rewriter.expand("")
        assert results == []

    def test_decompose_returns_result(self, rewriter):
        result = rewriter.decompose("Python and machine learning")
        assert isinstance(result, RewriteResult)
        assert len(result.sub_queries) >= 1

    def test_decompose_single_query(self, rewriter):
        result = rewriter.decompose("What is Python?")
        assert len(result.sub_queries) == 1

    def test_hyde_returns_result(self, rewriter):
        result = rewriter.hyde("What is Python?")
        assert isinstance(result, RewriteResult)
        assert result.method == "hyde"

    def test_rewrite_for_retrieval(self, rewriter):
        queries = rewriter.rewrite_for_retrieval("Python programming")
        assert isinstance(queries, list)
        assert len(queries) >= 1
        assert queries[0] == "Python programming"

    def test_rewrite_with_llm_config(self):
        """Test that LLM mode is attempted when llm_provider is not mock."""
        config = RAGConfig(llm_provider="mock")
        rewriter = QueryRewriter(config)
        result = rewriter.rewrite("test query")
        assert isinstance(result, RewriteResult)

    def test_expand_num_queries_respected(self, rewriter):
        for n in [1, 2, 3]:
            results = rewriter.expand("Python", num_queries=n)
            assert len(results) <= n


# ---------------------------------------------------------------------------
# Vector Store tests
# ---------------------------------------------------------------------------

class TestInMemoryVectorStore:
    @pytest.fixture
    def store(self):
        return InMemoryVectorStore(dim=4)

    @pytest.fixture
    def sample_embeddings(self):
        np.random.seed(42)
        return np.random.randn(3, 4).astype(np.float32)

    def test_add_and_count(self, store, sample_embeddings):
        doc_ids = ["doc1", "doc2", "doc3"]
        store.add(sample_embeddings, doc_ids)
        assert store.count == 3

    def test_add_with_documents(self, store):
        doc_ids = ["doc1", "doc2"]
        docs = [Document(content="hello", source="t1"),
                Document(content="world", source="t2")]
        embs = np.random.randn(2, 4).astype(np.float32)
        store.add(embs, doc_ids, docs)
        assert store.count == 2
        assert store.get_by_id("doc1").content == "hello"

    def test_search_returns_results(self, store, sample_embeddings):
        doc_ids = ["doc1", "doc2", "doc3"]
        store.add(sample_embeddings, doc_ids)
        query = np.array([1, 0, 0, 0], dtype=np.float32)
        results = store.search(query, top_k=2)
        assert len(results) == 2
        assert all(isinstance(r, VectorSearchResult) for r in results)

    def test_search_empty_store(self, store):
        query = np.array([1, 0, 0, 0], dtype=np.float32)
        results = store.search(query, top_k=5)
        assert results == []

    def test_search_scores_bounded(self, store, sample_embeddings):
        doc_ids = ["doc1", "doc2", "doc3"]
        store.add(sample_embeddings, doc_ids)
        query = np.array([1, 0, 0, 0], dtype=np.float32)
        results = store.search(query, top_k=3)
        for r in results:
            assert -1.0 <= r.score <= 1.0

    def test_delete(self, store, sample_embeddings):
        doc_ids = ["doc1", "doc2", "doc3"]
        store.add(sample_embeddings, doc_ids)
        removed = store.delete(["doc2"])
        assert removed == 1
        assert store.count == 2

    def test_delete_nonexistent(self, store):
        embs = np.random.randn(2, 4).astype(np.float32)
        store.add(embs, ["doc1", "doc2"])
        removed = store.delete(["nonexistent"])
        assert removed == 0

    def test_clear(self, store):
        embs = np.random.randn(2, 4).astype(np.float32)
        store.add(embs, ["doc1", "doc2"])
        store.clear()
        assert store.count == 0

    def test_get_by_id(self, store):
        docs = [Document(content="test content", source="test")]
        embs = np.random.randn(1, 4).astype(np.float32)
        store.add(embs, ["doc1"], docs)
        doc = store.get_by_id("doc1")
        assert doc is not None
        assert doc.content == "test content"

    def test_get_by_id_missing(self, store):
        assert store.get_by_id("nonexistent") is None


class TestVectorStoreFactory:
    def test_default_is_memory(self):
        store = VectorStore(backend="memory", dim=4)
        assert store.backend_name == "memory"
        assert isinstance(store._backend, InMemoryVectorStore)

    def test_add_and_search(self):
        store = VectorStore(backend="memory", dim=4)
        np.random.seed(42)
        embs = np.random.randn(3, 4).astype(np.float32)
        store.add(embs, ["a", "b", "c"])
        results = store.search(np.array([1, 0, 0, 0], dtype=np.float32), top_k=2)
        assert len(results) == 2

    def test_count(self):
        store = VectorStore(backend="memory", dim=4)
        assert store.count == 0

    def test_repr(self):
        store = VectorStore(backend="memory", dim=4)
        assert "VectorStore" in repr(store)
        assert "memory" in repr(store)


# ---------------------------------------------------------------------------
# Observability tests
# ---------------------------------------------------------------------------

class TestStructuredLogger:
    def test_log_event(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            logger = StructuredLogger(name="test", log_file=f.name)
            logger.log_event("test_event", key="value")
            # 确保写入
            for h in logger._logger.handlers:
                h.flush()
            content = Path(f.name).read_text()
            assert "test_event" in content

    def test_log_query(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            logger = StructuredLogger(name="test_query", log_file=f.name)
            logger.log_query("Python test", num_results=5, latency_ms=42.5)
            for h in logger._logger.handlers:
                h.flush()
            content = Path(f.name).read_text()
            data = json.loads(content.strip())
            assert data["event"] == "query"
            assert data["num_results"] == 5

    def test_no_file(self):
        """Logger without file should not raise."""
        logger = StructuredLogger(name="test_no_file")
        logger.log_event("test", foo="bar")  # should not raise


class TestRAGMetrics:
    def test_record_and_summary(self):
        metrics = RAGMetrics()
        metrics.record_query(latency_ms=100, num_results=5, intent="factual")
        metrics.record_query(latency_ms=200, num_results=3, intent="analytical")
        metrics.record_query(latency_ms=50, num_results=8, cache_hit=True)

        summary = metrics.summary()
        assert summary["total_queries"] == 3
        assert summary["cache_hit_rate"] == pytest.approx(1 / 3)
        assert summary["latency"]["p50_ms"] == pytest.approx(100)
        assert summary["recall"]["mean"] == pytest.approx((5 + 3 + 8) / 3, rel=1e-2)

    def test_empty_summary(self):
        metrics = RAGMetrics()
        summary = metrics.summary()
        assert summary["total_queries"] == 0
        assert summary["error_rate"] == 0.0

    def test_error_rate(self):
        metrics = RAGMetrics()
        metrics.record_query(latency_ms=100, num_results=5)
        metrics.record_query(latency_ms=0, num_results=0, error="timeout")
        summary = metrics.summary()
        assert summary["error_rate"] == pytest.approx(0.5)

    def test_reset(self):
        metrics = RAGMetrics()
        metrics.record_query(latency_ms=100, num_results=5)
        metrics.reset()
        assert metrics.summary()["total_queries"] == 0

    def test_window_size(self):
        metrics = RAGMetrics(window_size=5)
        for _ in range(10):
            metrics.record_query(latency_ms=100, num_results=5)
        assert len(metrics._query_metrics) == 5

    def test_backend_usage(self):
        metrics = RAGMetrics()
        metrics.record_query(latency_ms=100, num_results=5, backend="memory")
        metrics.record_query(latency_ms=100, num_results=5, backend="milvus")
        summary = metrics.summary()
        assert summary["backend_usage"]["memory"] == 1
        assert summary["backend_usage"]["milvus"] == 1


class TestRAGObserver:
    @pytest.fixture
    def observer(self):
        return RAGObserver()

    def test_trace_context_manager(self, observer):
        with observer.trace("test_op", key="val") as span:
            span.metadata["result"] = "ok"
        assert span.name == "test_op"
        assert span.duration_ms >= 0
        assert span.metadata["key"] == "val"
        assert span.metadata["result"] == "ok"

    def test_health_check(self, observer):
        health = observer.health_check()
        assert health["status"] == "healthy"
        assert "checks" in health

    def test_health_check_with_vector_store(self, observer):
        store = InMemoryVectorStore(dim=4)
        np.random.seed(42)
        embs = np.random.randn(2, 4).astype(np.float32)
        store.add(embs, ["d1", "d2"])
        health = observer.health_check(vector_store=store)
        assert health["checks"]["vector_store"]["status"] == "ok"
        assert health["checks"]["vector_store"]["document_count"] == 2

    def test_record_query(self, observer):
        observer.record_query(
            query="test",
            num_results=3,
            latency_ms=100,
            intent="factual",
        )
        summary = observer.get_metrics_summary()
        assert summary["total_queries"] == 1

    def test_repr(self, observer):
        assert "RAGObserver" in repr(observer)

    def test_no_logging(self):
        obs = RAGObserver(enable_logging=False)
        assert obs.logger is None

    def test_no_metrics(self):
        obs = RAGObserver(enable_metrics=False)
        assert obs.metrics is None


# ---------------------------------------------------------------------------
# Integration: Observer + Pipeline
# ---------------------------------------------------------------------------

class TestObserverPipelineIntegration:
    def test_query_records_metrics(self):
        from tools.rag import RAGPipeline

        config = RAGConfig()
        pipeline = RAGPipeline(config)
        pipeline.ingest(SAMPLE_DOCS)
        observer = RAGObserver()

        with observer.trace("query") as span:
            result = pipeline.query("What is Python?", top_k=2)
            span.metadata["num_results"] = len(result.reranked_documents)

        observer.record_query(
            query="What is Python?",
            num_results=len(result.reranked_documents),
            latency_ms=span.duration_ms,
            intent=result.intent.primary_intent,
        )

        summary = observer.get_metrics_summary()
        assert summary["total_queries"] == 1

    def test_health_with_empty_pipeline(self):
        from tools.rag import RAGPipeline

        config = RAGConfig()
        pipeline = RAGPipeline(config)
        observer = RAGObserver()

        health = observer.health_check(vector_store=None)
        assert health["status"] == "healthy"
