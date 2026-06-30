# tests/langgraph_adapter/test_state.py

"""
Tests for tools.langgraph_adapter.state — LangGraphState, initial_state, reducers.

纯 Python 测试，无 LangGraph 依赖。
"""

import pytest

from tools.langgraph_adapter.state import (
    LangGraphState,
    initial_state,
    merge_node_outputs,
    append_errors,
)


class TestInitialState:

    def test_default_state(self):
        state = initial_state()
        assert state["node_outputs"] == {}
        assert state["current_phase"] == 0
        assert state["quality_passed"] is False
        assert state["fix_iterations"] == 0
        assert state["errors"] == []
        assert state["pending_human"] is None

    def test_with_overrides(self):
        state = initial_state(current_phase=2, quality_passed=True)
        assert state["current_phase"] == 2
        assert state["quality_passed"] is True
        # 未被覆盖的字段保持默认值
        assert state["node_outputs"] == {}
        assert state["fix_iterations"] == 0

    def test_with_node_outputs(self):
        outputs = {"auth": "generated code", "db": "schema"}
        state = initial_state(node_outputs=outputs)
        assert state["node_outputs"] == outputs

    def test_with_errors(self):
        state = initial_state(errors=["error1", "error2"])
        assert len(state["errors"]) == 2

    def test_with_pending_human(self):
        pending = {"node_id": "deploy", "prompt": "确认部署？", "risk_level": "high"}
        state = initial_state(pending_human=pending)
        assert state["pending_human"] == pending


class TestMergeNodeOutputs:

    def test_merge_empty(self):
        result = merge_node_outputs({}, {"a": 1})
        assert result == {"a": 1}

    def test_merge_no_conflict(self):
        result = merge_node_outputs({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_merge_with_conflict(self):
        """冲突时新值覆盖旧值。"""
        result = merge_node_outputs({"a": 1, "b": 2}, {"b": 99, "c": 3})
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_merge_does_not_mutate_existing(self):
        existing = {"a": 1}
        result = merge_node_outputs(existing, {"b": 2})
        assert existing == {"a": 1}  # 原字典不变

    def test_merge_nested(self):
        result = merge_node_outputs(
            {"module": {"status": "pending"}},
            {"module": {"status": "done", "output": "code"}},
        )
        assert result["module"]["status"] == "done"


class TestAppendErrors:

    def test_append_single_error(self):
        result = append_errors(["existing"], "new error")
        assert result == ["existing", "new error"]

    def test_append_multiple_errors(self):
        result = append_errors(["e1"], ["e2", "e3"])
        assert result == ["e1", "e2", "e3"]

    def test_append_to_empty(self):
        result = append_errors([], "first error")
        assert result == ["first error"]

    def test_does_not_mutate_existing(self):
        existing = ["error1"]
        result = append_errors(existing, "error2")
        assert existing == ["error1"]  # 原列表不变
        assert result == ["error1", "error2"]
