# tests/runtime/test_loop.py

"""
tests/runtime/test_loop.py — ReActLoop 单元测试。

覆盖：初始化、max_steps 限制、动作解析、工具调用、终止条件。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from agents.runtime.loop import ReActLoop, ReActLoopConfig, ReActStep
from agents.runtime.state import AgentState, StopReason, create_agent_state


# ---------------------------------------------------------------------------
# Mock LLM Provider
# ---------------------------------------------------------------------------

@dataclass
class MockLLMResponse:
    """Mock LLM 响应。"""
    content: str
    success: bool = True


class MockLLMProvider:
    """Mock LLM Provider — 用于测试 ReActLoop。"""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or []
        self._call_count = 0

    def complete(self, prompt: str, system_prompt: str = "",
                 output_format: str = "text", **kwargs: Any) -> MockLLMResponse:
        if self._call_count < len(self._responses):
            content = self._responses[self._call_count]
        else:
            content = "Action: respond\nInput: 任务完成"
        self._call_count += 1
        return MockLLMResponse(content=content)

    @property
    def call_count(self) -> int:
        return self._call_count


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------

class TestReActLoopInit:
    def test_react_loop_init_defaults(self):
        """默认初始化。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        assert loop._config.max_steps == 10
        assert loop._llm is not None
        assert loop.steps == []

    def test_react_loop_config(self):
        """自定义配置。"""
        config = ReActLoopConfig(max_steps=5, system_prompt="Custom prompt")
        loop = ReActLoop(llm_provider=MockLLMProvider(), config=config)
        assert loop._config.max_steps == 5
        assert loop._config.system_prompt == "Custom prompt"


# ---------------------------------------------------------------------------
# Tests: Action Parsing
# ---------------------------------------------------------------------------

class TestParseAction:
    def test_parse_action_respond(self):
        """解析 respond 动作。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        action, args = loop._parse_action("Action: respond\nInput: Hello!")
        assert action == "respond"
        assert args == {"content": "Hello!"}

    def test_parse_action_tool_call(self):
        """解析工具调用动作。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        action, args = loop._parse_action(
            'Action: search_kb\nInput: {"query": "auth module"}'
        )
        assert action == "search_kb"
        assert args == {"query": "auth module"}

    def test_parse_action_no_action_keyword(self):
        """无 Action 关键词时默认为 respond。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        action, args = loop._parse_action("Some random text")
        assert action == "respond"

    def test_parse_action_empty_input(self):
        """空输入时返回默认 content。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        action, args = loop._parse_action("")
        assert action == "respond"
        assert args == {"content": "无输出"}


# ---------------------------------------------------------------------------
# Tests: Built-in Tools
# ---------------------------------------------------------------------------

class TestBuiltinTools:
    def test_tool_compile_pipeline(self):
        """compile_pipeline 工具 stub 返回编译结果。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("build auth module")
        result = loop._tool_compile_pipeline({}, state)
        assert result["status"] == "compiled"

    def test_tool_run_quality_check(self):
        """run_quality_check 工具 stub 返回质量结果。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        result = loop._tool_run_quality_check({}, state)
        assert result["status"] == "passed"
        assert "score" in result

    def test_tool_search_kb(self):
        """search_kb 工具 stub 返回检索结果。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        result = loop._tool_search_kb({"query": "auth module"}, state)
        assert len(result["results"]) > 0
        assert result["query"] == "auth module"

    def test_tool_search_kb_uses_state_message(self):
        """search_kb 无 query 时使用 state.message。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("user login")
        result = loop._tool_search_kb({}, state)
        assert result["query"] == "user login"

    def test_tool_request_approval(self):
        """request_approval 工具设置 pending_approval 并停止。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        result = loop._tool_request_approval({"tool_name": "write_file"}, state)
        assert result["status"] == "pending"
        assert state.stop_reason == StopReason.WAITING_HUMAN
        assert state.pending_approval is not None

    def test_tool_generate_code(self):
        """generate_code 工具 stub 返回代码。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        result = loop._tool_generate_code({"module_name": "auth"}, state)
        assert result["status"] == "generated"
        assert "code" in result

    def test_tool_fix_code(self):
        """fix_code 工具 stub 返回修复结果。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        result = loop._tool_fix_code({"issues": ["bug1"]}, state)
        assert result["status"] == "fixed"


# ---------------------------------------------------------------------------
# Tests: Max Steps Guard
# ---------------------------------------------------------------------------

class TestMaxStepsGuard:
    @pytest.mark.asyncio
    async def test_react_loop_max_steps_guard(self):
        """超过 max_steps 时循环终止。"""
        # LLM 永远返回需要继续的动作
        mock_llm = MockLLMProvider(
            responses=["Action: search_kb\nInput: {\"query\": \"test\"}"] * 20
        )
        config = ReActLoopConfig(max_steps=3)
        loop = ReActLoop(llm_provider=mock_llm, config=config)
        state = create_agent_state("test")

        result = await loop.run(state)

        assert result.stop_reason == StopReason.MAX_STEPS
        assert result.step_count == 3

    @pytest.mark.asyncio
    async def test_react_loop_stops_on_respond(self):
        """LLM 返回 respond 动作时立即停止。"""
        mock_llm = MockLLMProvider(
            responses=["Action: respond\nInput: 已完成任务"]
        )
        loop = ReActLoop(llm_provider=mock_llm)
        state = create_agent_state("test")

        result = await loop.run(state)

        assert result.stop_reason == StopReason.ANSWERED
        assert result.reply == "已完成任务"


# ---------------------------------------------------------------------------
# Tests: Termination
# ---------------------------------------------------------------------------

class TestTermination:
    def test_check_termination_answered(self):
        """有回复内容时标记为 answered。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        state.reply = "Here is the answer"
        loop._check_termination(state)
        assert state.stop_reason == StopReason.ANSWERED

    def test_check_termination_no_reply(self):
        """无回复时不设置 stop_reason。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        loop._check_termination(state)
        assert state.stop_reason == StopReason.NONE

    def test_check_termination_already_stopped(self):
        """已停止时不覆盖 stop_reason。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        state.stop_reason = StopReason.ERROR
        loop._check_termination(state)
        assert state.stop_reason == StopReason.ERROR


# ---------------------------------------------------------------------------
# Tests: Step Recording
# ---------------------------------------------------------------------------

class TestStepRecording:
    @pytest.mark.asyncio
    async def test_steps_recorded(self):
        """执行步骤被记录。"""
        mock_llm = MockLLMProvider(
            responses=["Action: respond\nInput: done"]
        )
        loop = ReActLoop(llm_provider=mock_llm)
        state = create_agent_state("test")

        await loop.run(state)

        assert len(loop.steps) >= 1
        assert loop.steps[0].action == "respond"

    @pytest.mark.asyncio
    async def test_tool_history_recorded(self):
        """工具调用记录写入 state.tool_history。"""
        mock_llm = MockLLMProvider(
            responses=["Action: search_kb\nInput: {\"query\": \"auth\"}"]
        )
        # 第二步返回 respond 以终止循环
        mock_llm._responses.append("Action: respond\nInput: done")

        loop = ReActLoop(llm_provider=mock_llm, config=ReActLoopConfig(max_steps=5))
        state = create_agent_state("test")

        await loop.run(state)

        # 应该有 search_kb 的工具记录
        tool_names = [r.tool_name for r in state.tool_history]
        assert "search_kb" in tool_names


# ---------------------------------------------------------------------------
# Tests: Unknown Tool
# ---------------------------------------------------------------------------

class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        """未知工具名返回失败结果。"""
        loop = ReActLoop(llm_provider=MockLLMProvider())
        state = create_agent_state("test")
        result, success = await loop._execute_tool("nonexistent_tool", {}, state)
        assert success is False
        assert "Unknown tool" in result["error"]


# ---------------------------------------------------------------------------
# Tests: Plugin Tool Registry Integration
# ---------------------------------------------------------------------------

class TestPluginToolIntegration:
    @pytest.mark.asyncio
    async def test_execute_plugin_tool(self):
        """插件工具通过 PluginToolRegistry 调用。"""
        from tools.plugins.tool_registry import PluginToolRegistry

        # 使用 fixture 目录加载工具（相对于 tests/plugins/fixtures）
        fixtures_dir = __import__("pathlib").Path(__file__).parent.parent / "plugins" / "fixtures"

        tool_registry = PluginToolRegistry(plugins_dir=fixtures_dir)
        tool_registry.load()

        mock_llm = MockLLMProvider(
            responses=["Action: ast_validator\nInput: {\"code\": \"x = 1\"}"]
        )
        mock_llm._responses.append("Action: respond\nInput: done")

        loop = ReActLoop(llm_provider=mock_llm, tool_registry=tool_registry,
                         config=ReActLoopConfig(max_steps=5))
        state = create_agent_state("validate code")

        await loop.run(state)

        # 验证插件工具被调用
        tool_names = [r.tool_name for r in state.tool_history]
        assert "ast_validator" in tool_names
