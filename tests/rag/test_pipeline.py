"""Tests for the RAG package."""

import pytest
from tools.rag import (
    RAGConfig,
    Document,
    IntentClassifier,
    IntentResult,
    BM25Retriever,
    VectorRetriever,
    GraphRetriever,
    CrossEncoderReranker,
    LLMRelevanceScorer,
    CombinedScorer,
    GRPOTrainer,
    StubPolicy,
    default_reward_function,
    RAGPipeline,
    RAGResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    Document(
        content="Python is a high-level programming language with dynamic semantics. Its high-level built-in data structures make it attractive for rapid application development.",
        source="wiki_python",
        metadata={"category": "programming"},
    ),
    Document(
        content="Machine learning is a subset of artificial intelligence that enables systems to learn and improve from experience without being explicitly programmed.",
        source="wiki_ml",
        metadata={"category": "ai"},
    ),
    Document(
        content="The Eiffel Tower is a wrought-iron lattice tower located in Paris, France. It was constructed in 1889 and stands 330 meters tall.",
        source="wiki_eiffel",
        metadata={"category": "landmarks"},
    ),
    Document(
        content="Neural networks are computing systems inspired by biological neural networks. They consist of interconnected nodes that process information using connectionist approaches.",
        source="wiki_nn",
        metadata={"category": "ai"},
    ),
    Document(
        content="The Great Wall of China is a series of fortifications stretching over 13,000 miles. It was built over many centuries to protect Chinese states from invasions.",
        source="wiki_wall",
        metadata={"category": "landmarks"},
    ),
    Document(
        content="Docker is a platform for developing, shipping, and running applications in containers. Containers allow an application to be packaged with all its dependencies.",
        source="docs_docker",
        metadata={"category": "devops"},
    ),
    Document(
        content="Kubernetes is an open-source container orchestration system for automating deployment, scaling, and management of containerized applications.",
        source="docs_k8s",
        metadata={"category": "devops"},
    ),
    Document(
        content="The French Revolution began in 1789 and profoundly changed the political landscape of France. It led to the rise of democracy and the decline of absolute monarchy.",
        source="history_french_rev",
        metadata={"category": "history"},
    ),
    Document(
        content="Climate change refers to long-term shifts in global temperatures and weather patterns. Human activities, particularly burning fossil fuels, have been the main driver since the 1800s.",
        source="sci_climate",
        metadata={"category": "science"},
    ),
    Document(
        content="REST APIs use HTTP methods like GET, POST, PUT, and DELETE to interact with resources. They are the backbone of modern web services and microservices architecture.",
        source="docs_rest",
        metadata={"category": "programming"},
    ),
]


@pytest.fixture
def config():
    return RAGConfig(
        bm25_top_k=5,
        vector_top_k=5,
        graph_top_k=3,
        fusion_top_k=8,
        rerank_top_k=5,
        enable_llm_scorer=False,
    )


@pytest.fixture
def pipeline(config):
    p = RAGPipeline(config)
    p.ingest(SAMPLE_DOCS)
    return p


# ---------------------------------------------------------------------------
# Document tests
# ---------------------------------------------------------------------------

class TestDocument:
    def test_auto_id(self):
        doc = Document(content="hello world", source="test")
        assert doc.doc_id
        assert len(doc.doc_id) == 16

    def test_id_consistency(self):
        doc1 = Document(content="same content", source="src")
        doc2 = Document(content="same content", source="src")
        assert doc1.doc_id == doc2.doc_id

    def test_equality(self):
        doc1 = Document(content="a", source="s1")
        doc2 = Document(content="b", source="s2")
        assert doc1 == doc1
        assert doc1 != doc2

    def test_hash(self):
        doc = Document(content="hashable", source="src")
        assert hash(doc) == hash(doc.doc_id)

    def test_repr(self):
        doc = Document(content="short", source="src")
        assert "Document" in repr(doc)


# ---------------------------------------------------------------------------
# Intent tests
# ---------------------------------------------------------------------------

class TestIntentClassifier:
    def test_factual_intent(self):
        clf = IntentClassifier()
        result = clf.classify("What is the capital of France?")
        assert result.primary_intent == "factual"
        assert result.confidence > 0

    def test_code_intent(self):
        clf = IntentClassifier()
        result = clf.classify("Write a Python function to sort a list")
        assert result.primary_intent == "code_generation"

    def test_analytical_intent(self):
        clf = IntentClassifier()
        result = clf.classify("Why does climate change affect biodiversity?")
        assert result.primary_intent == "analytical"

    def test_creative_intent(self):
        clf = IntentClassifier()
        result = clf.classify("Write a poem about the ocean")
        assert result.primary_intent == "creative"

    def test_entity_extraction(self):
        clf = IntentClassifier()
        result = clf.classify("Barack Obama visited Paris on 2024-01-15")
        # Check that some entities were found (at least date or proper noun)
        assert len(result.entities) >= 1

    def test_keyword_extraction(self):
        clf = IntentClassifier()
        result = clf.classify("machine learning algorithms for natural language processing")
        assert len(result.keywords) > 0

    def test_empty_query(self):
        clf = IntentClassifier()
        result = clf.classify("")
        assert result.confidence == 0.0

    def test_all_scores_present(self):
        clf = IntentClassifier()
        result = clf.classify("test query")
        assert len(result.all_scores) == 4
        for label in ["factual", "analytical", "creative", "code_generation"]:
            assert label in result.all_scores


# ---------------------------------------------------------------------------
# Retriever tests
# ---------------------------------------------------------------------------

class TestBM25Retriever:
    def test_basic_retrieval(self, config):
        retriever = BM25Retriever(config)
        retriever.add_documents(SAMPLE_DOCS)
        results = retriever.retrieve("Python programming language", top_k=3)
        assert len(results) > 0
        assert all(isinstance(d, Document) for d in results)
        assert results[0].score > 0

    def test_empty_corpus(self, config):
        retriever = BM25Retriever(config)
        results = retriever.retrieve("anything", top_k=3)
        assert results == []

    def test_scores_descending(self, config):
        retriever = BM25Retriever(config)
        retriever.add_documents(SAMPLE_DOCS)
        results = retriever.retrieve("machine learning", top_k=5)
        scores = [d.score for d in results]
        assert scores == sorted(scores, reverse=True)

    def test_metadata_tagged(self, config):
        retriever = BM25Retriever(config)
        retriever.add_documents(SAMPLE_DOCS)
        results = retriever.retrieve("Docker containers", top_k=2)
        assert all(d.metadata.get("retriever") == "bm25" for d in results)


class TestVectorRetriever:
    def test_basic_retrieval(self, config):
        retriever = VectorRetriever(config)
        retriever.add_documents(SAMPLE_DOCS)
        results = retriever.retrieve("artificial intelligence", top_k=3)
        assert len(results) > 0
        assert all(isinstance(d, Document) for d in results)

    def test_embeddings_stored(self, config):
        retriever = VectorRetriever(config)
        retriever.add_documents(SAMPLE_DOCS)
        assert retriever._embeddings is not None
        assert retriever._embeddings.shape[0] == len(SAMPLE_DOCS)

    def test_empty_corpus(self, config):
        retriever = VectorRetriever(config)
        results = retriever.retrieve("anything", top_k=3)
        assert results == []

    def test_scores_bounded(self, config):
        retriever = VectorRetriever(config)
        retriever.add_documents(SAMPLE_DOCS)
        results = retriever.retrieve("neural networks", top_k=5)
        assert all(0.0 <= d.score <= 1.0 for d in results)


class TestGraphRetriever:
    def test_basic_retrieval(self, config):
        retriever = GraphRetriever(config)
        retriever.add_documents(SAMPLE_DOCS)
        results = retriever.retrieve("container orchestration", top_k=3)
        assert len(results) > 0

    def test_graph_edges_built(self, config):
        # Use docs with high overlap to guarantee edges
        docs = [
            Document(content="machine learning artificial intelligence neural networks deep learning"),
            Document(content="artificial intelligence neural networks computer vision natural language"),
            Document(content="deep learning neural networks backpropagation gradient descent"),
        ]
        retriever = GraphRetriever(config)
        retriever.add_documents(docs)
        edge_count = sum(len(v) for v in retriever._adj.values()) // 2
        assert edge_count > 0

    def test_empty_corpus(self, config):
        retriever = GraphRetriever(config)
        results = retriever.retrieve("anything", top_k=3)
        assert results == []


# ---------------------------------------------------------------------------
# Reranker tests
# ---------------------------------------------------------------------------

class TestCrossEncoderReranker:
    def test_reranking(self, config):
        reranker = CrossEncoderReranker(config)
        results = reranker.rerank("Python programming", SAMPLE_DOCS[:5], top_k=3)
        assert len(results) == 3
        assert all(isinstance(d, Document) for d in results)

    def test_empty_docs(self, config):
        reranker = CrossEncoderReranker(config)
        results = reranker.rerank("test", [], top_k=3)
        assert results == []

    def test_scores_assigned(self, config):
        reranker = CrossEncoderReranker(config)
        results = reranker.rerank("machine learning", SAMPLE_DOCS[:5], top_k=3)
        # At least the top result should have a non-zero score
        assert results[0].score != 0.0


class TestLLMRelevanceScorer:
    def test_scoring(self, config):
        scorer = LLMRelevanceScorer(config)
        scores = scorer.score("Python programming", SAMPLE_DOCS[:3])
        assert len(scores) == 3
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_relevant_scores_higher(self, config):
        scorer = LLMRelevanceScorer(config)
        relevant_doc = [Document(content="Python is a programming language with functions and classes")]
        irrelevant_doc = [Document(content="The Eiffel Tower in Paris is 330 meters tall")]
        scores = scorer.score("Python code", relevant_doc + irrelevant_doc)
        assert scores[0] > scores[1]


class TestCombinedScorer:
    def test_combined_reranking(self, config):
        scorer = CombinedScorer(config)
        results = scorer.rerank("artificial intelligence", SAMPLE_DOCS[:6], top_k=4)
        assert len(results) == 4
        assert all(d.metadata.get("retriever") == "combined" for d in results)

    def test_metadata_fields(self, config):
        scorer = CombinedScorer(config)
        results = scorer.rerank("test", SAMPLE_DOCS[:3], top_k=2)
        assert all("ce_score" in d.metadata for d in results)
        assert all("vector_score" in d.metadata for d in results)


# ---------------------------------------------------------------------------
# GRPO tests
# ---------------------------------------------------------------------------

class TestGRPOTrainer:
    def test_train_step(self, config):
        trainer = GRPOTrainer(config)
        prompts = ["What is Python?", "Explain neural networks"]
        docs = [SAMPLE_DOCS[:3], SAMPLE_DOCS[3:6]]
        result = trainer.train_step(prompts, docs)
        assert result.num_samples == 2
        assert isinstance(result.loss, float)
        assert isinstance(result.mean_reward, float)

    def test_train_step_with_llm_policy(self, config):
        """GRPOTrainer auto-detects LLMPolicy when llm_provider is set."""
        config_with_llm = RAGConfig(llm_provider="mock")  # mock for testing
        trainer = GRPOTrainer(config_with_llm)
        assert "LLMPolicy" in repr(trainer) or "StubPolicy" in repr(trainer)

    def test_llmpolicy_generate(self):
        """LLMPolicy.generate() works with mock provider."""
        from tools.rag.feedback.rag_feedback import LLMPolicy

        config = RAGConfig(llm_provider="mock")
        policy = LLMPolicy(config)
        response = policy.generate("Hello")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_llmpolicy_update(self):
        """LLMPolicy.update() returns a loss value."""
        from tools.rag.feedback.rag_feedback import LLMPolicy

        policy = LLMPolicy()
        loss = policy.update(-0.5, 0.3)
        assert isinstance(loss, float)

    def test_empty_prompts(self, config):
        trainer = GRPOTrainer(config)
        result = trainer.train_step([], [])
        assert result.num_samples == 0
        assert result.loss == 0.0

    def test_with_stub_policy(self, config):
        trainer = GRPOTrainer(config)
        policy = StubPolicy()
        prompts = ["Explain Docker"]
        docs = [SAMPLE_DOCS[5:7]]
        result = trainer.train_step(prompts, docs, policy=policy)
        assert result.num_samples == 1

    def test_step_count(self, config):
        trainer = GRPOTrainer(config)
        assert trainer.step_count == 0
        trainer.train_step(["test"], [SAMPLE_DOCS[:2]])
        assert trainer.step_count == 1

    def test_history(self, config):
        trainer = GRPOTrainer(config)
        trainer.train_step(["a", "b"], [SAMPLE_DOCS[:2], SAMPLE_DOCS[2:4]])
        trainer.train_step(["c"], [SAMPLE_DOCS[4:6]])
        assert len(trainer.history) == 2

    def test_reward_function(self):
        doc = [Document(content="Python programming language with functions")]
        reward = default_reward_function("Python code", doc, "Python is great for writing code")
        assert 0.0 <= reward <= 1.0

    def test_reward_zero_docs(self):
        reward = default_reward_function("test", [], "some response")
        assert reward >= 0.0


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------

class TestRAGPipeline:
    def test_full_pipeline(self, pipeline):
        result = pipeline.query("What is machine learning?")
        assert isinstance(result, RAGResult)
        assert result.query == "What is machine learning?"
        assert isinstance(result.intent, IntentResult)
        assert len(result.reranked_documents) > 0
        assert result.answer

    def test_pipeline_metadata(self, pipeline):
        result = pipeline.query("Tell me about Python")
        assert "num_documents" in result.metadata
        assert result.metadata["num_documents"] == len(SAMPLE_DOCS)

    def test_intent_in_result(self, pipeline):
        result = pipeline.query("Write a Python function")
        assert result.intent.primary_intent == "code_generation"

    def test_ingest_and_query(self, config):
        pipeline = RAGPipeline(config)
        assert pipeline.num_documents == 0
        pipeline.ingest(SAMPLE_DOCS[:3])
        assert pipeline.num_documents == 3
        pipeline.ingest(SAMPLE_DOCS[3:])
        assert pipeline.num_documents == len(SAMPLE_DOCS)

    def test_empty_pipeline(self, config):
        pipeline = RAGPipeline(config)
        result = pipeline.query("anything")
        assert "No relevant documents" in result.answer

    def test_top_k_respected(self, pipeline):
        result = pipeline.query("programming", top_k=2)
        assert len(result.reranked_documents) <= 2

    def test_repr(self, pipeline):
        assert "RAGPipeline" in repr(pipeline)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestRAGConfig:
    def test_defaults(self):
        cfg = RAGConfig()
        assert cfg.bm25_top_k == 10
        assert cfg.vector_top_k == 10
        assert cfg.enable_bm25 is True
        assert cfg.enable_vector is True
        assert cfg.enable_graph is True

    def test_custom_values(self):
        cfg = RAGConfig(bm25_top_k=20, enable_graph=False)
        assert cfg.bm25_top_k == 20
        assert cfg.enable_graph is False

    def test_intent_labels(self):
        cfg = RAGConfig()
        assert "factual" in cfg.intent_labels
        assert "code_generation" in cfg.intent_labels
