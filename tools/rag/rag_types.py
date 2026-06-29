# tools/rag/rag_types.py
"""
Shared types for the RAG system: Document, RAGConfig, and common dataclasses.

Merges: document.py + config.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

@dataclass
class Document:
    """A document unit in the RAG system.

    Attributes:
        content: Raw text content of the document.
        source: Origin identifier (file path, URL, etc.).
        metadata: Arbitrary metadata dict (tags, timestamps, …).
        score: Retrieval / ranking score (set by retrievers & rerankers).
        embedding: Optional dense vector embedding.
        doc_id: Unique identifier (auto-generated from source if omitted).
    """

    content: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    embedding: np.ndarray | None = field(default=None, repr=False)
    doc_id: str = ""

    def __post_init__(self) -> None:
        if not self.doc_id:
            import hashlib
            hash_input = f"{self.source}:{self.content[:200]}"
            self.doc_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    def __hash__(self) -> int:
        return hash(self.doc_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return self.doc_id == other.doc_id

    def __repr__(self) -> str:
        preview = self.content[:60] + "..." if len(self.content) > 60 else self.content
        return f"Document(id={self.doc_id!r}, source={self.source!r}, score={self.score:.4f}, content={preview!r})"


# ---------------------------------------------------------------------------
# RAGConfig
# ---------------------------------------------------------------------------

@dataclass
class RAGConfig:
    """Configuration for the RAG pipeline."""

    # Retriever settings
    bm25_top_k: int = 10
    vector_top_k: int = 10
    graph_top_k: int = 5
    fusion_top_k: int = 15

    # Reranker settings
    rerank_top_k: int = 10
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    cross_encoder_weight: float = 0.4
    llm_scorer_weight: float = 0.3
    vector_score_weight: float = 0.3

    # Embedding settings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # Intent settings
    intent_labels: list[str] = field(
        default_factory=lambda: [
            "factual",
            "analytical",
            "creative",
            "code_generation",
        ]
    )

    # GRPO / Feedback settings
    grpo_learning_rate: float = 1e-5
    grpo_epochs: int = 3
    grpo_batch_size: int = 8
    grpo_clip_ratio: float = 0.2
    grpo_temperature: float = 0.7
    reward_relevance_weight: float = 0.5
    reward_fluency_weight: float = 0.3
    reward_diversity_weight: float = 0.2

    # Pipeline settings
    enable_bm25: bool = True
    enable_vector: bool = True
    enable_graph: bool = True
    enable_reranker: bool = True
    enable_llm_scorer: bool = False

    # Graph settings
    graph_similarity_threshold: float = 0.3
    graph_max_depth: int = 3

    # Index paths (optional persistence)
    index_dir: str | None = None

    # LLM settings
    llm_provider: Literal["mock", "anthropic", "openai"] = "mock"
    llm_model: str = "claude-sonnet-4-6"
