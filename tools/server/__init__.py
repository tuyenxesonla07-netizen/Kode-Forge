# tools/server/

"""
统一 Pipeline API 服务器。

提供 FastAPI 端点:
  POST /api/v1/pipeline/run     — 同步执行，等待结果
  POST /api/v1/pipeline/stream  — SSE 流式执行，实时推送节点进度
  GET  /api/v1/pipeline/status/{run_id}  — 查询运行状态
  GET  /api/v1/health           — 健康检查

用法:
    python -m tools.server.app --port 8080
    uvicorn tools.server.app:create_app --host 0.0.0.0 --port 8080
"""

from tools.server.app import create_app, ServerConfig
from tools.server.orchestrator import PipelineOrchestrator, SessionManager

__all__ = ["create_app", "PipelineOrchestrator", "ServerConfig", "SessionManager"]
