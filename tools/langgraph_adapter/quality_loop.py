# tools/langgraph_adapter/quality_loop.py

"""
质量循环 — 质量门禁失败时的修复循环。

编译为 LangGraph 条件边：
    module_a → quality_a ─next→ module_b
                   ├─fix→ module_a (fix_iterations++)
                   └─fail→ END
"""

from __future__ import annotations

import logging
from typing import Any

from tools.langgraph_adapter.state import LangGraphState

logger = logging.getLogger(__name__)


def make_quality_condition_fn(
    quality_gate: dict[str, Any],
    next_node: str,
    fix_node: str | None,
    max_fix_iterations: int = 3,
) -> callable:
    """
    构建质量门禁条件函数。

    该函数被 LangGraph 作为条件边调用，决定下一步执行方向。

    Args:
        quality_gate: 质量门禁配置（metric, operator, value）
        next_node: 质量通过时的目标节点
        fix_node: 质量失败时回退到的节点（None 则直接失败）
        max_fix_iterations: 最大修复次数

    Returns:
        条件函数 (state) -> str（节点名称）
    """
    metric = quality_gate.get("metric", "")
    operator = quality_gate.get("operator", "==")
    expected_value = quality_gate.get("value", True)

    def quality_condition_fn(state: LangGraphState) -> str:
        node_outputs = state.get("node_outputs", {})
        fix_iterations = state.get("fix_iterations", 0)

        # 获取质量指标值
        metric_value = _extract_metric(node_outputs, metric)
        passed = _evaluate_condition(metric_value, operator, expected_value)

        if passed:
            logger.info("[QualityGate] %s PASSED → %s", metric, next_node)
            return next_node

        # 质量未通过
        if fix_node is not None and fix_iterations < max_fix_iterations:
            logger.info(
                "[QualityGate] %s FAILED (iteration %d/%d) → %s",
                metric, fix_iterations + 1, max_fix_iterations, fix_node,
            )
            return fix_node

        # 超过最大修复次数或没有修复节点
        logger.warning("[QualityGate] %s FAILED after %d iterations → END", metric, fix_iterations)
        return "__end__"

    return quality_condition_fn


def _extract_metric(node_outputs: dict[str, Any], metric: str) -> Any:
    """
    从节点输出中提取质量指标值。

    支持：
    - 直接键查找: "module_a.quality_score"
    - 嵌套字典查找
    """
    if not metric:
        return None

    # 尝试直接查找
    if metric in node_outputs:
        return node_outputs[metric]

    # 尝试点分路径
    parts = metric.split(".")
    current: Any = node_outputs
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _evaluate_condition(actual: Any, operator: str, expected: Any) -> bool:
    """
    评估条件表达式。

    支持: ==, !=, >, <, >=, <=, in, not_in
    """
    operators = {
        "==": lambda a, e: a == e,
        "!=": lambda a, e: a != e,
        ">": lambda a, e: a is not None and e is not None and a > e,
        "<": lambda a, e: a is not None and e is not None and a < e,
        ">=": lambda a, e: a is not None and e is not None and a >= e,
        "<=": lambda a, e: a is not None and e is not None and a <= e,
        "in": lambda a, e: a in e if e is not None else False,
        "not_in": lambda a, e: a not in e if e is not None else True,
    }

    fn = operators.get(operator)
    if fn is None:
        logger.warning("[QualityGate] Unknown operator '%s', defaulting to ==", operator)
        fn = operators["=="]

    try:
        return fn(actual, expected)
    except (TypeError, ValueError):
        return False


def make_fix_iteration_updater() -> callable:
    """
    构建修复迭代计数器更新函数。

    每次执行到修复节点时，fix_iterations 加 1。

    Returns:
        节点函数 async (state) -> {"fix_iterations": N+1}
    """
    async def fix_iteration_fn(state: LangGraphState) -> dict[str, Any]:
        current = state.get("fix_iterations", 0)
        return {"fix_iterations": current + 1}

    return fix_iteration_fn
