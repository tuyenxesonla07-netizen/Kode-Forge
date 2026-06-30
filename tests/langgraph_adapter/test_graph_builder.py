# tests/langgraph_adapter/test_graph_builder.py

"""
Tests for tools.langgraph_adapter.graph_builder — LangGraphBackend.

NOTE: These tests require langgraph to be installed.
If langgraph is not available, all tests are skipped.
"""

import pytest

# Skip entire module if langgraph not installed
langgraph = pytest.importorskip("langgraph")

from tools.langgraph_adapter.graph_builder import LangGraphBackend
from tools.langgraph_adapter.state import initial_state
from tools.workflow.engine import Workflow
from tools.workflow.nodes import WorkflowNode, NodeType


class TestLangGraphBackendInit:

    def test_init_with_defaults(self):
        backend = LangGraphBackend()
        assert backend._llm_provider is None
        assert backend._max_fix_iterations == 3

    def test_init_with_custom_params(self):
        backend = LangGraphBackend(max_fix_iterations=5, interrupt_before=["deploy"])
        assert backend._max_fix_iterations == 5
        assert backend._interrupt_before == ["deploy"]


class TestLangGraphBackendBuild:

    def _make_simple_workflow(self) -> Workflow:
        nodes = {
            "step_a": WorkflowNode(
                id="step_a",
                type=NodeType.LLM,
                config={"prompt_template": "Do step A"},
            ),
            "step_b": WorkflowNode(
                id="step_b",
                type=NodeType.LLM,
                inputs=["step_a"],
                config={"prompt_template": "Do step B"},
            ),
        }
        edges = {
            "step_a": ["step_b"],
        }
        return Workflow(id="test", name="Test", nodes=nodes, edges=edges)

    def test_build_returns_compiled_graph(self):
        backend = LangGraphBackend()
        workflow = self._make_simple_workflow()
        graph = backend.build(workflow)
        assert graph is not None

    def test_build_with_interrupt_before(self):
        backend = LangGraphBackend(interrupt_before=["step_b"])
        workflow = self._make_simple_workflow()
        graph = backend.build(workflow)
        assert graph is not None

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self):
        backend = LangGraphBackend()
        workflow = self._make_simple_workflow()
        graph = backend.build(workflow)
        result = await backend.execute(graph, {"query": "test"})
        assert "node_outputs" in result
        assert "step_a" in result["node_outputs"]
        assert "step_b" in result["node_outputs"]

    @pytest.mark.asyncio
    async def test_execute_with_initial_state(self):
        backend = LangGraphBackend()
        workflow = self._make_simple_workflow()
        graph = backend.build(workflow)
        result = await backend.execute(graph, initial_state(current_phase=1))
        assert result["current_phase"] == 1
