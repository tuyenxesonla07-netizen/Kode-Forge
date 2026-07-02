# tests/langgraph_adapter/test_quality_loop.py

"""
Tests for tools.langgraph_adapter.quality_loop — quality condition functions.

纯 Python 测试，无 LangGraph 依赖。
"""

import pytest

from tools.langgraph_adapter.quality_loop import (
    make_quality_condition_fn,
    _extract_metric,
    _evaluate_condition,
    make_fix_iteration_updater,
)
from tools.langgraph_adapter.state import initial_state


class TestMakeQualityConditionFn:

    def test_pass_returns_next(self):
        gate = {"metric": "quality_passed", "operator": "==", "value": True}
        fn = make_quality_condition_fn(gate, next_node="module_b", fix_node="module_a")
        state = initial_state(node_outputs={"quality_passed": True})
        assert fn(state) == "module_b"

    def test_fail_with_fix_returns_fix(self):
        gate = {"metric": "quality_passed", "operator": "==", "value": True}
        fn = make_quality_condition_fn(gate, next_node="module_b", fix_node="module_a")
        state = initial_state(node_outputs={"quality_passed": False}, fix_iterations=0)
        assert fn(state) == "module_a"

    def test_fail_at_max_iterations_returns_end(self):
        gate = {"metric": "quality_passed", "operator": "==", "value": True}
        fn = make_quality_condition_fn(
            gate, next_node="module_b", fix_node="module_a", max_fix_iterations=3,
        )
        state = initial_state(node_outputs={"quality_passed": False}, fix_iterations=3)
        assert fn(state) == "__end__"

    def test_fail_with_no_fix_node_returns_end(self):
        gate = {"metric": "quality_passed", "operator": "==", "value": True}
        fn = make_quality_condition_fn(gate, next_node="module_b", fix_node=None)
        state = initial_state(node_outputs={"quality_passed": False})
        assert fn(state) == "__end__"

    def test_metric_from_nested_output(self):
        gate = {"metric": "auth.quality_score", "operator": ">=", "value": 80}
        fn = make_quality_condition_fn(gate, next_node="module_b", fix_node="module_a")
        state = initial_state(node_outputs={"auth": {"quality_score": 90}})
        assert fn(state) == "module_b"

    def test_metric_not_found_fails(self):
        gate = {"metric": "nonexistent_metric", "operator": "==", "value": True}
        fn = make_quality_condition_fn(gate, next_node="module_b", fix_node="module_a")
        state = initial_state()
        assert fn(state) == "module_a"  # metric 为 None，不等于 True，所以失败


class TestExtractMetric:

    def test_direct_key(self):
        outputs = {"quality_passed": True}
        assert _extract_metric(outputs, "quality_passed") is True

    def test_nested_key(self):
        outputs = {"auth": {"score": 95}}
        assert _extract_metric(outputs, "auth.score") == 95

    def test_missing_key(self):
        outputs = {"a": 1}
        assert _extract_metric(outputs, "b") is None

    def test_missing_nested_key(self):
        outputs = {"a": {"b": 1}}
        assert _extract_metric(outputs, "a.c") is None

    def test_empty_metric(self):
        assert _extract_metric({"a": 1}, "") is None


class TestEvaluateCondition:

    def test_equals_true(self):
        assert _evaluate_condition(5, "==", 5) is True

    def test_equals_false(self):
        assert _evaluate_condition(5, "==", 6) is False

    def test_not_equals(self):
        assert _evaluate_condition(5, "!=", 6) is True

    def test_greater_than(self):
        assert _evaluate_condition(10, ">", 5) is True
        assert _evaluate_condition(5, ">", 10) is False

    def test_less_than(self):
        assert _evaluate_condition(5, "<", 10) is True

    def test_greater_or_equal(self):
        assert _evaluate_condition(5, ">=", 5) is True
        assert _evaluate_condition(5, ">=", 4) is True

    def test_in_operator(self):
        assert _evaluate_condition("a", "in", ["a", "b", "c"]) is True
        assert _evaluate_condition("d", "in", ["a", "b", "c"]) is False

    def test_not_in_operator(self):
        assert _evaluate_condition("d", "not_in", ["a", "b", "c"]) is True
        assert _evaluate_condition("a", "not_in", ["a", "b", "c"]) is False

    def test_none_values_safe(self):
        """None 值不会导致异常。"""
        assert _evaluate_condition(None, ">", 5) is False

    def test_unknown_operator_defaults_to_equals(self):
        assert _evaluate_condition(5, "unknown_op", 5) is True


class TestMakeFixIterationUpdater:

    @pytest.mark.asyncio
    async def test_increments(self):
        fn = make_fix_iteration_updater()
        state = initial_state(fix_iterations=0)
        result = await fn(state)
        assert result["fix_iterations"] == 1

    @pytest.mark.asyncio
    async def test_increments_from_middle(self):
        fn = make_fix_iteration_updater()
        state = initial_state(fix_iterations=5)
        result = await fn(state)
        assert result["fix_iterations"] == 6
