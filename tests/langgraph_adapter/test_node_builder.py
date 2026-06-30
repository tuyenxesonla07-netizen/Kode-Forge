# tests/langgraph_adapter/test_node_builder.py

"""
Tests for tools.langgraph_adapter.node_builder — build_node_fn, node functions.

纯 Python 测试，不依赖 LangGraph。
"""

import asyncio
import pytest

from tools.workflow.nodes import (
    WorkflowNode,
    NodeType,
    HumanNode,
)
from tools.langgraph_adapter.node_builder import build_node_fn
from tools.langgraph_adapter.state import initial_state


class TestBuildNodeFn:

    def test_build_llm_node(self):
        node = WorkflowNode(
            id="auth_llm",
            type=NodeType.LLM,
            config={"prompt_template": "Generate {{module}} code"},
        )
        fn = build_node_fn(node)
        assert callable(fn)
        assert fn.__name__ == "llm_node_auth_llm"

    def test_build_rag_node(self):
        node = WorkflowNode(
            id="knowledge_search",
            type=NodeType.RAG,
            config={"top_k": 3},
        )
        fn = build_node_fn(node)
        assert callable(fn)
        assert fn.__name__ == "rag_node_knowledge_search"

    def test_build_tool_node(self):
        node = WorkflowNode(
            id="deploy",
            type=NodeType.TOOL,
            config={"tool_name": "deploy_service"},
        )
        fn = build_node_fn(node)
        assert callable(fn)

    def test_build_code_node(self):
        node = WorkflowNode(
            id="calc",
            type=NodeType.CODE,
            config={"code_template": "result = 1 + 1"},
        )
        fn = build_node_fn(node)
        assert callable(fn)

    def test_build_branch_node(self):
        node = WorkflowNode(
            id="check_quality",
            type=NodeType.BRANCH,
            config={"condition": "quality_passed", "branches": {"true": "next", "false": "fix"}},
        )
        fn = build_node_fn(node)
        assert callable(fn)

    def test_build_human_node(self):
        node = WorkflowNode(
            id="approval",
            type=NodeType.HUMAN,
            config={"prompt": "确认部署？", "risk_level": "high"},
        )
        fn = build_node_fn(node)
        assert callable(fn)

    def test_unknown_node_type_raises(self):
        with pytest.raises(ValueError, match="Unknown node type"):
            # 使用不存在的类型
            node = WorkflowNode(id="bad", type="unknown_type")  # type: ignore[arg-type]
            build_node_fn(node)


class TestLLMNodeFn:

    @pytest.mark.asyncio
    async def test_llm_node_without_provider(self):
        node = WorkflowNode(
            id="test_llm",
            type=NodeType.LLM,
            config={"prompt_template": "Hello {{name}}"},
        )
        fn = build_node_fn(node, llm_provider=None)
        state = initial_state(node_outputs={"input": {"name": "World"}})
        result = await fn(state)
        assert "test_llm" in result
        assert "Hello" in result["test_llm"]

    @pytest.mark.asyncio
    async def test_llm_node_uses_inputs(self):
        """节点通过 inputs 声明从上游 node_outputs 获取数据，key 是上游节点 ID。"""
        node = WorkflowNode(
            id="greet",
            type=NodeType.LLM,
            inputs=["input"],
            config={"prompt_template": "Process {{input}}"},
        )
        fn = build_node_fn(node)
        state = initial_state(node_outputs={"input": "test_data"})
        result = await fn(state)
        assert "test_data" in result["greet"]


class TestCodeNodeFn:

    @pytest.mark.asyncio
    async def test_code_node_executes(self):
        node = WorkflowNode(
            id="calc",
            type=NodeType.CODE,
            config={"code_template": "result = 2 + 3"},
        )
        fn = build_node_fn(node)
        state = initial_state()
        result = await fn(state)
        assert "calc" in result
        assert "5" in result["calc"]["output"]

    @pytest.mark.asyncio
    async def test_code_node_handles_error(self):
        node = WorkflowNode(
            id="bad_code",
            type=NodeType.CODE,
            config={"code_template": "raise ValueError('test error')"},
        )
        fn = build_node_fn(node)
        state = initial_state()
        result = await fn(state)
        assert "error" in result["bad_code"]


class TestBranchNodeFn:

    @pytest.mark.asyncio
    async def test_branch_true(self):
        node = WorkflowNode(
            id="check",
            type=NodeType.BRANCH,
            config={
                "condition": "quality_passed",
                "branches": {"true": "next_step", "false": "fix_step"},
            },
        )
        fn = build_node_fn(node)
        state = initial_state(quality_passed=True)
        result = await fn(state)
        assert result["check"]["branch"] == "true"
        assert result["check"]["target"] == "next_step"

    @pytest.mark.asyncio
    async def test_branch_false(self):
        node = WorkflowNode(
            id="check",
            type=NodeType.BRANCH,
            config={
                "condition": "quality_passed",
                "branches": {"true": "next_step", "false": "fix_step"},
            },
        )
        fn = build_node_fn(node)
        state = initial_state(quality_passed=False)
        result = await fn(state)
        assert result["check"]["branch"] == "false"
        assert result["check"]["target"] == "fix_step"


class TestHumanNodeFn:

    @pytest.mark.asyncio
    async def test_human_node_sets_pending(self):
        node = WorkflowNode(
            id="deploy_approval",
            type=NodeType.HUMAN,
            config={"prompt": "确认部署到生产环境？", "risk_level": "high"},
        )
        fn = build_node_fn(node)
        state = initial_state()
        result = await fn(state)
        assert "deploy_approval" in result
        assert result["pending_human"]["prompt"] == "确认部署到生产环境？"
        assert result["pending_human"]["risk_level"] == "high"

    @pytest.mark.asyncio
    async def test_human_node_no_inputs(self):
        node = WorkflowNode(
            id="simple_approval",
            type=NodeType.HUMAN,
            config={"prompt": "确认继续？"},
        )
        fn = build_node_fn(node)
        state = initial_state()
        result = await fn(state)
        assert result["pending_human"] is not None
