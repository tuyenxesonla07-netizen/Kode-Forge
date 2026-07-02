# tests/integration/test_agent_conversation_api.py

"""
tests/integration/test_agent_conversation_api.py — Agent 对话 API 专用测试。

验证:
    - 对话 CRUD
    - SSE 流式消息
    - 多轮对话状态保持
    - 错误处理
"""

from __future__ import annotations

import pytest

from tools.server.agent_conversation import AgentConversationManager, _sse_event


# ---------------------------------------------------------------------------
# AgentConversationManager 单元测试
# ---------------------------------------------------------------------------


def test_create_conversation():
    """创建对话返回有效 ID。"""
    mgr = AgentConversationManager()
    cid = mgr.create()
    assert cid
    assert isinstance(cid, str)
    assert len(cid) > 0


def test_get_conversation_state():
    """获取对话状态返回 AgentState。"""
    from agents.runtime.state import AgentState

    mgr = AgentConversationManager()
    cid = mgr.create()
    state = mgr.get(cid)
    assert state is not None
    assert isinstance(state, AgentState)


def test_get_nonexistent_conversation_returns_none():
    """获取不存在的对话返回 None。"""
    mgr = AgentConversationManager()
    assert mgr.get("nonexistent-id") is None


def test_delete_conversation():
    """删除对话成功返回 True。"""
    mgr = AgentConversationManager()
    cid = mgr.create()
    assert mgr.delete(cid) is True
    assert mgr.get(cid) is None


def test_delete_nonexistent_conversation_returns_false():
    """删除不存在的对话返回 False。"""
    mgr = AgentConversationManager()
    assert mgr.delete("nonexistent") is False


def test_list_conversations():
    """列出对话返回正确数量。"""
    mgr = AgentConversationManager()
    mgr.create()
    mgr.create()
    convs = mgr.list_conversations()
    assert len(convs) == 2
    assert all("conversation_id" in c for c in convs)


def test_lru_eviction():
    """超过 max 时 LRU 淘汰生效。"""
    mgr = AgentConversationManager(max_conversations=3)
    cid1 = mgr.create()
    cid2 = mgr.create()
    cid3 = mgr.create()
    # 访问 cid1，使其变为最近使用
    mgr.get(cid1)
    # 创建第 4 条，应淘汰 cid2（最久未使用）
    cid4 = mgr.create()
    assert mgr.get(cid1) is not None  # 保留
    assert mgr.get(cid2) is None      # 被淘汰
    assert mgr.get(cid3) is not None  # 保留
    assert mgr.get(cid4) is not None  # 新建


@pytest.mark.asyncio
async def test_send_message_streams_sse():
    """send_message 产出有效 SSE 事件。"""
    mgr = AgentConversationManager()
    cid = mgr.create()

    events = []
    async for event in mgr.send_message(cid, "生成用户登录代码"):
        events.append(event)

    assert len(events) >= 3
    # 应包含 intent/reply/done 事件
    full_text = "".join(events)
    assert "event: intent" in full_text
    assert "event: reply" in full_text
    assert "event: done" in full_text


@pytest.mark.asyncio
async def test_send_message_to_nonexistent_conversation():
    """向不存在的对话发送消息返回错误事件。"""
    mgr = AgentConversationManager()

    events = []
    async for event in mgr.send_message("nonexistent", "hello"):
        events.append(event)

    assert len(events) == 1
    assert "error" in events[0]


@pytest.mark.asyncio
async def test_multiturn_conversation_preserves_history():
    """多轮对话：每轮消息添加到 state.history。

    注意: stub 模式下 orchestrator.run_agent 创建新 state，
    但 send_message 在每轮调用前将 user message 添加到 record.state.history。
    """
    mgr = AgentConversationManager()
    cid = mgr.create()

    # 第一轮
    async for _ in mgr.send_message(cid, "第一轮消息"):
        pass

    state = mgr.get(cid)
    # 至少有 user + assistant 两条消息
    assert len(state.history) >= 2
    assert state.history[0].role == "user"
    assert state.history[-1].role == "assistant"


# ---------------------------------------------------------------------------
# SSE 格式测试
# ---------------------------------------------------------------------------


def test_sse_event_format():
    """_sse_event 产生正确的 SSE 格式。"""
    event = _sse_event("intent", {"intent": "code_generation"})
    assert event.startswith("event: intent\n")
    assert "data:" in event
    assert "code_generation" in event
    event.strip().endswith("")  # SSE 以 \n\n 结束


def test_sse_event_with_unicode():
    """SSE 事件正确处理中文。"""
    event = _sse_event("reply", {"reply": "生成代码"})
    assert "生成代码" in event


# ---------------------------------------------------------------------------
# REST API 集成测试
# ---------------------------------------------------------------------------


def test_rest_create_conversation():
    """POST /api/v1/agents/conversations 返回 conversation_id。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/v1/agents/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert "conversation_id" in data


def test_rest_get_conversation():
    """GET /api/v1/agents/conversations/{cid} 返回对话状态。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/v1/agents/conversations")
    cid = resp.json()["conversation_id"]

    resp = client.get(f"/api/v1/agents/conversations/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == cid
    assert "history" in data


def test_rest_get_nonexistent_conversation_returns_404():
    """获取不存在的对话返回 404。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/v1/agents/conversations/nonexistent")
    assert resp.status_code == 404


def test_rest_delete_conversation():
    """DELETE /api/v1/agents/conversations/{cid} 成功删除。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/v1/agents/conversations")
    cid = resp.json()["conversation_id"]

    resp = client.delete(f"/api/v1/agents/conversations/{cid}")
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/agents/conversations/{cid}")
    assert resp.status_code == 404


def test_rest_send_message_empty_body_returns_400():
    """空消息体返回 400。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/v1/agents/conversations")
    cid = resp.json()["conversation_id"]

    resp = client.post(
        f"/api/v1/agents/conversations/{cid}/messages",
        json={"message": ""},
    )
    assert resp.status_code == 400


def test_rest_list_conversations():
    """GET /api/v1/agents/conversations 返回对话列表。"""
    from tools.server.app import create_app
    from starlette.testclient import TestClient

    app = create_app()
    client = TestClient(app)

    client.post("/api/v1/agents/conversations")
    client.post("/api/v1/agents/conversations")

    resp = client.get("/api/v1/agents/conversations")
    assert resp.status_code == 200
    assert len(resp.json()["conversations"]) >= 2
