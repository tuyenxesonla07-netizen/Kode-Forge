# tests/integration/test_unified_runtime.py

"""
tests/integration/test_unified_runtime.py — 统一运行时集成测试。

验证:
    - AgentOrchestrator 端到端工作
    - RAG 路由挂载在统一服务器上
    - Pipeline + RAG 共存
    - LangGraph 后端在可用时能接通
    - Agent Conversation API 端到端
"""

from __future__ import annotations

import pytest

from agents.runtime.orchestrator import AgentOrchestrator, AgentOrchestratorConfig
from agents.runtime.state import StopReason


# ---------------------------------------------------------------------------
# AgentOrchestrator 端到端
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_e2e_code_generation():
    """端到端: code_generation 意图完整流程。"""
    orch = AgentOrchestrator()
    state = await orch.run_agent("实现一个 Python 快速排序")
    assert state.stop_reason == StopReason.ANSWERED
    assert state.intent == "code_generation"
    assert len(state.trace) > 0


@pytest.mark.asyncio
async def test_orchestrator_e2e_knowledge_query():
    """端到端: knowledge_query 意图完整流程。"""
    orch = AgentOrchestrator()
    state = await orch.run_agent("什么是依赖注入？")
    assert state.stop_reason == StopReason.ANSWERED
    assert state.intent == "knowledge_query"


@pytest.mark.asyncio
async def test_orchestrator_tool_context_injection():
    """验证 AgentState 被注入到 tool context（tool_registry=None 时不崩溃）。"""
    orch = AgentOrchestrator()
    # tool_registry 为 None 时，ToolContextWrapper 不会被触发
    # 但 orchestrator 本身应正常工作
    state = await orch.run_agent("生成代码")
    assert state.stop_reason == StopReason.ANSWERED


# ---------------------------------------------------------------------------
# 统一 HTTP 服务器测试
# ---------------------------------------------------------------------------


def test_create_app_with_rag_engine():
    """验证 create_app 挂载 RAG 路由后仍能正常创建。"""
    from tools.rag import RAGPipeline, RAGConfig
    from tools.server.app import create_app

    rag_config = RAGConfig()
    rag_pipeline = RAGPipeline(rag_config)

    # 摄入一些文档
    from tools.rag.rag_types import Document
    rag_pipeline.ingest([
        Document(content="Python 是一种高级编程语言", source="test"),
        Document(content="依赖注入是一种设计模式", source="test"),
    ])

    app = create_app(rag_engine=rag_pipeline)
    assert app is not None


def test_pipeline_and_rag_endpoints_coexist():
    """验证 Pipeline 和 RAG 端点共存于同一应用。"""
    from tools.rag import RAGPipeline, RAGConfig
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    rag_config = RAGConfig()
    rag_pipeline = RAGPipeline(rag_config)

    app = create_app(rag_engine=rag_pipeline)
    client = TestClient(app)

    # Pipeline health 端点
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "claude-codex-multi-agent"

    # RAG health 端点
    resp = client.get("/api/v1/rag/health")
    assert resp.status_code == 200

    # Pipeline run 端点（无 LLM 时返回 stub 或 500）
    resp = client.post("/api/v1/pipeline/run", json={"requirement": "测试"})
    assert resp.status_code in (200, 500)

    # RAG query 端点
    resp = client.post("/api/v1/rag/query", json={"query": "Python"})
    assert resp.status_code == 200


def test_rag_ingest_and_query():
    """验证 RAG 摄入 + 查询完整流程。"""
    from tools.rag import RAGPipeline, RAGConfig
    from tools.rag.rag_types import Document
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    rag_config = RAGConfig()
    rag_pipeline = RAGPipeline(rag_config)
    rag_pipeline.ingest([
        Document(content="快速排序使用分治法策略", source="algo"),
    ])

    app = create_app(rag_engine=rag_pipeline)
    client = TestClient(app)

    resp = client.post("/api/v1/rag/query", json={"query": "快速排序"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data


# ---------------------------------------------------------------------------
# LangGraph 后端测试（条件跳过）
# ---------------------------------------------------------------------------


def test_langgraph_backend_if_available():
    """如果 langgraph 安装则测试 to_langgraph，否则跳过。"""
    try:
        import langgraph  # noqa: F401
    except ImportError:
        pytest.skip("langgraph not installed")

    from tools.compiler.pipeline_compiler import PipelineCompiler

    compiler = PipelineCompiler()
    compiled = compiler.compile_from_config()
    graph = compiled.to_langgraph()
    assert graph is not None


def test_pipeline_orchestrator_backend_param():
    """验证 PipelineOrchestrator 接受 backend 参数。"""
    from tools.server.orchestrator import PipelineOrchestrator

    orch = PipelineOrchestrator(backend="workflow")
    assert orch.backend == "workflow"

    orch_lg = PipelineOrchestrator(backend="langgraph")
    assert orch_lg.backend == "langgraph"


# ---------------------------------------------------------------------------
# Agent Conversation API 端到端
# ---------------------------------------------------------------------------


def test_agent_conversation_via_api():
    """验证 Agent Conversation REST API 完整流程。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    # 1. 创建对话
    resp = client.post("/api/v1/agents/conversations")
    assert resp.status_code == 200
    cid = resp.json()["conversation_id"]
    assert cid

    # 2. 获取对话状态
    resp = client.get(f"/api/v1/agents/conversations/{cid}")
    assert resp.status_code == 200
    assert resp.json()["conversation_id"] == cid

    # 3. 列出对话
    resp = client.get("/api/v1/agents/conversations")
    assert resp.status_code == 200
    convs = resp.json()["conversations"]
    assert len(convs) >= 1

    # 4. 删除对话
    resp = client.delete(f"/api/v1/agents/conversations/{cid}")
    assert resp.status_code == 200

    # 5. 确认已删除
    resp = client.get(f"/api/v1/agents/conversations/{cid}")
    assert resp.status_code == 404


def test_conversation_sse_endpoint_exists():
    """验证 SSE 消息端点存在并返回 text/event-stream。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    # 创建对话
    resp = client.post("/api/v1/agents/conversations")
    cid = resp.json()["conversation_id"]

    # 发送消息 (SSE)
    resp = client.post(
        f"/api/v1/agents/conversations/{cid}/messages",
        json={"message": "生成代码"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
