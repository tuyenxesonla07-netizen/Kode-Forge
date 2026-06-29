"""Tests for Workflow engine - extended coverage (async, nodes, edge cases)."""

import asyncio
import pytest

from tools.workflow.engine import (
    WorkflowEngine,
    WorkflowResult,
    ExecutionLog,
)
from tools.workflow.nodes import (
    WorkflowNode,
    NodeType,
    LLMNode,
    RAGNode,
    ToolNode,
    CodeNode,
    BranchNode,
)


def _run(coro):
    """Run a coroutine synchronously, safe in any context."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# LLMNode
# ---------------------------------------------------------------------------

class TestLLMNode:
    def test_without_provider(self):
        node = LLMNode(prompt_template="Hello {{input}}")
        result = _run(node.execute({"input": "world"}))
        assert "Hello world" in result

    def test_placeholder_replacement(self):
        node = LLMNode(prompt_template="{{greeting}}, {{name}}!")
        result = _run(node.execute({"greeting": "Hi", "name": "Alice"}))
        assert "Hi, Alice!" in result

    def test_missing_placeholder(self):
        node = LLMNode(prompt_template="Hello {{missing}}")
        result = _run(node.execute({}))
        assert "{{missing}}" in result or "missing" in result


# ---------------------------------------------------------------------------
# RAGNode
# ---------------------------------------------------------------------------

class TestRAGNode:
    def test_without_engine(self):
        node = RAGNode()
        result = _run(node.execute({"query": "test"}))
        assert result["sources"] == []

    def test_with_empty_query(self):
        node = RAGNode()
        result = _run(node.execute({"query": ""}))
        assert result["query"] == ""


# ---------------------------------------------------------------------------
# ToolNode
# ---------------------------------------------------------------------------

class TestToolNode:
    def test_without_registry(self):
        node = ToolNode()
        result = _run(node.execute({}))
        assert "error" in result

    def test_with_registry_call(self):
        class MockRegistry:
            async def call(self, tool_name, args):
                return f"Called {tool_name} with {args}"

        node = ToolNode(tool_registry=MockRegistry(), tool_name="search")
        result = _run(node.execute({"query": "test"}))
        assert result["result"] is not None
        assert result["tool"] == "search"

    def test_with_registry_error(self):
        class FailingRegistry:
            async def call(self, tool_name, args):
                raise RuntimeError("Tool failed")

        node = ToolNode(tool_registry=FailingRegistry(), tool_name="bad_tool")
        result = _run(node.execute({}))
        assert "error" in result


# ---------------------------------------------------------------------------
# CodeNode
# ---------------------------------------------------------------------------

class TestCodeNode:
    def test_basic_execution(self):
        node = CodeNode(code_template="result = 1 + 1")
        result = _run(node.execute({}))
        assert result["output"] == "2"

    def test_with_input_vars(self):
        node = CodeNode(code_template="result = {{x}} * 2")
        result = _run(node.execute({"x": 5}))
        assert result["output"] == "10"

    def test_execution_error(self):
        node = CodeNode(code_template="result = 1 / 0")
        result = _run(node.execute({}))
        assert "error" in result

    def test_empty_code(self):
        node = CodeNode(code_template="")
        result = _run(node.execute({}))
        assert "output" in result


# ---------------------------------------------------------------------------
# BranchNode
# ---------------------------------------------------------------------------

class TestBranchNode:
    def test_true_branch(self):
        node = BranchNode(
            condition="status == 'approved'",
            branches={"true": "next_step", "false": "reject_step"},
        )
        result = _run(node.execute({"status": "approved"}))
        assert result["branch"] == "true"
        assert result["target"] == "next_step"

    def test_false_branch(self):
        node = BranchNode(
            condition="score > 0.8",
            branches={"true": "pass", "false": "fail"},
        )
        result = _run(node.execute({"score": 0.5}))
        assert result["branch"] == "false"
        assert result["target"] == "fail"

    def test_condition_error_falls_to_false(self):
        node = BranchNode(
            condition="undefined_var > 0",
            branches={"true": "a", "false": "b"},
        )
        result = _run(node.execute({}))
        assert result["branch"] == "false"

    def test_default_branches(self):
        node = BranchNode(condition="True")
        result = _run(node.execute({}))
        assert result["branch"] == "true"


# ---------------------------------------------------------------------------
# WorkflowEngine extended
# ---------------------------------------------------------------------------

class TestWorkflowEngineExtended:
    def test_load_workflow_no_edges(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "no-edges",
            "name": "No Edges",
            "nodes": [{"id": "n1", "type": "llm", "name": "N1", "config": {}}],
            "edges": [],
        })
        assert len(wf.edges) == 0

    def test_load_workflow_no_nodes(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "empty",
            "name": "Empty",
            "nodes": [],
            "edges": [],
        })
        assert len(wf.nodes) == 0

    def test_topological_sort_isolated_nodes(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "isolated",
            "name": "Isolated",
            "nodes": [
                {"id": "a", "type": "llm", "name": "A", "config": {}},
                {"id": "b", "type": "llm", "name": "B", "config": {}},
                {"id": "c", "type": "llm", "name": "C", "config": {}},
            ],
            "edges": [],
        })
        order = engine._topological_sort(wf)
        assert set(order) == {"a", "b", "c"}

    def test_topological_sort_diamond(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "diamond",
            "name": "Diamond",
            "nodes": [
                {"id": "root", "type": "llm", "name": "Root", "config": {}},
                {"id": "left", "type": "llm", "name": "Left", "config": {}},
                {"id": "right", "type": "llm", "name": "Right", "config": {}},
                {"id": "join", "type": "llm", "name": "Join", "config": {}},
            ],
            "edges": [
                {"from": "root", "to": "left"},
                {"from": "root", "to": "right"},
                {"from": "left", "to": "join"},
                {"from": "right", "to": "join"},
            ],
        })
        order = engine._topological_sort(wf)
        assert order[0] == "root"
        assert order[-1] == "join"
        assert order.index("left") < order.index("join")
        assert order.index("right") < order.index("join")

    @pytest.mark.asyncio
    async def test_execute_with_llm_node(self):
        engine = WorkflowEngine()
        engine.load_workflow({
            "id": "llm-test",
            "name": "LLM Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step 1", "config": {"prompt_template": "Hello"}},
            ],
            "edges": [],
        })
        run_id = await engine.execute_async("llm-test", {"input": "test"})
        await asyncio.sleep(0.3)
        result = engine.get_run_result(run_id)
        assert result is not None
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_execute_with_code_node(self):
        engine = WorkflowEngine()
        engine.load_workflow({
            "id": "code-test",
            "name": "Code Test",
            "nodes": [
                {"id": "n1", "type": "code", "name": "Step 1", "config": {"code": "result = 2 + 3"}},
            ],
            "edges": [],
        })
        run_id = await engine.execute_async("code-test", {})
        await asyncio.sleep(0.3)
        result = engine.get_run_result(run_id)
        assert result is not None
        assert result.status == "success"
        assert result.outputs.get("n1", {}).get("output") == "5"

    def test_list_runs(self):
        engine = WorkflowEngine()
        engine.load_workflow({
            "id": "test",
            "name": "Test",
            "nodes": [{"id": "n1", "type": "llm", "name": "N1", "config": {}}],
            "edges": [],
        })
        runs = engine.list_runs("test")
        assert isinstance(runs, list)

    def test_get_run_result_missing(self):
        engine = WorkflowEngine()
        assert engine.get_run_result("nonexistent") is None


# ---------------------------------------------------------------------------
# WorkflowResult
# ---------------------------------------------------------------------------

class TestWorkflowResultExtended:
    def test_default_values(self):
        r = WorkflowResult(
            workflow_id="test",
            status="running",
            outputs={},
            execution_time_ms=0,
            logs=[],
        )
        assert r.started_at == ""
        assert r.finished_at == ""


# ---------------------------------------------------------------------------
# NodeType
# ---------------------------------------------------------------------------

class TestNodeType:
    def test_all_types(self):
        assert NodeType.LLM == "llm"
        assert NodeType.RAG == "rag"
        assert NodeType.TOOL == "tool"
        assert NodeType.CODE == "code"
        assert NodeType.BRANCH == "branch"
        assert NodeType.HUMAN == "human"
