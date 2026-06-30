# agents/runtime/loop.py

"""
ReActLoop — Agent 主循环（plan → act → observe）。

借鉴 customer-service-course 的 AgentLoop + refund-agent 的 v10 循环模式。
内置工具为 stub 实现（P1 完善），插件工具通过 PluginToolRegistry 动态调用。

用法:
    from agents.runtime.loop import ReActLoop, ReActLoopConfig
    from agents.runtime.state import create_agent_state

    loop = ReActLoop(llm_provider=mock_provider)
    state = create_agent_state("帮我构建用户登录模块")
    result_state = await loop.run(state)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from agents.runtime.state import AgentState, StopReason
from agents.runtime._tool_context import ToolContextWrapper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config & Step Record
# ---------------------------------------------------------------------------

@dataclass
class ReActLoopConfig:
    """ReActLoop 配置。"""
    max_steps: int = 10
    system_prompt: str = (
        "你是一个代码生成流水线助手。根据用户需求，选择合适的工具完成任务。\n"
        "可用工具：compile_pipeline, run_quality_check, search_kb, "
        "request_approval, generate_code, fix_code"
    )
    output_format: str = "text"    # "text" | "json"


@dataclass
class ReActStep:
    """单次 ReAct 循环记录。"""
    step_number: int
    thought: str
    action: str                    # tool_name 或 "respond"
    action_input: dict
    observation: str
    success: bool


# ---------------------------------------------------------------------------
# ReActLoop
# ---------------------------------------------------------------------------

class ReActLoop:
    """Agent 主循环 — plan → act → observe → check。"""

    # 内置工具集合（stub 实现）
    BUILTIN_TOOLS: dict[str, str] = {
        "compile_pipeline": "_tool_compile_pipeline",
        "run_quality_check": "_tool_run_quality_check",
        "search_kb": "_tool_search_kb",
        "request_approval": "_tool_request_approval",
        "generate_code": "_tool_generate_code",
        "fix_code": "_tool_fix_code",
    }

    def __init__(
        self,
        llm_provider: Any = None,
        skill_registry: Any = None,
        tool_registry: Any = None,
        approval_handler: Any = None,
        skill_workflow_runner: Any = None,
        config: ReActLoopConfig | None = None,
    ) -> None:
        self._llm = llm_provider
        self._skill_registry = skill_registry
        self._tool_registry = tool_registry
        self._approval_handler = approval_handler
        self._workflow_runner = skill_workflow_runner
        self._config = config or ReActLoopConfig()
        self._steps: list[ReActStep] = []

    @property
    def steps(self) -> list[ReActStep]:
        """返回已执行的步骤记录。"""
        return list(self._steps)

    # -------------------------------------------------------------------
    # Main Loop
    # -------------------------------------------------------------------

    async def run(self, state: AgentState) -> AgentState:
        """主循环：plan → act → observe → check，直到 stop_reason 被设置。

        Args:
            state: 初始 AgentState（应包含用户消息）

        Returns:
            执行完毕的 AgentState（stop_reason 已设置）
        """
        state.max_steps = self._config.max_steps
        self._steps = []

        # 注入 AgentState 到 plugin tool context
        if self._tool_registry is not None:
            self._tool_registry = ToolContextWrapper(self._tool_registry, state)

        # 如果 state 已经有 intent，记录到 trace
        if state.intent:
            state.add_trace("intent_detected", {"intent": state.intent})

        while not state.should_stop():
            # 检查步数限制
            if state.check_max_steps():
                state.add_trace("max_steps_reached", {"step": state.step_count})
                break

            state.increment_step()

            # 1. Build prompt
            system, user = self._build_prompt(state)

            # 2. LLM think
            try:
                llm_output = await self._llm_think(system, user)
            except Exception as e:
                state.last_error = str(e)
                state.stop_reason = StopReason.ERROR
                state.add_trace("llm_error", {"error": str(e)})
                break

            # 3. Parse action
            action, action_input = self._parse_action(llm_output)

            # 4. Execute tool
            result, success = await self._execute_tool(action, action_input, state)

            # 5. Record step
            step = ReActStep(
                step_number=state.step_count,
                thought=llm_output[:200],
                action=action,
                action_input=action_input,
                observation=str(result)[:500],
                success=success,
            )
            self._steps.append(step)
            state.add_trace("step_completed", {
                "step": step.step_number,
                "action": action,
                "success": success,
            })

            # 6. Check termination
            self._check_termination(state)

        return state

    # -------------------------------------------------------------------
    # Prompt Building
    # -------------------------------------------------------------------

    def _build_prompt(self, state: AgentState) -> tuple[str, str]:
        """构建 (system_prompt, user_prompt)。"""
        system = self._config.system_prompt

        # 构建用户 prompt（包含对话历史和当前上下文）
        parts = []

        # 最近的对话历史（最多5条）
        recent_history = state.history[-5:] if state.history else []
        if recent_history:
            parts.append("## 对话历史")
            for msg in recent_history:
                parts.append(f"[{msg.role}] {msg.content}")
            parts.append("")

        # 工具调用历史
        if state.tool_history:
            parts.append("## 最近工具调用")
            for record in state.tool_history[-3:]:
                status = "成功" if record.success else "失败"
                parts.append(f"- {record.tool_name}: {status}")
            parts.append("")

        # 当前用户消息
        parts.append(f"## 当前请求\n{state.message}")

        user = "\n".join(parts)
        return system, user

    # -------------------------------------------------------------------
    # LLM Call
    # -------------------------------------------------------------------

    async def _llm_think(self, system: str, user: str) -> str:
        """调用 LLM 获取下一步思考。"""
        if self._llm is None:
            # 无 LLM 时返回默认动作
            return "Action: respond\nInput: 我需要更多信息来完成任务。"

        # 支持 async complete 和同步 complete
        if hasattr(self._llm, "acomplete"):
            response = await self._llm.acomplete(
                prompt=user,
                system_prompt=system,
                output_format=self._config.output_format,
            )
        else:
            response = self._llm.complete(
                prompt=user,
                system_prompt=system,
                output_format=self._config.output_format,
            )

        if hasattr(response, "content"):
            return response.content
        return str(response)

    # -------------------------------------------------------------------
    # Action Parsing
    # -------------------------------------------------------------------

    # 正则：匹配 "Action: tool_name" 和 "Input: {...}"
    _ACTION_RE = re.compile(r"Action:\s*(\w+)", re.IGNORECASE)
    _INPUT_RE = re.compile(r"Input:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)

    def _parse_action(self, llm_output: str) -> tuple[str, dict]:
        """解析 LLM 输出为 (action_name, action_input)。

        支持格式：
            Action: tool_name
            Input: {"key": "value"}

        或简化格式：
            Action: respond
            Input: 直接回复内容
        """
        if not llm_output:
            return "respond", {"content": "无输出"}

        action_match = self._ACTION_RE.search(llm_output)
        action = action_match.group(1).lower() if action_match else "respond"

        input_match = self._INPUT_RE.search(llm_output)
        input_str = input_match.group(1).strip() if input_match else ""

        # 尝试解析 JSON input
        action_input: dict = {}
        if input_str:
            try:
                action_input = json.loads(input_str)
            except json.JSONDecodeError:
                # 非 JSON 时作为 content 字段
                action_input = {"content": input_str}

        return action, action_input

    # -------------------------------------------------------------------
    # Tool Execution
    # -------------------------------------------------------------------

    async def _execute_tool(self, name: str, args: dict, state: AgentState) -> tuple[Any, bool]:
        """执行工具，返回 (result, success)。"""
        # 内置工具
        if name in self.BUILTIN_TOOLS:
            handler_name = self.BUILTIN_TOOLS[name]
            handler: Callable = getattr(self, handler_name)
            try:
                result = handler(args, state)
                # 支持 async handler
                if hasattr(result, "__await__"):
                    result = await result
                state.add_tool_record(name, args, result, True)
                return result, True
            except Exception as e:
                state.add_tool_record(name, args, str(e), False)
                logger.error("[ReActLoop] Built-in tool '%s' error: %s", name, e)
                return {"error": str(e)}, False

        # respond — 直接设置回复
        if name == "respond":
            content = args.get("content", "")
            state.reply = content
            state.stop_reason = StopReason.ANSWERED
            return {"reply": content}, True

        # 插件工具
        if self._tool_registry is not None:
            try:
                result = self._tool_registry.call(name, context={}, params=args)
                success = result.get("success", False)
                state.add_tool_record(name, args, result, success)
                return result, success
            except KeyError:
                pass  # 工具不存在，继续

        # 未知工具
        logger.warning("[ReActLoop] Unknown tool: %s", name)
        return {"error": f"Unknown tool: {name}"}, False

    # -------------------------------------------------------------------
    # Termination Check
    # -------------------------------------------------------------------

    def _check_termination(self, state: AgentState) -> None:
        """检查并设置 stop_reason。"""
        if state.should_stop():
            return

        # 如果有回复内容，标记为 answered
        if state.reply:
            state.stop_reason = StopReason.ANSWERED
            return

        # 如果最后一步是 respond 动作但未设置 stop_reason
        if self._steps and self._steps[-1].action == "respond":
            state.stop_reason = StopReason.ANSWERED

    # -------------------------------------------------------------------
    # Built-in Tools (stub implementations — P1 will wire to real subsystems)
    # -------------------------------------------------------------------

    def _tool_compile_pipeline(self, args: dict, state: AgentState) -> dict:
        """编译流水线（stub）。"""
        return {
            "status": "compiled",
            "message": f"Pipeline compiled for: {state.message}",
            "modules": args.get("modules", ["default_module"]),
        }

    def _tool_run_quality_check(self, args: dict, state: AgentState) -> dict:
        """运行质量门禁（stub）。"""
        return {
            "status": "passed",
            "score": 0.85,
            "issues": [],
        }

    def _tool_search_kb(self, args: dict, state: AgentState) -> dict:
        """知识库检索（stub）。"""
        query = args.get("query", args.get("content", state.message))
        return {
            "results": [
                {"id": "kb-001", "content": f"Knowledge about: {query}", "score": 0.9},
            ],
            "query": query,
        }

    def _tool_request_approval(self, args: dict, state: AgentState) -> dict:
        """请求人工审批（stub）。"""
        approval_id = str(uuid.uuid4())
        state.pending_approval = {
            "approval_id": approval_id,
            "tool_name": args.get("tool_name", "unknown"),
            "args": args,
            "status": "pending",
        }
        state.stop_reason = StopReason.WAITING_HUMAN
        return {
            "approval_id": approval_id,
            "status": "pending",
            "message": "等待人工审批",
        }

    def _tool_generate_code(self, args: dict, state: AgentState) -> dict:
        """生成代码（stub）。"""
        module_name = args.get("module_name", "unnamed")
        return {
            "status": "generated",
            "module": module_name,
            "code": f"# Generated code for {module_name}\ndef main():\n    pass",
        }

    def _tool_fix_code(self, args: dict, state: AgentState) -> dict:
        """修复代码（stub）。"""
        return {
            "status": "fixed",
            "issues_found": args.get("issues", []),
            "fixes_applied": 1,
        }
