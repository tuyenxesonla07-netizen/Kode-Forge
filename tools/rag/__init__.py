"""tools/rag/__init__ — Public API for the RAG package.

Dual-engine architecture:
    Search Engine (搜索引擎模式): BM25 + Vector + RRF + Rerank
    Cognitive Engine (认知引擎模式): Intent → Graph + Skill + Memory + GRPO

Usage:
    from tools.rag import RAGPipeline, SkillLearner, MemoryManager, UserModel

    # Search engine
    pipeline = RAGPipeline(config)
    pipeline.ingest(docs)
    result = pipeline.query("What is machine learning?")

    # Cognitive engine
    skills = SkillLearner(".skills")
    memory = MemoryManager(".rag_memory.json")
    user = UserModel()

    result = pipeline.query_with_cognitive(
        query="实现订单认证模块",
        skill_manager=skills,
        memory_manager=memory,
        user_model=user,
    )
"""

from tools.rag.rag_types import RAGConfig, Document
from tools.rag.feedback.rag_feedback import (
    FeedbackSample,
    FeedbackStore,
    FeedbackRanker,
    FullFeedbackRanker,
    FeedbackStepResult,
    FeedbackTrajectory,
    GRPOTrainer,
    GRPOStepResult,
    GRPOTrajectory,
    RealGRPOTrainer,
    StubPolicy,
    LLMPolicy,
    default_reward_function,
)
from tools.rag.feedback.skill_manager import LearnedSkill, SkillLearner
from tools.rag.cognitive.rag_cognitive import (
    IntentClassifier,
    IntentResult,
    UserModel,
    IntentRouter,
    RetrievalStrategy,
)
from tools.rag.cognitive.memory_manager import MemoryManager, MemoryItem
from tools.rag.cognitive.observability import RAGMetrics, RAGObserver, StructuredLogger
from tools.rag.pipeline import RAGPipeline, RAGResult
from tools.rag.search.query_rewriter import QueryRewriter, RewriteResult
from tools.rag.search.reranker import CombinedScorer, CrossEncoderReranker, LLMRelevanceScorer
from tools.rag.search.retriever import BM25Retriever, GraphRetriever, VectorRetriever
from tools.rag.search.vector_store import (
    ChromaVectorStore,
    InMemoryVectorStore,
    MilvusVectorStore,
    VectorStore,
    VectorSearchResult,
)

__all__ = [
    # Config
    "RAGConfig",
    # Document
    "Document",
    # Feedback
    "FeedbackSample",
    "FeedbackStore",
    # Feedback Ranker / GRPO
    "FeedbackRanker",
    "FullFeedbackRanker",
    "FeedbackStepResult",
    "FeedbackTrajectory",
    "GRPOTrainer",
    "GRPOStepResult",
    "GRPOTrajectory",
    "RealGRPOTrainer",
    "StubPolicy",
    "LLMPolicy",
    "default_reward_function",
    # Skills
    "LearnedSkill",
    "SkillLearner",
    # Intent
    "IntentClassifier",
    "IntentResult",
    # User Model
    "UserModel",
    "IntentRouter",
    "RetrievalStrategy",
    # Memory
    "MemoryManager",
    "MemoryItem",
    # Observability
    "RAGObserver",
    "RAGMetrics",
    "StructuredLogger",
    # Query Rewriting
    "QueryRewriter",
    "RewriteResult",
    # Vector Store
    "VectorStore",
    "VectorSearchResult",
    "InMemoryVectorStore",
    "MilvusVectorStore",
    "ChromaVectorStore",
    # Retrievers
    "BM25Retriever",
    "VectorRetriever",
    "GraphRetriever",
    # Rerankers
    "CrossEncoderReranker",
    "LLMRelevanceScorer",
    "CombinedScorer",
    # Pipeline
    "RAGPipeline",
    "RAGResult",
]
