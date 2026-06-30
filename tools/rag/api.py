"""RAG REST API + WebSocket — 生产级 HTTP 服务。

对标 Dify 的 API 能力:
    1. RESTful API — 文档摄入、查询、搜索、管理
    2. WebSocket — 实时流式查询结果
    3. OpenAPI/Swagger 文档
    4. CORS 支持

Endpoints:
    POST /api/v1/ingest           — 摄入文档
    POST /api/v1/query            — 查询 (搜索引擎模式)
    POST /api/v1/query/cognitive  — 查询 (认知引擎模式)
    GET  /api/v1/documents        — 列出所有文档
    GET  /api/v1/documents/{id}   — 获取单个文档
    DELETE /api/v1/documents/{id} — 删除文档
    GET  /api/v1/health           — 健康检查
    GET  /api/v1/metrics          — 指标查询
    WS   /ws/v1/query            — WebSocket 流式查询

Usage:
    from tools.rag import RAGServer

    server = RAGServer(pipeline, observer)
    server.run(host="0.0.0.0", port=8080)

    # 或者使用已有的 app (例如用于 uvicorn):
    app = server.app
    # uvicorn tools.rag.api:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from tools.rag.rag_types import RAGConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

@dataclass
class IngestRequest:
    """文档摄入请求。"""
    documents: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IngestRequest:
        return cls(documents=data.get("documents", []))


@dataclass
class QueryRequest:
    """查询请求。"""
    query: str
    top_k: int = 10
    mode: str = "search"          # "search" | "cognitive"
    user_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryRequest:
        return cls(
            query=data.get("query", ""),
            top_k=data.get("top_k", 10),
            mode=data.get("mode", "search"),
            user_id=data.get("user_id"),
        )


@dataclass
class QueryResponse:
    """查询响应。"""
    query: str
    answer: str
    intent: str = ""
    documents: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer": self.answer,
            "intent": self.intent,
            "documents": self.documents,
            "metadata": self.metadata,
            "latency_ms": round(self.latency_ms, 2),
        }


# ---------------------------------------------------------------------------
# FastAPI 应用构建
# ---------------------------------------------------------------------------

def _build_fastapi_app(
    pipeline: Any,
    observer: Any = None,
    cors_origins: list[str] | None = None,
) -> Any:
    """构建 FastAPI 应用。

    如果 FastAPI 不可用，返回 None。
    """
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        logger.warning(
            "FastAPI not installed. REST API unavailable. "
            "Install with: pip install fastapi uvicorn"
        )
        return None

    app = FastAPI(
        title="RAG Engine API",
        description="Dual-engine RAG system: Search Engine + Cognitive Engine",
        version="1.0.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 依赖注入 ----

    def _get_pipeline():
        return pipeline

    def _get_observer():
        return observer

    # ---- REST Endpoints ----

    @app.get("/api/v1/health")
    async def health_check():
        """健康检查。"""
        obs = _get_observer()
        if obs:
            return obs.health_check(
                vector_store=getattr(pipeline, "_vector_store", None)
            )
        return {"status": "ok", "timestamp": time.time()}

    @app.get("/api/v1/metrics")
    async def get_metrics():
        """获取指标。"""
        obs = _get_observer()
        if obs:
            return obs.get_metrics_summary()
        return {"error": "metrics not enabled"}

    @app.post("/api/v1/ingest")
    async def ingest(request: dict[str, Any]):
        """摄入文档。"""
        start = time.time()

        try:
            req = IngestRequest.from_dict(request)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

        if not req.documents:
            raise HTTPException(status_code=400, detail="No documents provided")

        from tools.rag.rag_types import Document

        docs = []
        for doc_data in req.documents:
            content = doc_data.get("content", "")
            source = doc_data.get("source", "api")
            metadata = doc_data.get("metadata", {})
            if not content:
                continue
            docs.append(Document(content=content, source=source, metadata=metadata))

        if not docs:
            raise HTTPException(status_code=400, detail="No valid documents")

        pipeline.ingest(docs)
        elapsed = (time.time() - start) * 1000

        # 记录
        obs = _get_observer()
        if obs and obs.logger:
            obs.logger.log_ingest(
                num_documents=len(docs),
                num_chunks=len(docs),
                latency_ms=elapsed,
            )

        return {
            "status": "ok",
            "num_documents": len(docs),
            "latency_ms": round(elapsed, 2),
        }

    @app.post("/api/v1/query")
    async def query(request: dict[str, Any]):
        """搜索引擎模式查询。"""
        start = time.time()

        try:
            req = QueryRequest.from_dict(request)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

        if not req.query.strip():
            raise HTTPException(status_code=400, detail="Empty query")

        try:
            result = pipeline.query(req.query, top_k=req.top_k)
            elapsed = (time.time() - start) * 1000

            # 构建响应
            docs = []
            for doc in result.reranked_documents:
                docs.append({
                    "content": doc.content[:500],  # 截断
                    "source": doc.source,
                    "score": round(doc.score, 4),
                    "doc_id": doc.doc_id,
                    "metadata": {k: v for k, v in doc.metadata.items()
                                 if k != "embedding"},
                })

            response = QueryResponse(
                query=req.query,
                answer=result.answer,
                intent=result.intent.primary_intent if result.intent else "",
                documents=docs,
                metadata=result.metadata,
                latency_ms=elapsed,
            )

            # 记录
            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=len(docs),
                    latency_ms=elapsed,
                    intent=response.intent,
                )

            return response.to_dict()

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=0,
                    latency_ms=elapsed,
                    error=str(e),
                )
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/query/cognitive")
    async def query_cognitive(request: dict[str, Any]):
        """认知引擎模式查询。"""
        start = time.time()

        try:
            req = QueryRequest.from_dict(request)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

        if not req.query.strip():
            raise HTTPException(status_code=400, detail="Empty query")

        kwargs: dict[str, Any] = {}
        mode = request.get("mode", req.mode)

        # 如果请求中包含 skill_manager 等
        if "skill_manager" in request:
            kwargs["skill_manager"] = request["skill_manager"]
        if "memory_manager" in request:
            kwargs["memory_manager"] = request["memory_manager"]
        if "user_model" in request:
            kwargs["user_model"] = request["user_model"]
        if "extract_skill" in request:
            kwargs["extract_skill"] = request["extract_skill"]

        try:
            result = pipeline.query_cognitive(req.query, top_k=req.top_k, **kwargs)
            elapsed = (time.time() - start) * 1000

            docs = []
            for doc in result.reranked_documents:
                docs.append({
                    "content": doc.content[:500],
                    "source": doc.source,
                    "score": round(doc.score, 4),
                    "doc_id": doc.doc_id,
                    "metadata": {k: v for k, v in doc.metadata.items()
                                 if k != "embedding"},
                })

            response = QueryResponse(
                query=req.query,
                answer=result.answer,
                intent=result.intent.primary_intent if result.intent else "",
                documents=docs,
                metadata={**result.metadata, "mode": "cognitive"},
                latency_ms=elapsed,
            )

            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=len(docs),
                    latency_ms=elapsed,
                    intent=response.intent,
                    backend="cognitive",
                )

            return response.to_dict()

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=0,
                    latency_ms=elapsed,
                    error=str(e),
                )
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/documents")
    async def list_documents():
        """列出所有文档 (摘要)。"""
        docs = []
        for doc in pipeline._documents:
            docs.append({
                "doc_id": doc.doc_id,
                "source": doc.source,
                "content_preview": doc.content[:200],
                "metadata": {k: v for k, v in doc.metadata.items()
                             if k != "embedding"},
            })
        return {"documents": docs, "total": len(docs)}

    @app.get("/api/v1/documents/{doc_id}")
    async def get_document(doc_id: str):
        """获取单个文档。"""
        for doc in pipeline._documents:
            if doc.doc_id == doc_id:
                return {
                    "doc_id": doc.doc_id,
                    "content": doc.content,
                    "source": doc.source,
                    "metadata": {
                        k: v for k, v in doc.metadata.items()
                        if k != "embedding"
                    },
                }
        raise HTTPException(status_code=404, detail="Document not found")

    @app.delete("/api/v1/documents/{doc_id}")
    async def delete_document(doc_id: str):
        """删除单个文档。"""
        before = len(pipeline._documents)
        pipeline._documents = [
            d for d in pipeline._documents if d.doc_id != doc_id
        ]
        removed = before - len(pipeline._documents)
        if removed == 0:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"status": "ok", "removed": removed}

    # ---- WebSocket ----

    @app.websocket("/ws/v1/query")
    async def websocket_query(websocket: WebSocket):
        """WebSocket 流式查询。

        请求格式 (JSON):
            {"query": "...", "top_k": 5}

        响应格式 (streaming):
            {"type": "start"}
            {"type": "document", "content": "...", "source": "...", "score": 0.8}
            {"type": "document", ...}
            {"type": "answer", "text": "..."}
            {"type": "end", "latency_ms": 123}
        """
        await websocket.accept()

        try:
            data = await websocket.receive_text()
            request = json.loads(data)
            req = QueryRequest.from_dict(request)

            await websocket.send_json({"type": "start", "query": req.query})

            start = time.time()

            # 查询
            result = pipeline.query(req.query, top_k=req.top_k)

            # 流式发送文档
            for doc in result.reranked_documents:
                await websocket.send_json({
                    "type": "document",
                    "content": doc.content[:500],
                    "source": doc.source,
                    "score": round(doc.score, 4),
                    "doc_id": doc.doc_id,
                })
                await asyncio.sleep(0.01)  # 让出控制权

            elapsed = (time.time() - start) * 1000

            # 发送答案
            await websocket.send_json({
                "type": "answer",
                "text": result.answer,
            })

            # 结束
            await websocket.send_json({
                "type": "end",
                "latency_ms": round(elapsed, 2),
                "num_documents": len(result.reranked_documents),
            })

        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })
            except Exception:
                pass

    # OpenAPI 文档
    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        """Swagger UI。"""
        from fastapi.openapi.docs import get_swagger_ui_html

        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="RAG Engine API",
            swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
            swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        )

    return app


def create_rag_router(
    pipeline: Any = None,
    observer: Any = None,
) -> Any:
    """创建 RAG APIRouter，可挂载到主 FastAPI 应用。

    用法:
        from tools.rag.api import create_rag_router
        rag_router = create_rag_router(pipeline, observer)
        app.include_router(rag_router)

    路由前缀: /api/v1/rag
    """
    try:
        from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
    except ImportError:
        logger.warning("FastAPI not installed. create_rag_router returns None.")
        return None

    router = APIRouter(prefix="/api/v1/rag", tags=["rag"])

    def _get_pipeline():
        return pipeline

    def _get_observer():
        return observer

    @router.get("/health")
    async def rag_health():
        """健康检查。"""
        obs = _get_observer()
        if obs:
            return obs.health_check(
                vector_store=getattr(pipeline, "_vector_store", None)
            )
        return {"status": "ok", "timestamp": time.time()}

    @router.get("/metrics")
    async def rag_metrics():
        """获取指标。"""
        obs = _get_observer()
        if obs:
            return obs.get_metrics_summary()
        return {"error": "metrics not enabled"}

    @router.post("/ingest")
    async def rag_ingest(request: dict[str, Any]):
        """摄入文档。"""
        start = time.time()
        try:
            req = IngestRequest.from_dict(request)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

        if not req.documents:
            raise HTTPException(status_code=400, detail="No documents provided")

        from tools.rag.rag_types import Document

        docs = []
        for doc_data in req.documents:
            content = doc_data.get("content", "")
            source = doc_data.get("source", "api")
            metadata = doc_data.get("metadata", {})
            if not content:
                continue
            docs.append(Document(content=content, source=source, metadata=metadata))

        if not docs:
            raise HTTPException(status_code=400, detail="No valid documents")

        pipeline.ingest(docs)
        elapsed = (time.time() - start) * 1000

        obs = _get_observer()
        if obs and obs.logger:
            obs.logger.log_ingest(
                num_documents=len(docs),
                num_chunks=len(docs),
                latency_ms=elapsed,
            )

        return {
            "status": "ok",
            "num_documents": len(docs),
            "latency_ms": round(elapsed, 2),
        }

    @router.post("/query")
    async def rag_query(request: dict[str, Any]):
        """搜索引擎模式查询。"""
        start = time.time()
        try:
            req = QueryRequest.from_dict(request)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

        if not req.query.strip():
            raise HTTPException(status_code=400, detail="Empty query")

        try:
            result = pipeline.query(req.query, top_k=req.top_k)
            elapsed = (time.time() - start) * 1000

            docs = []
            for doc in result.reranked_documents:
                docs.append({
                    "content": doc.content[:500],
                    "source": doc.source,
                    "score": round(doc.score, 4),
                    "doc_id": doc.doc_id,
                    "metadata": {k: v for k, v in doc.metadata.items()
                                 if k != "embedding"},
                })

            response = QueryResponse(
                query=req.query,
                answer=result.answer,
                intent=result.intent.primary_intent if result.intent else "",
                documents=docs,
                metadata=result.metadata,
                latency_ms=elapsed,
            )

            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=len(docs),
                    latency_ms=elapsed,
                    intent=response.intent,
                )

            return response.to_dict()

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=0,
                    latency_ms=elapsed,
                    error=str(e),
                )
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/query/cognitive")
    async def rag_query_cognitive(request: dict[str, Any]):
        """认知引擎模式查询。"""
        start = time.time()
        try:
            req = QueryRequest.from_dict(request)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

        if not req.query.strip():
            raise HTTPException(status_code=400, detail="Empty query")

        kwargs: dict[str, Any] = {}
        mode = request.get("mode", req.mode)
        if "skill_manager" in request:
            kwargs["skill_manager"] = request["skill_manager"]
        if "memory_manager" in request:
            kwargs["memory_manager"] = request["memory_manager"]
        if "user_model" in request:
            kwargs["user_model"] = request["user_model"]
        if "extract_skill" in request:
            kwargs["extract_skill"] = request["extract_skill"]

        try:
            result = pipeline.query_cognitive(req.query, top_k=req.top_k, **kwargs)
            elapsed = (time.time() - start) * 1000

            docs = []
            for doc in result.reranked_documents:
                docs.append({
                    "content": doc.content[:500],
                    "source": doc.source,
                    "score": round(doc.score, 4),
                    "doc_id": doc.doc_id,
                    "metadata": {k: v for k, v in doc.metadata.items()
                                 if k != "embedding"},
                })

            response = QueryResponse(
                query=req.query,
                answer=result.answer,
                intent=result.intent.primary_intent if result.intent else "",
                documents=docs,
                metadata={**result.metadata, "mode": "cognitive"},
                latency_ms=elapsed,
            )

            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=len(docs),
                    latency_ms=elapsed,
                    intent=response.intent,
                    backend="cognitive",
                )

            return response.to_dict()

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            obs = _get_observer()
            if obs:
                obs.record_query(
                    query=req.query,
                    num_results=0,
                    latency_ms=elapsed,
                    error=str(e),
                )
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/documents")
    async def rag_list_documents():
        """列出所有文档 (摘要)。"""
        docs = []
        for doc in pipeline._documents:
            docs.append({
                "doc_id": doc.doc_id,
                "source": doc.source,
                "content_preview": doc.content[:200],
                "metadata": {k: v for k, v in doc.metadata.items()
                             if k != "embedding"},
            })
        return {"documents": docs, "total": len(docs)}

    @router.get("/documents/{doc_id}")
    async def rag_get_document(doc_id: str):
        """获取单个文档。"""
        for doc in pipeline._documents:
            if doc.doc_id == doc_id:
                return {
                    "doc_id": doc.doc_id,
                    "content": doc.content,
                    "source": doc.source,
                    "metadata": {
                        k: v for k, v in doc.metadata.items()
                        if k != "embedding"
                    },
                }
        raise HTTPException(status_code=404, detail="Document not found")

    @router.delete("/documents/{doc_id}")
    async def rag_delete_document(doc_id: str):
        """删除单个文档。"""
        before = len(pipeline._documents)
        pipeline._documents = [
            d for d in pipeline._documents if d.doc_id != doc_id
        ]
        removed = before - len(pipeline._documents)
        if removed == 0:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"status": "ok", "removed": removed}

    # ---- WebSocket ----

    @router.websocket("/ws/query")
    async def rag_websocket_query(websocket: WebSocket):
        """WebSocket 流式查询。"""
        await websocket.accept()
        try:
            data = await websocket.receive_text()
            request = json.loads(data)
            req = QueryRequest.from_dict(request)

            await websocket.send_json({"type": "start", "query": req.query})

            start = time.time()
            result = pipeline.query(req.query, top_k=req.top_k)

            for doc in result.reranked_documents:
                await websocket.send_json({
                    "type": "document",
                    "content": doc.content[:500],
                    "source": doc.source,
                    "score": round(doc.score, 4),
                    "doc_id": doc.doc_id,
                })
                await asyncio.sleep(0.01)

            elapsed = (time.time() - start) * 1000

            await websocket.send_json({
                "type": "answer",
                "text": result.answer,
            })

            await websocket.send_json({
                "type": "end",
                "latency_ms": round(elapsed, 2),
                "num_documents": len(result.reranked_documents),
            })

        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })
            except Exception:
                pass

    return router


# ---------------------------------------------------------------------------
# Flask 备选方案 (如果 FastAPI 不可用)
# ---------------------------------------------------------------------------

def _build_flask_app(
    pipeline: Any,
    observer: Any = None,
) -> Any:
    """构建 Flask 应用 (轻量备选)。"""
    try:
        from flask import Flask, request, jsonify
    except ImportError:
        logger.warning("Neither FastAPI nor Flask installed. REST API unavailable.")
        return None

    app = Flask(__name__)

    @app.route("/api/v1/health", methods=["GET"])
    def health_check():
        obs = observer
        if obs:
            return jsonify(obs.health_check(
                vector_store=getattr(pipeline, "_vector_store", None)
            ))
        return jsonify({"status": "ok"})

    @app.route("/api/v1/query", methods=["POST"])
    def query():
        start = time.time()
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data"}), 400

        req = QueryRequest.from_dict(data)
        if not req.query.strip():
            return jsonify({"error": "Empty query"}), 400

        try:
            result = pipeline.query(req.query, top_k=req.top_k)
            elapsed = (time.time() - start) * 1000

            docs = [{
                "content": doc.content[:500],
                "source": doc.source,
                "score": round(doc.score, 4),
                "doc_id": doc.doc_id,
            } for doc in result.reranked_documents]

            response = QueryResponse(
                query=req.query,
                answer=result.answer,
                intent=result.intent.primary_intent if result.intent else "",
                documents=docs,
                metadata=result.metadata,
                latency_ms=elapsed,
            )

            if observer:
                observer.record_query(
                    query=req.query,
                    num_results=len(docs),
                    latency_ms=elapsed,
                    intent=response.intent,
                )

            return jsonify(response.to_dict())

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/v1/ingest", methods=["POST"])
    def ingest():
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data"}), 400

        from tools.rag.rag_types import Document

        docs = []
        for doc_data in data.get("documents", []):
            content = doc_data.get("content", "")
            if content:
                docs.append(Document(
                    content=content,
                    source=doc_data.get("source", "api"),
                    metadata=doc_data.get("metadata", {}),
                ))

        pipeline.ingest(docs)
        return jsonify({"status": "ok", "num_documents": len(docs)})

    return app


# ---------------------------------------------------------------------------
# RAG 服务器
# ---------------------------------------------------------------------------

class RAGServer:
    """RAG HTTP 服务器。

    自动选择 FastAPI (优先) 或 Flask (备选)。

    Usage:
        server = RAGServer(pipeline, observer)
        server.run(host="0.0.0.0", port=8080)
    """

    def __init__(
        self,
        pipeline: Any,
        observer: Any = None,
        cors_origins: list[str] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.observer = observer

        # 优先尝试 FastAPI
        self._app = _build_fastapi_app(pipeline, observer, cors_origins)
        self._backend = "fastapi" if self._app else None

        # 备选 Flask
        if self._app is None:
            self._app = _build_flask_app(pipeline, observer)
            self._backend = "flask" if self._app else None

    @property
    def app(self) -> Any:
        """返回 ASGI/WSGI 应用。"""
        return self._app

    @property
    def backend(self) -> str | None:
        """返回使用的后端框架名称。"""
        return self._backend

    def run(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        **kwargs: Any,
    ) -> None:
        """启动服务器。"""
        if self._backend == "fastapi":
            import uvicorn

            uvicorn.run(self._app, host=host, port=port, **kwargs)
        elif self._backend == "flask":
            self._app.run(host=host, port=port, **kwargs)
        else:
            raise RuntimeError(
                "No web framework available. "
                "Install fastapi+uvicorn or flask."
            )

    def __repr__(self) -> str:
        return f"RAGServer(backend={self._backend})"
