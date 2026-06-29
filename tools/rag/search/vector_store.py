"""向量存储引擎 — Milvus / Chroma / 内存回退三级架构。

对标 Dify 的向量存储能力:
    - Milvus: 生产级分布式向量数据库 (需要 Milvus 服务)
    - Chroma: 轻量级本地向量库 (需要 chromadb 包)
    - 内存: 纯 NumPy 实现 (始终可用，无需安装)

Usage:
    from tools.rag import VectorStore

    # 自动选择最佳后端
    store = VectorStore(collection_name="rag_docs", dim=384)
    store.add(documents)

    # Milvus 模式
    store = VectorStore(
        backend="milvus",
        collection_name="rag_docs",
        dim=384,
        milvus_uri="http://localhost:19530",
    )

    # Chroma 模式
    store = VectorStore(
        backend="chroma",
        collection_name="rag_docs",
        persist_dir="./.chroma",
    )

    # 查询
    results = store.search(query_embedding, top_k=10)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from tools.rag.rag_types import RAGConfig, Document

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 向量存储后端类型
# ---------------------------------------------------------------------------

VectorStoreBackend = Any  # MilvusCollection | ChromaCollection | InMemoryStore


# ---------------------------------------------------------------------------
# 搜索结果
# ---------------------------------------------------------------------------

@dataclass
class VectorSearchResult:
    """单条向量搜索结果。"""

    doc_id: str
    score: float
    document: Document | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 内存向量存储 (始终可用)
# ---------------------------------------------------------------------------

class InMemoryVectorStore:
    """纯 NumPy 内存向量存储。

    作为 Milvus/Chroma 不可用时的回退方案。
    支持增量添加、相似度搜索。
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self._embeddings: np.ndarray | None = None
        self._doc_ids: list[str] = []
        self._documents: dict[str, Document] = {}

    def add(
        self,
        embeddings: np.ndarray,
        doc_ids: list[str],
        documents: list[Document] | None = None,
    ) -> None:
        """添加向量。"""
        if len(embeddings) != len(doc_ids):
            raise ValueError("embeddings and doc_ids must have same length")

        # 确保维度正确
        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)

        if self._embeddings is None:
            self._embeddings = embeddings.astype(np.float32)
        else:
            self._embeddings = np.vstack([self._embeddings, embeddings]).astype(np.float32)

        self._doc_ids.extend(doc_ids)
        if documents:
            for did, doc in zip(doc_ids, documents):
                # 使用调用方提供的 doc_id 作为 key (而非 Document 自动生成的)
                self._documents[did] = doc

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        doc_ids: list[str] | None = None,
    ) -> list[VectorSearchResult]:
        """搜索最近邻。"""
        if self._embeddings is None or len(self._doc_ids) == 0:
            return []

        query = query_embedding.astype(np.float32)
        if query.ndim == 1:
            query = query.reshape(1, -1)

        # 余弦相似度
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-8)
        normalized = self._embeddings / norms

        query_norm = np.linalg.norm(query)
        query_norm = max(query_norm, 1e-8)
        query_normalized = query / query_norm

        scores = normalized @ query_normalized.T.flatten()

        # 过滤指定 doc_ids
        if doc_ids:
            id_set = set(doc_ids)
            indices = [i for i, did in enumerate(self._doc_ids) if did in id_set]
            if not indices:
                return []
            filtered_scores = scores[indices]
            top_local = np.argsort(filtered_scores)[::-1][:top_k]
            results = []
            for local_idx in top_local:
                global_idx = indices[local_idx]
                did = self._doc_ids[global_idx]
                results.append(VectorSearchResult(
                    doc_id=did,
                    score=float(filtered_scores[local_idx]),
                    document=self._documents.get(did),
                    metadata=self._documents.get(did, Document(content="", source="")).metadata if did in self._documents else {},
                ))
            return results

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            did = self._doc_ids[idx]
            results.append(VectorSearchResult(
                doc_id=did,
                score=float(scores[idx]),
                document=self._documents.get(did),
                metadata=self._documents.get(did, Document(content="", source="")).metadata if did in self._documents else {},
            ))
        return results

    def delete(self, doc_ids: list[str]) -> int:
        """删除向量。"""
        if self._embeddings is None:
            return 0

        id_set = set(doc_ids)
        keep_indices = [i for i, did in enumerate(self._doc_ids) if did not in id_set]

        if len(keep_indices) == len(self._doc_ids):
            return 0  # 无变化

        removed = len(self._doc_ids) - len(keep_indices)
        self._embeddings = self._embeddings[keep_indices]
        self._doc_ids = [self._doc_ids[i] for i in keep_indices]
        for did in doc_ids:
            self._documents.pop(did, None)

        return removed

    def get_by_id(self, doc_id: str) -> Document | None:
        """根据 ID 获取文档。"""
        return self._documents.get(doc_id)

    @property
    def count(self) -> int:
        return len(self._doc_ids)

    def clear(self) -> None:
        """清空所有数据。"""
        self._embeddings = None
        self._doc_ids = []
        self._documents = {}


# ---------------------------------------------------------------------------
# Milvus 向量存储
# ---------------------------------------------------------------------------

class MilvusVectorStore:
    """Milvus 向量数据库后端。

    需要运行中的 Milvus 服务。使用 pymilvus 客户端。
    """

    def __init__(
        self,
        collection_name: str = "rag_docs",
        dim: int = 384,
        milvus_uri: str = "http://localhost:19530",
        metric_type: str = "IP",   # inner product
    ) -> None:
        self.collection_name = collection_name
        self.dim = dim
        self.milvus_uri = milvus_uri
        self.metric_type = metric_type
        self._collection = None

    def _get_collection(self):
        """获取或创建 Milvus collection。"""
        if self._collection is not None:
            return self._collection

        try:
            from pymilvus import (
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                connections,
                utility,
            )
        except ImportError:
            raise ImportError(
                "pymilvus is required for Milvus backend. "
                "Install with: pip install pymilvus"
            )

        connections.connect("default", uri=self.milvus_uri)

        # 检查 collection 是否存在
        if utility.has_collection(self.collection_name):
            self._collection = Collection(self.collection_name)
            self._collection.load()
            return self._collection

        # 创建新 collection
        fields = [
            FieldSchema(
                name="doc_id",
                dtype=DataType.VARCHAR,
                max_length=64,
                is_primary=True,
            ),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=self.dim,
            ),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
            ),
            FieldSchema(
                name="source",
                dtype=DataType.VARCHAR,
                max_length=256,
            ),
        ]

        schema = CollectionSchema(fields, description="RAG document vectors")
        self._collection = Collection(self.collection_name, schema)

        # 创建索引
        index_params = {
            "metric_type": self.metric_type,
            "index_type": "IVF_FLAT",
            "params": {"nlist": 1024},
        }
        self._collection.create_index("embedding", index_params)
        self._collection.load()

        return self._collection

    def add(
        self,
        embeddings: np.ndarray,
        doc_ids: list[str],
        documents: list[Document] | None = None,
    ) -> None:
        """添加文档向量到 Milvus。"""
        coll = self._get_collection()

        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)

        content_list = []
        source_list = []
        if documents:
            for doc in documents:
                content_list.append(doc.content[:65000])  # Milvus 限制
                source_list.append(doc.source)
        else:
            content_list = [""] * len(doc_ids)
            source_list = [""] * len(doc_ids)

        data = [
            doc_ids,
            embeddings.tolist(),
            content_list,
            source_list,
        ]

        coll.insert(data)
        coll.flush()

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        doc_ids: list[str] | None = None,
    ) -> list[VectorSearchResult]:
        """向量搜索。"""
        coll = self._get_collection()

        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        search_params = {
            "metric_type": self.metric_type,
            "params": {"nprobe": 10},
        }

        # 如果有 doc_ids 过滤
        expr = None
        if doc_ids:
            formatted = ', '.join(f'"{did}"' for did in doc_ids)
            expr = f"doc_id in [{formatted}]"

        results = coll.search(
            data=query_embedding.tolist(),
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["doc_id", "content", "source"],
        )

        search_results = []
        for hits in results:
            for hit in hits:
                doc = Document(
                    content=hit.entity.get("content", ""),
                    source=hit.entity.get("source", ""),
                    metadata={"doc_id": hit.entity.get("doc_id")},
                )
                search_results.append(VectorSearchResult(
                    doc_id=hit.entity.get("doc_id", ""),
                    score=hit.distance,
                    document=doc,
                    metadata={"source": hit.entity.get("source", "")},
                ))

        return search_results

    def delete(self, doc_ids: list[str]) -> int:
        """删除向量。"""
        if not doc_ids:
            return 0

        coll = self._get_collection()
        formatted = ', '.join(f'"{did}"' for did in doc_ids)
        expr = f"doc_id in [{formatted}]"
        coll.delete(expr)
        return len(doc_ids)

    def get_by_id(self, doc_id: str) -> Document | None:
        """根据 ID 获取文档。"""
        coll = self._get_collection()
        expr = f'doc_id == "{doc_id}"'
        result = coll.query(expr, output_fields=["doc_id", "content", "source"])
        if result:
            r = result[0]
            return Document(
                content=r.get("content", ""),
                source=r.get("source", ""),
            )
        return None

    @property
    def count(self) -> int:
        coll = self._get_collection()
        return coll.num_entities

    def clear(self) -> None:
        """清空 collection。"""
        coll = self._get_collection()
        coll.drop()


# ---------------------------------------------------------------------------
# Chroma 向量存储
# ---------------------------------------------------------------------------

class ChromaVectorStore:
    """Chroma 轻量级向量数据库后端。"""

    def __init__(
        self,
        collection_name: str = "rag_docs",
        persist_dir: str | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.persist_dir = persist_dir
        self._collection = None

    def _get_collection(self):
        """获取或创建 Chroma collection。"""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "chromadb is required for Chroma backend. "
                "Install with: pip install chromadb"
            )

        if self.persist_dir:
            client = chromadb.PersistentClient(path=self.persist_dir)
        else:
            client = chromadb.Client()

        self._collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def add(
        self,
        embeddings: np.ndarray,
        doc_ids: list[str],
        documents: list[Document] | None = None,
    ) -> None:
        """添加文档到 Chroma。"""
        coll = self._get_collection()

        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)

        contents = [doc.content for doc in documents] if documents else None
        metadatas = [{"source": doc.source} for doc in documents] if documents else None

        coll.add(
            ids=doc_ids,
            embeddings=embeddings.tolist(),
            documents=contents,
            metadatas=metadatas,
        )

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        doc_ids: list[str] | None = None,
    ) -> list[VectorSearchResult]:
        """搜索最近邻。"""
        coll = self._get_collection()

        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        # 构建 where 过滤
        where = None
        if doc_ids:
            if len(doc_ids) == 1:
                where = {"id": doc_ids[0]}
            else:
                where = {"id": {"$in": doc_ids}}

        kwargs: dict[str, Any] = {
            "query_embeddings": query_embedding.tolist(),
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = coll.query(**kwargs)

        search_results = []
        ids_list = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        docs_content = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i, did in enumerate(ids_list):
            score = 1.0 - distances[i]  # Chroma 返回距离，转为相似度
            doc = Document(
                content=docs_content[i] if i < len(docs_content) else "",
                source=metadatas[i].get("source", "") if i < len(metadatas) else "",
            )
            search_results.append(VectorSearchResult(
                doc_id=did,
                score=max(0.0, min(1.0, score)),
                document=doc,
                metadata=metadatas[i] if i < len(metadatas) else {},
            ))

        return search_results

    def delete(self, doc_ids: list[str]) -> int:
        """删除文档。"""
        if not doc_ids:
            return 0

        coll = self._get_collection()
        coll.delete(ids=doc_ids)
        return len(doc_ids)

    def get_by_id(self, doc_id: str) -> Document | None:
        """根据 ID 获取文档。"""
        coll = self._get_collection()
        result = coll.get(ids=[doc_id], include=["documents", "metadatas"])
        ids_list = result.get("ids", [])
        if not ids_list:
            return None

        content = result.get("documents", [[]])
        meta = result.get("metadatas", [[]])
        return Document(
            content=content[0] if content else "",
            source=meta[0].get("source", "") if meta else "",
        )

    @property
    def count(self) -> int:
        coll = self._get_collection()
        return coll.count()

    def clear(self) -> None:
        """清空 collection。"""
        coll = self._get_collection()
        coll.delete(where={"id": {"$ne": "__empty__"}})


# ---------------------------------------------------------------------------
# 统一向量存储入口 (自动选择后端)
# ---------------------------------------------------------------------------

class VectorStore:
    """统一的向量存储接口。

    自动选择最佳可用后端:
        1. Milvus (如果 pymilvus 可用且服务在运行)
        2. Chroma (如果 chromadb 可用)
        3. 内存 (始终可用)

    也可通过 backend 参数强制指定后端。

    Usage:
        store = VectorStore(dim=384)
        store.add(embeddings, doc_ids, documents)
        results = store.search(query_embedding, top_k=10)
    """

    BACKEND_MEMORY = "memory"
    BACKEND_MILVUS = "milvus"
    BACKEND_CHROMA = "chroma"

    def __init__(
        self,
        backend: str | None = None,
        collection_name: str = "rag_docs",
        dim: int = 384,
        milvus_uri: str = "http://localhost:19530",
        persist_dir: str | None = None,
    ) -> None:
        self.backend_name = backend or self._auto_select()
        self._backend = self._create_backend(
            backend=self.backend_name,
            collection_name=collection_name,
            dim=dim,
            milvus_uri=milvus_uri,
            persist_dir=persist_dir,
        )

        logger.info("VectorStore using backend: %s", self.backend_name)

    @staticmethod
    def _auto_select() -> str:
        """自动选择最佳后端。"""
        # 检查 Milvus
        try:
            import pymilvus  # noqa: F401

            from pymilvus import connections

            connections.connect("default", uri="http://localhost:19530")
            connections.disconnect("default")
            return "milvus"
        except Exception:
            pass

        # 检查 Chroma
        try:
            import chromadb  # noqa: F401

            return "chroma"
        except ImportError:
            pass

        # 回退到内存
        return "memory"

    def _create_backend(
        self,
        backend: str,
        collection_name: str,
        dim: int,
        milvus_uri: str,
        persist_dir: str | None,
    ) -> VectorStoreBackend:
        """创建具体的后端实例。"""
        if backend == "milvus":
            try:
                return MilvusVectorStore(
                    collection_name=collection_name,
                    dim=dim,
                    milvus_uri=milvus_uri,
                )
            except Exception as e:
                logger.warning("Milvus unavailable (%s), falling back to memory", e)
                return InMemoryVectorStore(dim=dim)

        elif backend == "chroma":
            try:
                return ChromaVectorStore(
                    collection_name=collection_name,
                    persist_dir=persist_dir,
                )
            except Exception as e:
                logger.warning("Chroma unavailable (%s), falling back to memory", e)
                return InMemoryVectorStore(dim=dim)

        return InMemoryVectorStore(dim=dim)

    # ---- 统一接口 ---------------------------------------------------------

    def add(
        self,
        embeddings: np.ndarray,
        doc_ids: list[str],
        documents: list[Document] | None = None,
    ) -> None:
        """添加文档向量。"""
        self._backend.add(embeddings, doc_ids, documents)

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        doc_ids: list[str] | None = None,
    ) -> list[VectorSearchResult]:
        """搜索最近邻。"""
        return self._backend.search(query_embedding, top_k, doc_ids)

    def delete(self, doc_ids: list[str]) -> int:
        """删除向量。"""
        return self._backend.delete(doc_ids)

    def get_by_id(self, doc_id: str) -> Document | None:
        """根据 ID 获取文档。"""
        return self._backend.get_by_id(doc_id)

    @property
    def count(self) -> int:
        """返回文档数量。"""
        return self._backend.count

    def clear(self) -> None:
        """清空所有数据。"""
        self._backend.clear()

    def __repr__(self) -> str:
        return f"VectorStore(backend={self.backend_name}, count={self.count})"
