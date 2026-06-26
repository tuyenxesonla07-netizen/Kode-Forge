# tools/memory/session_state.py

"""
会话状态 — 每个会话的状态快照和检查点。

参考 customer-service-agent 的 SessionState：
- session_id + user_id 标识
- status: idle | running | completed | blocked | handoff
- facts: 会话中沉淀的关键事实（订单号、模块名等）
- checkpoint/resume: 支持长任务中断恢复
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SessionState:
    """
    单个会话的状态。

    每个会话独立一个 SessionState 实例，记录：
    - 基本信息: session_id, user_id
    - 运行状态: status, step, tool_calls_made
    - 沉淀事实: facts (模块名、订单号等)
    - 检查点: checkpoints (支持 resume)
    """
    user_id: str = "default"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = "idle"          # idle | running | completed | blocked | handoff
    step: int = 0
    tool_calls_made: int = 0
    intent: str = ""
    facts: dict = field(default_factory=dict)
    checkpoints: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def checkpoint(self, label: str, data: dict = None) -> dict:
        """
        保存检查点快照。

        长任务中断后可从最近检查点恢复。

        Args:
            label: 检查点标签
            data: 可选的额外数据，会合并到快照中
        """
        snapshot = {
            "label": label,
            "time": _now(),
            "intent": self.intent,
            "status": self.status,
            "step": self.step,
            "tool_calls_made": self.tool_calls_made,
            "facts": dict(self.facts),
        }
        if data:
            snapshot["data"] = data
        self.checkpoints.append(snapshot)
        self.updated_at = _now()
        return snapshot

    def update(self, **fields) -> None:
        """更新状态字段"""
        for key, value in fields.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = _now()

    @classmethod
    def resume(cls, user_id: str, snapshot: dict) -> SessionState:
        """从检查点恢复"""
        state = cls(user_id=user_id)
        state.intent = snapshot.get("intent", "")
        state.status = snapshot.get("status", "idle")
        state.step = snapshot.get("step", 0)
        state.tool_calls_made = snapshot.get("tool_calls_made", 0)
        state.facts = dict(snapshot.get("facts", {}))
        state.updated_at = _now()
        return state

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "status": self.status,
            "step": self.step,
            "tool_calls_made": self.tool_calls_made,
            "intent": self.intent,
            "facts": self.facts,
            "checkpoints_count": len(self.checkpoints),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
