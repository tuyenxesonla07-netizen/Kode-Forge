"""Multi-path retrievers: BM25, Vector, and Graph traversal."""

from __future__ import annotations

import math
import warnings
from collections import defaultdict
from typing import Any, Protocol

import numpy as np

from tools.rag.rag_types import RAGConfig, Document


# ---------------------------------------------------------------------------
# Retriever protocol
# ---------------------------------------------------------------------------

class Retriever(Protocol):
    """Interface every retriever must satisfy."""

    def retrieve(self, query: str, top_k: int) -> list[Document]: ...


# ---------------------------------------------------------------------------
# BM25 Retriever
# ---------------------------------------------------------------------------

class BM25Retriever:
    """BM25 retriever backed by *jieba* (Chinese-friendly) tokenization and the
    *rank-bm25* library.  Falls back to a simple TF-IDF implementation when
    *rank-bm25* is not installed.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self._corpus: list[Document] = []
        self._tokenized: list[list[str]] = []
        self._bm25: Any | None = None
        self._fitted = False

    # -- indexing -----------------------------------------------------------

    def add_documents(self, documents: list[Document]) -> None:
        """Add documents to the BM25 index."""
        self._corpus.extend(documents)
        for doc in self._corpus:
            self._tokenized.append(_tokenize_bm25(doc.content))
        self._build_index()

    def _build_index(self) -> None:
        """Build (or rebuild) the BM25 index."""
        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi(self._tokenized)
        except ImportError:
            self._bm25 = None  # fallback to manual BM25
        self._fitted = True

    # -- retrieval ----------------------------------------------------------

    def retrieve(self, query: str, top_k: int | None = None) -> list[Document]:
        """Return top-k documents using BM25 scoring."""
        k = top_k or self.config.bm25_top_k
        if not self._corpus:
            return []

        query_tokens = _tokenize_bm25(query)

        if self._bm25 is not None:
            scores = self._bm25.get_scores(query_tokens).astype(float)
        else:
            scores = np.array([_manual_bm25_score(query_tokens, doc_tokens)
                               for doc_tokens in self._tokenized])

        top_indices = np.argsort(scores)[::-1][:k]
        results: list[Document] = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            doc = self._corpus[int(idx)]
            doc_copy = Document(
                content=doc.content,
                source=doc.source,
                metadata={**doc.metadata, "retriever": "bm25"},
                score=float(scores[idx]),
                embedding=doc.embedding,
                doc_id=doc.doc_id,
            )
            results.append(doc_copy)
        return results

    def __repr__(self) -> str:
        return f"BM25Retriever(docs={len(self._corpus)}, fitted={self._fitted})"


# ---------------------------------------------------------------------------
# Vector Retriever
# ---------------------------------------------------------------------------

class VectorRetriever:
    """Dense vector retriever using *sentence-transformers* for embedding
    and cosine similarity for scoring.  Falls back to a simple TF-based
    bag-of-words embedding when the library is not installed.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self._corpus: list[Document] = []
        self._embeddings: np.ndarray | None = None  # shape (n, dim)
        self._model: Any | None = None
        self._fitted = False

    # -- indexing -----------------------------------------------------------

    def add_documents(self, documents: list[Document]) -> None:
        """Embed and index documents."""
        self._corpus.extend(documents)
        # Embed any that don't already have embeddings
        to_embed: list[Document] = []
        indices: list[int] = []
        for i, doc in enumerate(self._corpus):
            if doc.embedding is None:
                to_embed.append(doc)
                indices.append(i)

        if to_embed:
            new_embs = np.array([self._embed(d.content) for d in to_embed])
            for j, idx in enumerate(indices):
                self._corpus[idx].embedding = new_embs[j]

        self._rebuild_matrix()
        self._fitted = True

    def _rebuild_matrix(self) -> None:
        if not self._corpus:
            return
        embs = [d.embedding for d in self._corpus if d.embedding is not None]
        if embs:
            self._embeddings = np.stack(embs)
        else:
            self._embeddings = None

    # -- embedding -----------------------------------------------------------

    def _embed(self, text: str) -> np.ndarray:
        """Embed a single text into a dense vector."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.config.embedding_model)
            except ImportError:
                self._model = "fallback"

        if self._model == "fallback":
            return _fallback_embed(text, dim=self.config.embedding_dim)

        emb = self._model.encode([text], show_progress_bar=False)[0]
        return emb.astype(np.float32)

    # -- retrieval ----------------------------------------------------------

    def retrieve(self, query: str, top_k: int | None = None) -> list[Document]:
        """Return top-k documents by cosine similarity."""
        k = top_k or self.config.vector_top_k
        if not self._corpus or self._embeddings is None:
            return []

        query_emb = self._embed(query)
        scores = _cosine_similarities(query_emb, self._embeddings)  # (n,)

        top_indices = np.argsort(scores)[::-1][:k]
        results: list[Document] = []
        for idx in top_indices:
            idx = int(idx)
            doc = self._corpus[idx]
            doc_copy = Document(
                content=doc.content,
                source=doc.source,
                metadata={**doc.metadata, "retriever": "vector"},
                score=float(scores[idx]),
                embedding=doc.embedding,
                doc_id=doc.doc_id,
            )
            results.append(doc_copy)
        return results

    def __repr__(self) -> str:
        return f"VectorRetriever(docs={len(self._corpus)}, fitted={self._fitted})"


# ---------------------------------------------------------------------------
# Graph Retriever
# ---------------------------------------------------------------------------

class GraphRetriever:
    """Knowledge-graph-style retriever.

    Builds a simple co-occurrence graph over documents: nodes are documents,
    edges connect documents that share significant keyword overlap.  Retrieval
    performs a breadth-first traversal seeded by the best keyword-matching
    documents.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self._corpus: list[Document] = []
        self._adj: dict[str, set[str]] = defaultdict(set)  # doc_id -> neighbour ids
        self._doc_map: dict[str, Document] = {}
        self._fitted = False

    # -- indexing -----------------------------------------------------------

    def add_documents(self, documents: list[Document]) -> None:
        """Add documents and build graph edges."""
        for doc in documents:
            self._corpus.append(doc)
            self._doc_map[doc.doc_id] = doc
        self._build_edges()
        self._fitted = True

    def _build_edges(self) -> None:
        """Connect documents that share keywords above the similarity threshold."""
        # Build inverted token sets
        doc_tokens: dict[str, frozenset[str]] = {}
        for doc in self._corpus:
            doc_tokens[doc.doc_id] = frozenset(_tokenize_bm25(doc.content))

        ids = list(doc_tokens.keys())
        threshold = self.config.graph_similarity_threshold

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id_i, id_j = ids[i], ids[j]
                tokens_i = doc_tokens[id_i]
                tokens_j = doc_tokens[id_j]
                if not tokens_i or not tokens_j:
                    continue
                jaccard = len(tokens_i & tokens_j) / len(tokens_i | tokens_j)
                if jaccard >= threshold:
                    self._adj[id_i].add(id_j)
                    self._adj[id_j].add(id_i)

    # -- retrieval ----------------------------------------------------------

    def retrieve(self, query: str, top_k: int | None = None) -> list[Document]:
        """BFS traversal from keyword-matched seed documents."""
        k = top_k or self.config.graph_top_k
        if not self._corpus:
            return []

        query_tokens = set(_tokenize_bm25(query))

        # Score each document by keyword overlap (seed relevance)
        seed_scores: dict[str, float] = {}
        for doc in self._corpus:
            doc_tokens = set(_tokenize_bm25(doc.content))
            overlap = len(query_tokens & doc_tokens)
            if overlap > 0:
                seed_scores[doc.doc_id] = overlap / max(1, len(query_tokens))

        if not seed_scores:
            return []

        # BFS from best seeds
        visited: set[str] = set()
        queue: list[str] = sorted(seed_scores, key=seed_scores.get, reverse=True)[:3]
        for s in queue:
            visited.add(s)

        results: list[Document] = []
        max_depth = self.config.graph_max_depth

        depth = 0
        while queue and depth < max_depth:
            next_queue: list[str] = []
            for doc_id in queue:
                for neighbour in self._adj.get(doc_id, set()):
                    if neighbour not in visited:
                        visited.add(neighbour)
                        next_queue.append(neighbour)
            queue = next_queue
            depth += 1

        # Sort visited by seed score (seeds first, then by graph proximity)
        for doc_id in visited:
            doc = self._doc_map[doc_id]
            base_score = seed_scores.get(doc_id, 0.1)  # non-seeds get small base
            doc_copy = Document(
                content=doc.content,
                source=doc.source,
                metadata={**doc.metadata, "retriever": "graph"},
                score=base_score,
                embedding=doc.embedding,
                doc_id=doc.doc_id,
            )
            results.append(doc_copy)

        results.sort(key=lambda d: d.score, reverse=True)
        return results[:k]

    def __repr__(self) -> str:
        edge_count = sum(len(v) for v in self._adj.values()) // 2
        return f"GraphRetriever(docs={len(self._corpus)}, edges={edge_count})"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tokenize_bm25(text: str) -> list[str]:
    """Tokenize using jieba (Chinese-friendly) with English word splitting."""
    try:
        import jieba

        tokens = list(jieba.cut(text, cut_all=False))
        # jieba often leaves whole English phrases as single tokens; split them further
        expanded: list[str] = []
        for tok in tokens:
            sub_tokens = tok.lower().split()
            expanded.extend(t for t in sub_tokens if t)
        return expanded if expanded else text.lower().split()
    except ImportError:
        # Fallback: simple whitespace tokenization
        return text.lower().split()


def _cosine_similarities(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity between *query* vector and every row of *matrix*."""
    query_norm = np.linalg.norm(query)
    if query_norm == 0:
        return np.zeros(len(matrix))
    matrix_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix_norms = np.maximum(matrix_norms, 1e-9)
    return (matrix @ query) / (query_norm * matrix_norms.squeeze())


def _manual_bm25_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """Simple BM25-like scoring without the rank-bm25 library."""
    if not doc_tokens:
        return 0.0
    k1 = 1.5
    b = 0.75
    avg_dl = len(doc_tokens)
    doc_len = len(doc_tokens)
    tf: dict[str, int] = defaultdict(int)
    for t in doc_tokens:
        tf[t] += 1
    score = 0.0
    for qt in set(query_tokens):
        f = tf.get(qt, 0)
        if f == 0:
            continue
        # IDF approximation
        n_qt = sum(1 for t in doc_tokens if t == qt)
        idf = math.log((1 + 1) / (n_qt + 0.5) + 1)
        denom = f + k1 * (1 - b + b * doc_len / max(avg_dl, 1))
        score += idf * (f * (k1 + 1)) / max(denom, 1e-9)
    return score


def _fallback_embed(text: str, dim: int = 384) -> np.ndarray:
    """Deterministic bag-of-words hash embedding (no external deps)."""
    import hashlib

    vec = np.zeros(dim, dtype=np.float32)
    tokens = text.lower().split()
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec
