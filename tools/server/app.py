# tools/server/app.py

"""
FastAPI 服务器 — Pipeline API 入口。

提供以下端点:
    POST /api/v1/pipeline/run     — 同步执行流水线
    POST /api/v1/pipeline/stream  — SSE 流式执行
    GET  /api/v1/pipeline/status/{run_id}  — 查询运行状态
    GET  /api/v1/health           — 健康检查
    GET  /api/v1/openapi.json     — OpenAPI 规范
    GET  /docs                    — Swagger UI

安全特性:
    - API Key 认证 (X-API-Key header, SHA-256 哈希存储)
    - CORS 可配置
    - 安全响应头 (X-Content-Type-Options, X-Frame-Options, ...)
    - 请求体大小限制
    - 可选的文档保护
    - 错误脱敏
    - Guardrails 输入/输出护栏

子模块:
    - tools.server.auth       — 认证工具 (hash_api_key, APIKeyValidator, AuthMiddleware)
    - tools.server.middleware — 中间件 (CorrelationId, SecurityHeaders, Guardrails, ...)

用法:
    python -m tools.server.app --port 8080
    uvicorn tools.server.app:create_app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility (old code imports these from app.py)
# ---------------------------------------------------------------------------

from tools.server.auth import hash_api_key, verify_api_key, APIKeyValidator
from tools.server.middleware import (
    SecurityHeadersMiddleware,
    RequestSizeLimitMiddleware,
    sanitize_error,
    sanitize_log_message,
    SENSITIVE_PATTERNS,
)


# ---------------------------------------------------------------------------
# ServerConfig
# ---------------------------------------------------------------------------

@dataclass
class ServerConfig:
    """服务器配置"""

    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    # 流水线配置
    max_concurrent_pipelines: int = 5
    pipeline_timeout_seconds: int = 300  # 5 分钟

    # 会话持久化
    session_dir: str = ".sessions"

    # CORS
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    # 认证 (SHA-256 哈希列表，空列表 = 无认证开发模式)
    api_keys: list[str] = field(default_factory=list)

    # 限流 (e.g. "30/minute", "100/hour"；空字符串 = 无限流)
    rate_limit: str = ""

    # 请求体大小限制 (bytes，默认 10MB)
    max_request_size: int = 10 * 1024 * 1024

    # 保护 /docs 和 /openapi.json (需要 api_keys 非空才生效)
    protect_docs: bool = False

    # TLS 证书路径 (Phase 9 预留)
    tls_cert_path: str = ""
    tls_key_path: str = ""

    # 日志
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> ServerConfig:
        """从环境变量加载配置"""
        import os

        # Parse API keys from env
        keys_str = os.getenv("CC_API_KEYS", "")
        api_keys = [k.strip() for k in keys_str.split(",") if k.strip()] if keys_str else []

        # Parse CORS origins from env
        cors_str = os.getenv("CC_CORS_ORIGINS", "")
        cors_origins = [o.strip() for o in cors_str.split(",") if o.strip()] if cors_str else ["*"]

        return cls(
            host=os.getenv("CC_SERVER_HOST", "0.0.0.0"),
            port=int(os.getenv("CC_SERVER_PORT", "8080")),
            debug=os.getenv("CC_DEBUG", "").lower() in ("1", "true", "yes"),
            max_concurrent_pipelines=int(os.getenv("CC_MAX_CONCURRENT", "5")),
            pipeline_timeout_seconds=int(os.getenv("CC_TIMEOUT", "300")),
            api_keys=api_keys,
            rate_limit=os.getenv("CC_RATE_LIMIT", ""),
            protect_docs=os.getenv("CC_PROTECT_DOCS", "").lower() in ("1", "true", "yes"),
            tls_cert_path=os.getenv("CC_TLS_CERT_PATH", ""),
            tls_key_path=os.getenv("CC_TLS_KEY_PATH", ""),
            log_level=os.getenv("CC_LOG_LEVEL", "INFO"),
        )


# ---------------------------------------------------------------------------
# create_app + main
# ---------------------------------------------------------------------------

def create_app(
    llm_provider=None,
    tool_registry=None,
    rag_engine=None,
    config: ServerConfig | None = None,
):
    """
    创建 FastAPI 应用。

    Args:
        llm_provider: LLM provider 实例
        tool_registry: ToolRegistry 实例
        rag_engine: RAG Pipeline 实例
        config: 服务器配置

    Returns:
        FastAPI app 实例
    """
    try:
        from fastapi import Body, FastAPI, HTTPException, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse, StreamingResponse
    except ImportError:
        raise ImportError(
            "FastAPI is required for the server. "
            "Install with: pip install fastapi uvicorn"
        )

    from tools.server.orchestrator import PipelineOrchestrator, PipelineEvent
    from tools.server.auth import AuthMiddleware
    from tools.server.middleware import (
        CorrelationIdMiddleware,
        GuardrailsMiddleware,
    )

    if config is None:
        config = ServerConfig()

    # ─── 优雅关闭 (Gap 21) ──────────────────────────────────

    _engine_ref: list = []  # 弱引用列表，避免全局变量

    async def lifespan(app):
        """应用生命周期 — 启动时初始化，关闭时等待任务完成"""
        logger.info("[Server] Starting up...")
        _engine_ref.clear()
        yield
        # 关闭时优雅等待
        logger.info("[Server] Shutting down, waiting for active tasks...")
        if _engine_ref:
            engine = _engine_ref[0]
            if engine and not engine._shutdown_event.is_set():
                engine.shutdown()
            if engine:
                await engine.wait_for_completion(timeout=30.0)
        logger.info("[Server] Shutdown complete.")

    # 条件开放文档
    docs_url = "/docs" if not config.protect_docs else None
    openapi_url = "/openapi.json" if not config.protect_docs else None

    app = FastAPI(
        title="Claude-Codex Multi-Agent Pipeline API",
        description="Schema-first multi-agent code generation pipeline with RAG dual-engine",
        version="1.0.0",
        docs_url=docs_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    # ─── 安全中间件 ──────────────────────────────────────────

    # 1. 认证 (全局中间件，当 api_keys 非空时拦截所有请求)
    app.add_middleware(AuthMiddleware, api_keys=config.api_keys or [])

    # 2. Guardrails (输入/输出护栏)
    app.add_middleware(GuardrailsMiddleware, enabled=True)

    # 3. 安全响应头
    app.add_middleware(SecurityHeadersMiddleware)

    # 4. 请求体大小限制
    app.add_middleware(RequestSizeLimitMiddleware, max_size_bytes=config.max_request_size)

    # 5. CORS (可配置)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 6. Correlation ID (必须在所有中间件之后，路由之前)
    app.add_middleware(CorrelationIdMiddleware)

    # ─── Prometheus 指标 ─────────────────────────────────────

    from tools.observability.production_observability import setup_metrics
    metrics = setup_metrics()

    # ─── 全局异常处理 (Gap 14: 错误脱敏) ─────────────────────

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局异常处理 — 脱敏后返回"""
        logger.error(
            "[API] Unhandled exception: %s",
            exc,
            exc_info=True,
            extra={"request_id": getattr(request.state, "request_id", "unknown")},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": sanitize_error(exc)},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """HTTP 异常处理 — 保留原始 status_code，脱敏 detail"""
        if exc.status_code >= 500:
            logger.error(
                "[API] HTTP %d: %s",
                exc.status_code,
                exc.detail,
                exc_info=True,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": sanitize_error(exc)},
        )

    # ─── Orchestrator ────────────────────────────────────────

    # 创建 orchestrator（共享实例）
    orchestrator = PipelineOrchestrator(
        llm_provider=llm_provider,
        tool_registry=tool_registry,
        rag_engine=rag_engine,
    )

    # 注册 engine 引用（供 lifespan 和 health 使用）
    _engine_ref.append(orchestrator.engine)

    # ─── 健康检查 (Gap 23) ──────────────────────────────────

    @app.get("/api/v1/health")
    async def health_check():
        """健康检查 — 返回活跃 pipeline 数和引擎状态"""
        engine = orchestrator.engine if orchestrator else None
        active_count = engine.active_task_count if engine else 0
        engine_running = engine is not None and not engine._shutdown_event.is_set()

        # 超过 10 个活跃 pipeline 标记为 degraded
        status = "ok"
        if active_count > 10:
            status = "degraded"

        return {
            "status": status,
            "service": "claude-codex-multi-agent",
            "version": "1.0.0",
            "active_pipelines": active_count,
            "engine_running": engine_running,
        }

    # ─── Prometheus 指标端点 (Gap 24) ────────────────────────

    @app.get("/metrics")
    async def prometheus_metrics():
        """Prometheus 指标端点"""
        from starlette.responses import Response
        return Response(
            content=metrics["get_metrics"](),
            media_type="text/plain",
        )

    # ─── 同步执行 ─────────────────────────────────────────────

    @app.post("/api/v1/pipeline/run")
    async def run_pipeline(body: dict = Body(...)):
        """
        同步执行流水线。

        等待流水线完成，返回结果 JSON。

        请求体:
            {
                "requirement": "构建用户登录模块",
                "context": {}  // 可选
            }
        """
        requirement = body.get("requirement", "").strip()
        if not requirement:
            raise HTTPException(status_code=400, detail="Missing 'requirement' field")

        context = body.get("context", {})

        try:
            result = await orchestrator.run_pipeline(requirement)
            return JSONResponse(content=result)
        except Exception as e:
            logger.error("[API] Pipeline execution failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    # ─── SSE 流式执行 ─────────────────────────────────────────

    @app.post("/api/v1/pipeline/stream")
    async def stream_pipeline(body: dict = Body(...)):
        """
        SSE 流式执行流水线。

        实时推送节点执行进度，使用 text/event-stream 格式。

        请求体:
            {
                "requirement": "构建用户登录模块"
            }

        SSE 事件格式:
            event: step
            data: {"tag": "think|node_start|node_complete|...", "content": "..."}

            data: [DONE]
        """
        requirement = body.get("requirement", "").strip()
        if not requirement:
            raise HTTPException(status_code=400, detail="Missing 'requirement' field")

        async def event_stream():
            try:
                async for event in orchestrator.stream_pipeline(requirement):
                    yield event.to_sse()
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error("[API] Stream pipeline failed: %s", e, exc_info=True)
                error_data = json.dumps({
                    "tag": "error",
                    "content": str(e),
                }, ensure_ascii=False)
                yield f"event: step\ndata: {error_data}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # ─── 查询运行状态 ─────────────────────────────────────────

    @app.get("/api/v1/pipeline/status/{run_id}")
    async def get_pipeline_status(run_id: str):
        """
        查询流水线运行状态。

        返回当前运行的状态（running / success / failed）。
        """
        result = orchestrator.engine.get_run_result(run_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        return {
            "run_id": run_id,
            "status": result.status,
            "execution_time_ms": result.execution_time_ms,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "log_count": len(result.logs),
        }

    # ─── 组件状态 ─────────────────────────────────────────────

    @app.get("/api/v1/components")
    async def list_components():
        """列出所有已加载的组件及其状态"""
        from tools.workflow.engine import WorkflowEngine

        engine = orchestrator.engine
        workflows = [
            {"id": w.id, "name": w.name, "node_count": len(w.nodes)}
            for w in engine._workflows.values()
        ]

        return {
            "workflows": workflows,
            "workflow_count": len(workflows),
            "rags_engine": orchestrator.rag_engine is not None,
            "llm_provider": orchestrator.llm_provider is not None,
            "tool_registry": orchestrator.tool_registry is not None,
        }

    # ─── 历史记录 ─────────────────────────────────────────────

    @app.get("/api/v1/sessions")
    async def list_sessions(limit: int = 20):
        """列出历史流水线运行记录"""
        runs = orchestrator.list_runs(limit=limit)
        return {"sessions": runs, "count": len(runs)}

    @app.get("/api/v1/sessions/{run_id}")
    async def get_session(run_id: str):
        """获取指定运行记录的完整结果"""
        run = orchestrator.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Session not found: {run_id}")
        return run

    return app


def main():
    """CLI 入口: python -m tools.server.app --port 8080"""
    import uvicorn

    parser = argparse.ArgumentParser(description="CC Pipeline Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    app = create_app()

    print(f"""
╔══════════════════════════════════════════════════╗
║  Claude-Codex Multi-Agent Pipeline API Server    ║
╠══════════════════════════════════════════════════╣
║  URL:  http://{args.host}:{args.port}              ║
║  Docs: http://{args.host}:{args.port}/docs         ║
║  SSE:  POST /api/v1/pipeline/stream              ║
╚══════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="debug" if args.debug else "info",
    )


if __name__ == "__main__":
    main()
