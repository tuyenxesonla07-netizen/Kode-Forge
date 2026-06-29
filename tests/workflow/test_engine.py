"""Tests for Workflow engine."""

import asyncio
import pytest

from tools.workflow.engine import (
    WorkflowEngine,
    Workflow,
    WorkflowResult,
    ExecutionLog,
)
from tools.workflow.nodes import (
    WorkflowNode,
    NodeType,
    LLMNode,
    CodeNode,
)


# ---------------------------------------------------------------------------
# Workflow loading
# ---------------------------------------------------------------------------

class TestWorkflowEngine:
    def test_load_workflow(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "test-001",
            "name": "Test Workflow",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step 1", "config": {"prompt_template": "Hello"}},
                {"id": "n2", "type": "code", "name": "Step 2", "config": {"code": "print('hi')"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
        })
        assert wf.id == "test-001"
        assert len(wf.nodes) == 2
        assert "n2" in wf.edges.get("n1", [])

    def test_get_workflow(self):
        engine = WorkflowEngine()
        engine.load_workflow({"id": "wf-1", "name": "Test", "nodes": [], "edges": []})
        wf = engine.get_workflow("wf-1")
        assert wf is not None
        assert wf.name == "Test"

    def test_get_workflow_missing(self):
        engine = WorkflowEngine()
        assert engine.get_workflow("nonexistent") is None

    def test_list_workflows(self):
        engine = WorkflowEngine()
        engine.load_workflow({"id": "wf-1", "name": "First", "nodes": [], "edges": []})
        engine.load_workflow({"id": "wf-2", "name": "Second", "nodes": [], "edges": []})
        workflows = engine.list_workflows()
        assert len(workflows) == 2

    def test_workflow_with_metadata(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "test",
            "name": "Test",
            "nodes": [],
            "edges": [],
            "metadata": {"version": "1.0"},
        })
        assert wf.metadata["version"] == "1.0"


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def test_linear_chain(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "linear",
            "name": "Linear",
            "nodes": [
                {"id": "a", "type": "llm", "name": "A", "config": {}},
                {"id": "b", "type": "llm", "name": "B", "config": {}},
                {"id": "c", "type": "llm", "name": "C", "config": {}},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        })
        order = engine._topological_sort(wf)
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_parallel_nodes(self):
        engine = WorkflowEngine()
        wf = engine.load_workflow({
            "id": "parallel",
            "name": "Parallel",
            "nodes": [
                {"id": "root", "type": "llm", "name": "Root", "config": {}},
                {"id": "p1", "type": "llm", "name": "P1", "config": {}},
                {"id": "p2", "type": "llm", "name": "P2", "config": {}},
            ],
            "edges": [{"from": "root", "to": "p1"}, {"from": "root", "to": "p2"}],
        })
        order = engine._topological_sort(wf)
        assert order[0] == "root"
        assert "p1" in order
        assert "p2" in order


# ---------------------------------------------------------------------------
# Async execution (requires asyncio)
# ---------------------------------------------------------------------------

class TestAsyncExecution:
    @pytest.mark.asyncio
    async def test_execute_linear_workflow(self):
        engine = WorkflowEngine()
        engine.load_workflow({
            "id": "exec-test",
            "name": "Exec Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step 1", "config": {"prompt_template": "Hello"}},
                ],
            "edges": [],
        })
        run_id = await engine.execute_async("exec-test", {"input": "test"})
        assert run_id is not None
        # Wait for async completion
        await asyncio.sleep(0.5)
        result = engine.get_run_result(run_id)
        assert result is not None
        assert result.status == "success"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class TestWorkflowResult:
    def test_creation(self):
        result = WorkflowResult(
            workflow_id="test",
            status="running",
            outputs={},
            execution_time_ms=0,
            logs=[],
        )
        assert result.status == "running"


class TestExecutionLog:
    def test_creation(self):
        log = ExecutionLog(
            node_id="n1",
            status="success",
            output="done",
            duration_ms=100,
            timestamp="2024-01-01T00:00:00",
        )
        assert log.status == "success"
        assert log.duration_ms == 100


# ---------------------------------------------------------------------------
# WorkflowNode
# ---------------------------------------------------------------------------

class TestWorkflowNode:
    def test_creation(self):
        node = WorkflowNode(
            id="n1",
            type=NodeType.LLM,
            name="Test Node",
            config={"prompt_template": "Hello {{input}}"},
        )
        assert node.id == "n1"
        assert node.type == NodeType.LLM


# ---------------------------------------------------------------------------
# LLMNode
# ---------------------------------------------------------------------------

class TestLLMNode:
    def test_creation(self):
        node = LLMNode(prompt_template="Hello {{input}}")
        assert node.prompt_template == "Hello {{input}}"


# ---------------------------------------------------------------------------
# CodeNode
# ---------------------------------------------------------------------------

class TestCodeNode:
    def test_creation(self):
        node = CodeNode(code_template="print('hello')")
        assert node.code_template == "print('hello')"
