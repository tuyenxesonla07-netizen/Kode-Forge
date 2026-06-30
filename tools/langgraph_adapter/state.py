# tools/langgraph_adapter/state.py

"""
LangGraph 状态定义 — TypedDict + reducers。

纯 Python，无 LangGraph 依赖。

状态字段:
    node_outputs  — Dict[str, Any]  (merge reducer：各节点输出)
    current_phase — int             (当前阶段)
    quality_passed — bool           (质量门禁是否通过)
    fix_iterations — int            (当前修复迭代次数)
    errors        — list[str]       (append reducer：累积错误)
    pending_human — dict | None     (待人工审批的节点)
"""

from __future__ import annotations

from typing import Any, TypedDict


class LangGraphState(TypedDict):
    """
    LangGraph 状态字典。

    每个字段的 reducer 策略：
    - node_outputs:   merge（dict.update）— 节点追加输出
    - current_phase:  replace — 每次赋值覆盖
    - quality_passed: replace
    - fix_iterations: replace
    - errors:         append — 错误累积
    - pending_human:  replace — 当前待审批节点
    """

    node_outputs: dict[str, Any]
    current_phase: int
    quality_passed: bool
    fix_iterations: int
    errors: list[str]
    pending_human: dict | None


def initial_state(**overrides: Any) -> LangGraphState:
    """
    创建初始状态。

    Args:
        **overrides: 覆盖默认值的字段

    Returns:
        LangGraphState 实例
    """
    defaults: LangGraphState = {
        "node_outputs": {},
        "current_phase": 0,
        "quality_passed": False,
        "fix_iterations": 0,
        "errors": [],
        "pending_human": None,
    }
    defaults.update(overrides)
    return defaults


def merge_node_outputs(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """
    node_outputs 的 reducer：合并两个字典。

    当 new 中的 key 与 existing 冲突时，new 的值覆盖。
    """
    merged = dict(existing)
    merged.update(new)
    return merged


def append_errors(existing: list[str], new: list[str] | str) -> list[str]:
    """
    errors 的 reducer：追加错误。

    Args:
        existing: 现有错误列表
        new: 新错误（字符串或字符串列表）
    """
    result = list(existing)
    if isinstance(new, str):
        result.append(new)
    else:
        result.extend(new)
    return result
