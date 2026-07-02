# agents/runtime/state.py

"""
AgentState — 对话式 Agent 的核心状态管理。

借鉴 codex 的 AgentState TypedDict 设计，但改用 @dataclass 以符合本代码库惯例。
ReActLoop、SupervisorRouter、WorkflowRunner 均通过 AgentState 传递上下文。

用法:
    from agents.runtime.state import AgentState, Message, ToolCallRecord, create_agent_state

    state = create_agent_state("帮我构建用户登录模块")
    state.intent = "code_generation"
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Stop reasons — Agent 循环终止原因
# ---------------------------------------------------------------------------

class StopReason:
    """Agent 循环终止原因常量。"""
    NONE = ""
    ANSWERED = "answered"
    NEED_MORE_INFO = "need_more_info"
    WAITING_HUMAN = "waiting_human"
    MAX_STEPS = "max_steps"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Message — 对话消息
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """单条对话消息。"""
    role: str       # "user" | "assistant" | "system" | "tool"
    content: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ToolCallRecord — 工具调用记录
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    """单次工具调用的完整记录。"""
    tool_name: str
    arguments: dict
    result: Any
    success: bool
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# AgentState — 对话式 Agent 的完整状态
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    """对话式 Agent 的完整状态容器。

    贯穿 ReActLoop、SupervisorRouter、WorkflowRunner 各阶段。
    """

    # --- 对话上下文 ---
    conversation_id: str = ""
    message: str = ""
    history: list[Message] = field(default_factory=list)

    # --- 意图路由 ---
    intent: str = ""
    intent_confidence: float = 0.0
    slots: dict = field(default_factory=dict)

    # --- 流水线执行 ---
    pipeline_run_id: str = ""
    compiled_pipeline_ref: Any = None

    # --- 工具调用 ---
    tool_results: dict = field(default_factory=dict)
    tool_history: list[ToolCallRecord] = field(default_factory=list)

    # --- 审批 ---
    pending_approval: dict | None = None
    approval_result: dict | None = None

    # --- 输出 ---
    reply: str = ""
    cards: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    # --- 控制 ---
    stop_reason: str = StopReason.NONE
    step_count: int = 0
    max_steps: int = 10

    # --- 错误 ---
    last_error: str = ""

    def should_stop(self) -> bool:
        """判断 Agent 循环是否应该终止。"""
        return self.stop_reason != StopReason.NONE

    def increment_step(self) -> None:
        """递增步数计数器。"""
        self.step_count += 1

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> Message:
        """添加一条对话消息并返回该消息。"""
        msg = Message(role=role, content=content, metadata=metadata or {})
        self.history.append(msg)
        return msg

    def add_tool_record(self, tool_name: str, arguments: dict, result: Any,
                        success: bool, duration_ms: int = 0) -> ToolCallRecord:
        """添加一条工具调用记录并返回该记录。"""
        record = ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            success=success,
            duration_ms=duration_ms,
        )
        self.tool_history.append(record)
        self.tool_results[tool_name] = result
        return record

    def add_trace(self, event: str, data: dict | None = None) -> dict:
        """添加一条 trace 记录。"""
        entry = {"event": event, "step": self.step_count, "data": data or {}}
        self.trace.append(entry)
        return entry

    def check_max_steps(self) -> bool:
        """检查是否超过最大步数，超过则设置 stop_reason。"""
        if self.step_count >= self.max_steps:
            self.stop_reason = StopReason.MAX_STEPS
            return True
        return False


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_agent_state(message: str, conversation_id: str = "", **kwargs: Any) -> AgentState:
    """创建初始 AgentState。

    Args:
        message: 用户消息
        conversation_id: 会话 ID（为空则自动生成 UUID）
        **kwargs: 其他 AgentState 字段覆盖值

    Returns:
        初始化好的 AgentState 实例
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    state = AgentState(
        message=message,
        conversation_id=conversation_id,
    )

    # 自动添加用户消息到 history
    state.add_message("user", message)

    # 应用额外字段覆盖
    for key, value in kwargs.items():
        if hasattr(state, key):
            setattr(state, key, value)

    return state
