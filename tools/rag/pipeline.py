"""RAG Pipeline: dual-engine (Search + Cognitive) pipeline.

Search Engine:  BM25 + Vector + Graph → RRF → Rerank → Answer
Cognitive Engine: Intent → Graph + Skill + Memory + GRPO → Answer

The query() method uses the search engine (all retrievers).
The query_cognitive() method uses the cognitive engine with skill matching,
memory recall, and user model personalization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence


from tools.rag.rag_types import RAGConfig, Document
from tools.rag.cognitive.rag_cognitive import IntentClassifier, IntentResult, IntentRouter, RetrievalStrategy, UserModel
from tools.rag.cognitive.memory_manager import MemoryManager
from tools.rag.search.reranker import CombinedScorer
from tools.rag.search.retriever import (
    BM25Retriever,
    GraphRetriever,
    VectorRetriever,
)
from tools.rag.feedback.skill_manager import SkillLearner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclass
class RAGResult:
    """Full result of a RAG pipeline query."""

    query: str
    intent: IntentResult
    retrieved_documents: list[Document]
    reranked_documents: list[Document]
    fused_documents: list[Document]
    answer: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fusion helper
# ---------------------------------------------------------------------------

def _reciprocal_rank_fusion(
    ranked_lists: list[list[Document]],
    k: int = 60,
) -> list[Document]:
    """Reciprocal Rank Fusion (RRF) over multiple ranked document lists.

    Args:
        ranked_lists: Lists of documents, each sorted by relevance (best first).
        k: RRF constant (higher = more weight to top-ranked items).

    Returns:
        Fused list of documents sorted by descending RRF score.
    """
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked):
            doc_id = doc.doc_id
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            doc_map[doc_id] = doc

    # Sort by RRF score
    sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)  # type: ignore[arg-type]
    results: list[Document] = []
    for doc_id in sorted_ids:
        doc = doc_map[doc_id]
        doc_copy = Document(
            content=doc.content,
            source=doc.source,
            metadata={**doc.metadata, "rrf_score": rrf_scores[doc_id]},
            score=rrf_scores[doc_id],
            embedding=doc.embedding,
            doc_id=doc.doc_id,
        )
        results.append(doc_copy)
    return results


# ---------------------------------------------------------------------------
# Simple answer generator (no external API)
# ---------------------------------------------------------------------------

def _generate_cognitive_answer(
    query: str,
    documents: list[Document],
    intent: IntentResult,
    memory_context: list[str] | None = None,
    skill_context: list[str] | None = None,
    strategy: RetrievalStrategy | None = None,
) -> str:
    """Generate an answer enriched with memory and skill context."""
    parts: list[str] = []

    # Header
    mode_label = strategy.mode.upper() if strategy else "COGNITIVE"
    parts.append(f"[{mode_label} | intent={intent.primary_intent} | conf={intent.confidence:.2f}]")
    parts.append("")

    # Memory context
    if memory_context:
        parts.append("## Memory Context")
        for i, mem in enumerate(memory_context, 1):
            parts.append(f"  {i}. {mem}")
        parts.append("")

    # Skill context
    if skill_context:
        parts.append("## Matched Skill")
        for sc in skill_context:
            parts.append(f"  {sc}")
        parts.append("")

    # Main content
    parts.append(f"## Query: {query}")
    parts.append("")

    if documents:
        parts.append("## Retrieved Documents")
        for i, doc in enumerate(documents[:3], 1):
            text = doc.content.strip()
            snippet = text[:150] + ("..." if len(text) > 150 else "")
            score_str = f" (score={doc.score:.4f})" if doc.score else ""
            parts.append(f"  {i}. [{doc.source}]{score_str} {snippet}")
        parts.append("")

    # Compose answer from top document
    if documents:
        answer_text = documents[0].content.strip()[:200]
        parts.append(f"**Answer:** {answer_text}")
    else:
        parts.append("No relevant documents found.")

    return "\n".join(parts)


# Legacy alias for backward compatibility
def _generate_answer(query: str, documents: list[Document], intent: IntentResult) -> str:
    """Generate a simple extractive answer from top documents."""
    if not documents:
        return "No relevant documents found to answer the query."

    snippets: list[str] = []
    for doc in documents[:3]:
        text = doc.content.strip()
        period_idx = text.find(".")
        if 0 < period_idx <= 150:
            snippet = text[: period_idx + 1]
        else:
            snippet = text[:150] + ("..." if len(text) > 150 else "")
        snippets.append(snippet)

    intent_label = intent.primary_intent
    header = f"[{intent_label.upper()} | confidence={intent.confidence:.2f}]"

    parts = [header, ""]
    parts.append(f"Query: {query}")
    parts.append("")
    parts.append("Relevant passages:")
    for i, snippet in enumerate(snippets, 1):
        parts.append(f"  {i}. {snippet}")
    parts.append("")
    answer_text = snippets[0] if snippets else ""
    parts.append(f"Answer: {answer_text}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# RAG Pipeline
# ---------------------------------------------------------------------------

class RAGPipeline:
    """Full RAG pipeline: ingest → query.

    Flow:
        1. Ingest documents (index in all retrievers).
        2. Query:
           a. Intent classification
           b. Multi-path retrieval (BM25, Vector, Graph)
           c. Reciprocal Rank Fusion
           d. Reranking (cross-encoder + optional LLM scorer)
           e. Answer generation
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self._bm25 = BM25Retriever(self.config)
        self._vector = VectorRetriever(self.config)
        self._graph = GraphRetriever(self.config)
        self._reranker = CombinedScorer(self.config)
        self._intent = IntentClassifier(self.config)
        self._documents: list[Document] = []
        self._ingested = False

    # ---- ingest ------------------------------------------------------------

    def ingest(self, documents: Sequence[Document]) -> None:
        """Index *documents* into all retrieval backends."""
        doc_list = list(documents)
        self._documents.extend(doc_list)

        if self.config.enable_bm25:
            self._bm25.add_documents(doc_list)
        if self.config.enable_vector:
            self._vector.add_documents(doc_list)
        if self.config.enable_graph:
            self._graph.add_documents(doc_list)

        self._ingested = True

    # ---- query -------------------------------------------------------------

    def query(self, query: str, top_k: int | None = None) -> RAGResult:
        """Execute the full RAG pipeline for *query*.

        Steps:
            1. Intent classification
            2. Multi-path retrieval
            3. Fusion (RRF)
            4. Reranking
            5. Answer generation
        """
        # 1. Intent
        intent = self._intent.classify(query)

        # 2-4. Multi-path retrieval + Fusion + Reranking (shared)
        reranked, ranked_lists = self._retrieve_and_fusion(query, top_k=top_k)

        # 5. Answer generation
        answer = _generate_answer(query, reranked, intent)

        return RAGResult(
            query=query,
            intent=intent,
            retrieved_documents=[d for lst in ranked_lists for d in lst],
            reranked_documents=reranked,
            fused_documents=reranked,  # post-fusion+rerank represents the final fused set
            answer=answer,
            metadata={
                "num_documents": len(self._documents),
                "num_retrieved": sum(len(lst) for lst in ranked_lists),
                "num_reranked": len(reranked),
            },
        )

    # ---- cognitive query --------------------------------------------------

    def query_cognitive(
        self,
        query: str,
        top_k: int | None = None,
        skill_manager: SkillLearner | None = None,
        memory_manager: MemoryManager | None = None,
        user_model: UserModel | None = None,
        extract_skill: bool = False,
        trajectory: list[dict[str, Any]] | None = None,
    ) -> RAGResult:
        """Execute the cognitive engine for complex queries.

        Steps:
            1. Intent classification
            2. IntentRouter → determine retrieval strategy
            3. Memory pre-turn recall
            4. Skill matching
            5. Selective retrieval (based on strategy)
            6. Fusion + Reranking
            7. Answer generation
            8. Post-turn: memory capture + optional skill extraction

        Args:
            query: The user query.
            top_k: Maximum results to return.
            skill_manager: Optional SkillLearner for skill matching.
            memory_manager: Optional MemoryManager for cross-session memory.
            user_model: Optional UserModel for personalization.
            extract_skill: If True, extract a skill from the trajectory.
            trajectory: Execution trajectory for skill extraction.

        Returns:
            RAGResult with cognitive engine metadata.
        """
        # 1. Intent
        intent = self._intent.classify(query)

        # 2. Route
        router = IntentRouter(self.config)
        strategy = router.route(query, intent, user_model)

        # 3. Memory recall
        memory_context: list[str] = []
        if memory_manager:
            memories = memory_manager.pre_turn(query, limit=3)
            memory_context = [m.content for m in memories]

        # 4. Skill matching
        skill_context: list[str] = []
        matched_skill = None
        if skill_manager:
            matched_skill = skill_manager.match_skill(query, intent.primary_intent)
            if matched_skill:
                skill_context.append(f"[Skill: {matched_skill.name}]\n{matched_skill.content}")

        # 5. Selective retrieval based on strategy (shared helper)
        reranked, ranked_lists = self._retrieve_and_fusion(
            query,
            use_bm25=strategy.use_bm25,
            use_vector=strategy.use_vector,
            use_graph=strategy.use_graph,
            top_k=top_k,
            default_top_k=strategy.rerank_top_k,
        )

        # 7. Build enriched answer
        answer = _generate_cognitive_answer(
            query, reranked, intent,
            memory_context=memory_context,
            skill_context=skill_context,
            strategy=strategy,
        )

        # 8. Post-turn: memory + skill
        if memory_manager:
            memory_manager.post_turn(
                query=query,
                response=answer,
                metadata={
                    "source": "cognitive_engine",
                    "intent": intent.primary_intent,
                    "mode": strategy.mode,
                },
            )

        if extract_skill and skill_manager and trajectory:
            skill_manager.extract_skill(query, trajectory, intent.primary_intent)

        if matched_skill and skill_manager:
            skill_manager.record_usage(matched_skill, success=True)

        return RAGResult(
            query=query,
            intent=intent,
            retrieved_documents=[d for lst in ranked_lists for d in lst],
            reranked_documents=reranked,
            fused_documents=reranked,
            answer=answer,
            metadata={
                "num_documents": len(self._documents),
                "num_retrieved": sum(len(lst) for lst in ranked_lists),
                "num_fused": len(reranked),
                "num_reranked": len(reranked),
                "mode": strategy.mode,
                "strategy": strategy.to_dict(),
                "memory_hits": len(memory_context),
                "skill_matched": matched_skill.name if matched_skill else None,
            },
        )

    def _retrieve_and_fusion(
        self,
        query: str,
        use_bm25: bool = True,
        use_vector: bool = True,
        use_graph: bool = True,
        top_k: int | None = None,
        default_top_k: int | None = None,
    ) -> tuple[list[Document], list[list[Document]]]:
        """共享的检索+融合逻辑，供 query() 和 query_cognitive() 复用。

        Returns:
            (reranked_or_fused documents, raw ranked_lists)
        """
        ranked_lists: list[list[Document]] = []

        if use_bm25 and self.config.enable_bm25:
            bm25_results = self._bm25.retrieve(query, top_k=self.config.bm25_top_k)
            if bm25_results:
                ranked_lists.append(bm25_results)

        if use_vector and self.config.enable_vector:
            vector_results = self._vector.retrieve(query, top_k=self.config.vector_top_k)
            if vector_results:
                ranked_lists.append(vector_results)

        if use_graph and self.config.enable_graph:
            graph_results = self._graph.retrieve(query, top_k=self.config.graph_top_k)
            if graph_results:
                ranked_lists.append(graph_results)

        fused = _reciprocal_rank_fusion(ranked_lists)
        fused = fused[: self.config.fusion_top_k]

        if self.config.enable_reranker and fused:
            reranked = self._reranker.rerank(query, fused, top_k=top_k)
        else:
            k = top_k if top_k is not None else default_top_k
            reranked = fused[:k] if k else fused

        return reranked, ranked_lists

    # ---- properties -------------------------------------------------------

    @property
    def documents(self) -> list[Document]:
        return list(self._documents)

    @property
    def num_documents(self) -> int:
        return len(self._documents)

    def __repr__(self) -> str:
        return (
            f"RAGPipeline(docs={len(self._documents)}, "
            f"bm25={self.config.enable_bm25}, "
            f"vector={self.config.enable_vector}, "
            f"graph={self.config.enable_graph})"
        )
