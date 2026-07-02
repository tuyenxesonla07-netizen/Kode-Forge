# agents/runtime/__init__.py

"""
agents/runtime — 对话式 Agent 运行时。

提供 AgentState（对话状态管理）和 ReActLoop（Agent 主循环）。

用法:
    from agents.runtime import AgentState, create_agent_state
    from agents.runtime import ReActLoop, ReActLoopConfig
"""

from __future__ import annotations

from __future__ import annotations

from typing import Any

from agents.runtime.state import (
    AgentState,
    Message,
    ToolCallRecord,
    StopReason,
    create_agent_state,
)
from agents.runtime.loop import (
    ReActLoop,
    ReActLoopConfig,
    ReActStep,
)
from agents.runtime._tool_context import ToolContextWrapper

# AgentOrchestrator is NOT imported here to avoid circular imports.
# Import it directly: from agents.runtime.orchestrator import AgentOrchestrator

__all__ = [
    # State
    "AgentState",
    "Message",
    "ToolCallRecord",
    "StopReason",
    "create_agent_state",
    # Loop
    "ReActLoop",
    "ReActLoopConfig",
    "ReActStep",
    # Tool context injection
    "ToolContextWrapper",
    # Orchestrator (import directly to avoid circular: from agents.runtime.orchestrator import ...)
    "AgentOrchestrator",
    "AgentOrchestratorConfig",
]


def __getattr__(name: str) -> Any:
    """Lazy import for AgentOrchestrator to avoid circular imports."""
    if name == "AgentOrchestrator":
        from agents.runtime.orchestrator import AgentOrchestrator
        return AgentOrchestrator
    if name == "AgentOrchestratorConfig":
        from agents.runtime.orchestrator import AgentOrchestratorConfig
        return AgentOrchestratorConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
