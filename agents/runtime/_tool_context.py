# agents/runtime/_tool_context.py

"""
ToolContextWrapper — 将 AgentState 注入 PluginToolRegistry 的 context 参数。

修复 ReActLoop._execute_tool() 传 context={} 的问题，
使插件工具能访问当前对话上下文（conversation_id, intent, step_count 等）。

用法:
    wrapped = ToolContextWrapper(registry, state)
    result = wrapped.call("my_tool", {"param": "value"})
"""

from __future__ import annotations

from typing import Any

from agents.runtime.state import AgentState


class ToolContextWrapper:
    """包装 PluginToolRegistry，将 AgentState 关键字段注入 context。

    实现与 PluginToolRegistry.call() 相同的接口：
        call(name, context={}, params={}) -> dict
    但在调用底层 registry 前，用 AgentState 信息覆盖 context。
    """

    def __init__(self, registry: Any, state: AgentState) -> None:
        self._registry = registry
        self._state = state

    def call(self, name: str, context: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用插件工具，自动注入 AgentState 上下文。

        签名与 PluginToolRegistry.call() 兼容，可被 ReActLoop 直接调用。
        AgentState 信息会覆盖传入的 context 参数。

        Args:
            name: 工具名称
            context: 原始上下文（会被 AgentState 信息覆盖）
            params: 工具参数

        Returns:
            {"success": bool, "result": Any, "error": str}
        """
        effective_context = {
            "conversation_id": self._state.conversation_id,
            "intent": self._state.intent,
            "step_count": self._state.step_count,
            "message": self._state.message,
            "max_steps": self._state.max_steps,
        }
        return self._registry.call(name, context=effective_context, params=params or {})
