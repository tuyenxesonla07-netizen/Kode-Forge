"""Reranker: cross-encoder reranking, LLM relevance scoring, and combined scoring."""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np

from tools.rag.rag_types import RAGConfig, Document


class CrossEncoderReranker:
    """Cross-encoder reranker that scores (query, document) pairs.

    Uses *sentence-transformers* cross-encoder when available; falls back
    to the dot-product of embeddings.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self._model: Any | None = None
        self._using_fallback = False

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.config.cross_encoder_model)
        except ImportError:
            warnings.warn(
                "sentence-transformers not installed; cross-encoder reranker "
                "will use embedding dot-product fallback.",
                stacklevel=2,
            )
            self._using_fallback = True

    def rerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int | None = None,
    ) -> list[Document]:
        """Score documents against the query and return the top-k."""
        k = top_k or self.config.rerank_top_k
        if not documents:
            return []

        self._load_model()

        if self._using_fallback or self._model is None:
            scores = self._fallback_score(query, documents)
        else:
            pairs = [(query, doc.content) for doc in documents]
            raw_scores = self._model.predict(pairs)
            scores = np.array(raw_scores, dtype=float)

        # Attach scores and sort
        ranked = _attach_scores(documents, scores, "cross_encoder")
        ranked.sort(key=lambda d: d.score, reverse=True)
        return ranked[:k]

    def _fallback_score(self, query: str, documents: list[Document]) -> np.ndarray:
        """Embedding dot-product fallback scoring."""
        query_text = query.lower()
        scores = np.zeros(len(documents))
        for i, doc in enumerate(documents):
            score = _jaccard_score(query_text.lower().split(), doc.content.lower().split())
            scores[i] = score
        return scores

    def __repr__(self) -> str:
        status = "fallback" if self._using_fallback else (self.config.cross_encoder_model if self._model else "unloaded")
        return f"CrossEncoderReranker(model={status})"


class LLMRelevanceScorer:
    """LLM-based relevance scorer.

    Sends (query, document) pairs to an LLM for scoring in [0, 1].
    Works with a mock provider out-of-box (deterministic heuristic).
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()

    def score(
        self,
        query: str,
        documents: list[Document],
    ) -> list[float]:
        """Return relevance scores in [0, 1] for each document."""
        scores: list[float] = []
        for doc in documents:
            score = self._score_pair(query, doc.content)
            scores.append(score)
        return scores

    def _score_pair(self, query: str, content: str) -> float:
        """Score a single query-document pair."""
        if self.config.llm_provider == "mock":
            return _mock_llm_score(query, content)

        # Use the project's LLM provider abstraction
        try:
            from tools.llm import create_llm_provider

            provider = create_llm_provider(backend=self.config.llm_provider)

            prompt = (
                f"Rate the relevance of this document to the query on a "
                f"scale of 0.0 to 1.0. Return ONLY the number.\n\n"
                f"Query: {query}\n"
                f"Document: {content[:500]}\n"
                f"Score:"
            )

            response = provider.complete(prompt, max_tokens=10, temperature=0.1)

            if response.success:
                text = response.content.strip()
                # Extract number from response
                import re

                match = re.search(r"(\d+\.?\d*)", text)
                if match:
                    score = float(match.group(1))
                    return max(0.0, min(1.0, score))

            # Fallback if parsing fails
            warnings.warn(
                f"LLM scorer returned unparseable response: {response.content!r}",
                stacklevel=2,
            )
            return _mock_llm_score(query, content)

        except ImportError:
            warnings.warn(
                "LLM provider not available; using mock fallback",
                stacklevel=2,
            )
            return _mock_llm_score(query, content)
        except Exception as exc:
            warnings.warn(f"LLM scorer failed ({exc}); using mock fallback", stacklevel=2)
            return _mock_llm_score(query, content)


class CombinedScorer:
    """Fuses cross-encoder, LLM, and vector scores into a single ranking."""

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self.cross_encoder = CrossEncoderReranker(config)
        self.llm_scorer = LLMRelevanceScorer(config) if config.enable_llm_scorer else None

    def rerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int | None = None,
    ) -> list[Document]:
        """Rerank documents using combined scores."""
        k = top_k or self.config.rerank_top_k
        if not documents:
            return []

        # 1) Cross-encoder scores
        ce_ranked = self.cross_encoder.rerank(query, documents, top_k=len(documents))
        ce_scores = {d.doc_id: d.score for d in ce_ranked}

        # 2) LLM scores (if enabled)
        if self.llm_scorer is not None:
            llm_scores_list = self.llm_scorer.score(query, documents)
            llm_scores = {d.doc_id: s for d, s in zip(documents, llm_scores_list)}
        else:
            llm_scores = {d.doc_id: 0.0 for d in documents}

        # 3) Vector scores (retriever scores already on documents)
        vec_scores = {d.doc_id: d.score for d in documents}

        # 4) Normalise each score dimension to [0, 1]
        ce_norm = _normalize(ce_scores)
        llm_norm = _normalize(llm_scores)
        vec_norm = _normalize(vec_scores)

        # 5) Weighted combination
        w = self.config
        combined_scores: dict[str, float] = {}
        for doc in documents:
            cid = doc.doc_id
            combined = (
                w.cross_encoder_weight * ce_norm.get(cid, 0.0)
                + w.llm_scorer_weight * llm_norm.get(cid, 0.0)
                + w.vector_score_weight * vec_norm.get(cid, 0.0)
            )
            combined_scores[cid] = combined

        # Build result list
        results: list[Document] = []
        for doc in documents:
            doc_copy = Document(
                content=doc.content,
                source=doc.source,
                metadata={
                    **doc.metadata,
                    "retriever": "combined",
                    "ce_score": ce_scores.get(doc.doc_id, 0.0),
                    "llm_score": llm_scores.get(doc.doc_id, 0.0),
                    "vector_score": vec_scores.get(doc.doc_id, 0.0),
                },
                score=combined_scores[doc.doc_id],
                embedding=doc.embedding,
                doc_id=doc.doc_id,
            )
            results.append(doc_copy)

        results.sort(key=lambda d: d.score, reverse=True)
        return results[:k]

    def __repr__(self) -> str:
        return f"CombinedScorer(llm_enabled={self.llm_scorer is not None})"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _jaccard_score(tokens_a: list[str], tokens_b: list[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    return len(set_a & set_b) / len(set_a | set_b)


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    """Min-max normalise scores to [0, 1]."""
    if not scores:
        return {}
    values = list(scores.values())
    min_v = min(values)
    max_v = max(values)
    range_v = max_v - min_v
    if range_v == 0:
        return {k: 0.5 for k in scores}
    return {k: (v - min_v) / range_v for k, v in scores.items()}


def _attach_scores(
    documents: list[Document],
    scores: np.ndarray,
    retriever_label: str,
) -> list[Document]:
    """Return copies of *documents* with *scores* attached."""
    result: list[Document] = []
    for i, doc in enumerate(documents):
        doc_copy = Document(
            content=doc.content,
            source=doc.source,
            metadata={**doc.metadata, "retriever": retriever_label},
            score=float(scores[i]),
            embedding=doc.embedding,
            doc_id=doc.doc_id,
        )
        result.append(doc_copy)
    return result


def _mock_llm_score(query: str, content: str) -> float:
    """Deterministic heuristic mimicking LLM relevance scoring."""
    query_tokens = set(query.lower().split())
    content_tokens = set(content.lower().split())
    if not query_tokens:
        return 0.5
    overlap = len(query_tokens & content_tokens)
    base = overlap / len(query_tokens)
    # Bonus for longer content (more context)
    length_bonus = min(0.2, len(content_tokens) / 500)
    return min(1.0, base + length_bonus)
