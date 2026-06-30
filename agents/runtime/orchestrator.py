# agents/runtime/orchestrator.py

"""
AgentOrchestrator — V0.5.0 统一 Agent 运行时入口。

连接 SupervisorRouter（意图路由）+ ReActLoop（主循环）+ PluginToolRegistry（工具执行），
提供单一 async 入口和 sync 兼容入口。

用法:
    # 异步用法（推荐）
    orchestrator = AgentOrchestrator()
    state = await orchestrator.run_agent("帮我构建用户登录模块")

    # 同步用法（CLI / 旧代码兼容）
    orchestrator = AgentOrchestrator()
    state = orchestrator.run_agent_sync("帮我构建用户登录模块")

    # 带配置
    config = AgentOrchestratorConfig(max_steps=15, llm_provider=provider)
    orchestrator = AgentOrchestrator(config=config)
    state = await orchestrator.run_agent("生成代码", conversation_id="conv-123")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agents.runtime.state import AgentState, StopReason, create_agent_state
from agents.supervisor.router import SupervisorRouter

logger = logging.getLogger(__name__)


@dataclass
class AgentOrchestratorConfig:
    """AgentOrchestrator 配置。"""
    max_steps: int = 10
    llm_provider: Any = None
    skill_registry: Any = None
    tool_registry: Any = None
    approval_handler: Any = None


class AgentOrchestrator:
    """V0.5.0 统一 Agent 运行时入口。

    内部流程：
        1. create_agent_state() 创建/恢复对话状态
        2. SupervisorRouter.route() 意图分类 + 路由
        3. ReActLoop.run() 执行工具循环
        4. 返回最终 AgentState
    """

    def __init__(self, config: AgentOrchestratorConfig | None = None) -> None:
        self._config = config or AgentOrchestratorConfig()
        self._router = SupervisorRouter(
            llm_provider=self._config.llm_provider,
            skill_registry=self._config.skill_registry,
            tool_registry=self._config.tool_registry,
            approval_handler=self._config.approval_handler,
        )

    async def run_agent(
        self,
        message: str,
        conversation_id: str = "",
        **kwargs: Any,
    ) -> AgentState:
        """异步主入口：处理用户消息并返回 AgentState。

        Args:
            message: 用户消息
            conversation_id: 对话 ID（多轮对话时复用）
            **kwargs: 传递给 create_agent_state 的额外参数

        Returns:
            处理后的 AgentState（stop_reason 已设置）
        """
        state = create_agent_state(message, conversation_id=conversation_id, **kwargs)
        state.max_steps = self._config.max_steps

        t0 = time.monotonic()
        try:
            result = await self._router.route(message, state)
        except Exception as e:
            logger.error("[AgentOrchestrator] run_agent error: %s", e)
            state.last_error = str(e)
            state.stop_reason = StopReason.ERROR
            result = state

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        result.add_trace("orchestrator_completed", {
            "elapsed_ms": elapsed_ms,
            "intent": result.intent,
            "stop_reason": result.stop_reason,
        })

        return result

    def run_agent_sync(self, message: str, **kwargs: Any) -> AgentState:
        """同步兼容入口（CLI / 旧代码使用）。

        使用 asyncio.run() 在独立事件循环中执行异步逻辑。
        适用于没有现有事件循环的同步上下文。
        """
        return asyncio.run(self.run_agent(message, **kwargs))
