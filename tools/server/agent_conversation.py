# tools/server/agent_conversation.py

"""
Agent Conversation Manager — 内存中的多轮对话状态管理。

管理 AgentOrchestrator 的对话生命周期:
    - 创建/获取对话
    - 发送消息并流式产出 SSE 事件
    - LRU 淘汰 (max 100 条)

用法:
    from tools.server.agent_conversation import AgentConversationManager

    mgr = AgentConversationManager()
    cid = mgr.create()
    async for event in mgr.send_message(cid, "帮我构建用户登录模块"):
        print(event)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ConversationRecord
# ---------------------------------------------------------------------------


@dataclass
class ConversationRecord:
    """单条对话记录。"""

    conversation_id: str
    state: Any  # AgentState
    created_at: float
    last_active: float
    sse_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    access_order: int = 0  # 单调递增 LRU 排序键


# ---------------------------------------------------------------------------
# AgentConversationManager
# ---------------------------------------------------------------------------


class AgentConversationManager:
    """内存中的对话状态管理（max 100 条，LRU 淘汰）。"""

    def __init__(
        self,
        max_conversations: int = 100,
        orchestrator: Any = None,
    ) -> None:
        self._convs: dict[str, ConversationRecord] = {}
        self._max = max_conversations
        self._access_counter: int = 0  # 单调递增计数器，用于 LRU 排序

        # 延迟导入避免循环依赖
        if orchestrator is not None:
            self._orch = orchestrator
        else:
            from agents.runtime.orchestrator import AgentOrchestrator

            self._orch = AgentOrchestrator()

    # ── 公共 API ────────────────────────────────────────────

    def create(self) -> str:
        """创建新对话，返回 conversation_id。"""
        self._evict_if_needed()
        cid = str(uuid.uuid4())[:12]
        from agents.runtime.state import create_agent_state

        state = create_agent_state(message="", conversation_id=cid)
        now = time.time()
        self._access_counter += 1
        self._convs[cid] = ConversationRecord(
            conversation_id=cid,
            state=state,
            created_at=now,
            last_active=now,
            access_order=self._access_counter,
        )
        logger.info("[ConversationManager] Created conversation: %s", cid)
        return cid

    def get(self, conversation_id: str) -> Any | None:
        """获取对话状态（AgentState 或 None）。"""
        record = self._convs.get(conversation_id)
        if record is None:
            return None
        self._access_counter += 1
        record.last_active = time.time()
        record.access_order = self._access_counter
        return record.state

    def delete(self, conversation_id: str) -> bool:
        """删除对话，成功返回 True。"""
        if conversation_id in self._convs:
            del self._convs[conversation_id]
            logger.info("[ConversationManager] Deleted conversation: %s", conversation_id)
            return True
        return False

    def list_conversations(self) -> list[dict[str, Any]]:
        """列出所有活跃对话摘要。"""
        return [
            {
                "conversation_id": r.conversation_id,
                "intent": r.state.intent or "unknown",
                "message_count": len(r.state.history),
                "step_count": r.state.step_count,
                "created_at": r.created_at,
                "last_active": r.last_active,
            }
            for r in self._convs.values()
        ]

    async def send_message(
        self,
        conversation_id: str,
        message: str,
    ) -> AsyncGenerator[str, None]:
        """运行 Agent 并流式产出 SSE 事件。

        事件序列:
            event: intent  data: {"intent": "..."}
            event: step    data: {"step": N, "total": M}
            event: reply   data: {"reply": "..."}
            event: done    data: {"stop_reason": "..."}
        """
        record = self._convs.get(conversation_id)
        if record is None:
            yield _sse_event("error", {"error": "conversation not found"})
            return

        self._access_counter += 1
        record.last_active = time.time()
        record.access_order = self._access_counter
        state = record.state
        state.message = message
        state.add_message("user", message)

        try:
            new_state = await self._orch.run_agent(
                message,
                conversation_id=conversation_id,
            )
            record.state = new_state

            # intent 事件（run_agent 后才获得真实意图）
            yield _sse_event("intent", {"intent": new_state.intent or "unknown"})

            yield _sse_event("step", {
                "step": new_state.step_count,
                "total": new_state.max_steps,
            })

            yield _sse_event("reply", {"reply": new_state.reply or ""})

            yield _sse_event("done", {
                "stop_reason": str(new_state.stop_reason),
                "step_count": new_state.step_count,
            })
        except Exception as e:
            logger.error("[ConversationManager] send_message error: %s", e, exc_info=True)
            yield _sse_event("error", {"error": str(e)})
            yield _sse_event("done", {"stop_reason": "error"})

    # ── 内部方法 ───────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        """LRU 淘汰：超过 max 时移除最久未使用的对话。"""
        if len(self._convs) < self._max:
            return
        # 找出 access_order 最小的记录（最久未访问）
        oldest_cid = min(self._convs, key=lambda cid: self._convs[cid].access_order)
        del self._convs[oldest_cid]
        logger.debug("[ConversationManager] Evicted LRU conversation: %s", oldest_cid)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """构造 SSE 事件字符串。"""
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
