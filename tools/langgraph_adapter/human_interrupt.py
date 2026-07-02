# tools/langgraph_adapter/human_interrupt.py

"""
人工中断包装器 — 将 HumanNode 包装为 LangGraph interrupt_before 语义。

在 LangGraph 中，interrupt_before 会在指定节点执行前暂停图，
等待人类通过 Command(resume=...) 恢复执行。

本模块提供：
- wrap_with_interrupt: 将节点函数包装为支持中断的版本
- resume_with_approval: 构建恢复命令
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from tools.langgraph_adapter.state import LangGraphState

logger = logging.getLogger(__name__)


def make_human_interrupt_node(
    node_fn: callable,
    prompt: str = "需要人工确认",
    risk_level: str = "high",
) -> callable:
    """
    构建支持人工中断的节点函数。

    在 LangGraph 中配合 interrupt_before 使用：
    - 节点执行前，LangGraph 中断
    - 调用方检查 pending_human 状态，展示给人类
    - 人类确认后，通过 Command(resume={"approved": True}) 恢复

    Args:
        node_fn: 原始节点函数
        prompt: 审批提示
        risk_level: 风险等级

    Returns:
        包装后的节点函数
    """
    async def interrupt_node_fn(state: LangGraphState) -> dict[str, Any]:
        # 检查是否已有审批结果（从 pending_human 中）
        pending = state.get("pending_human")
        if pending and pending.get("approved") is not None:
            # 审批已完成，继续执行
            if pending["approved"]:
                result = await node_fn(state)
                result["pending_human"] = None  # 清除审批状态
                return result
            else:
                return {
                    "errors": [f"Rejected by human: {pending.get('reason', 'no reason')}"],
                    "pending_human": None,
                }

        # 首次执行：设置 pending_human 并返回等待状态
        return {
            "pending_human": {
                "node_id": None,  # 由调用方设置
                "prompt": prompt,
                "risk_level": risk_level,
                "approved": None,
                "reason": None,
            },
        }

    interrupt_node_fn.__name__ = f"human_interrupt_{node_fn.__name__}"  # type: ignore[attr-defined]
    return interrupt_node_fn


def resume_with_approval(approved: bool, reason: str = "") -> dict[str, Any]:
    """
    构建人工审批恢复命令的参数字典。

    用法:
        # 人类批准
        resume_data = resume_with_approval(True, "LGTM")
        # 传入 LangGraph Command(resume=resume_data)

        # 人类拒绝
        resume_data = resume_with_approval(False, "Risk too high")

    Args:
        approved: 是否批准
        reason: 审批原因/意见

    Returns:
        恢复参数字典
    """
    return {
        "pending_human": {
            "approved": approved,
            "reason": reason,
        },
    }


def check_pending_human(state: LangGraphState) -> Optional[dict[str, Any]]:
    """
    检查状态中是否有待人工审批的节点。

    Args:
        state: 当前 LangGraphState

    Returns:
        待审批信息字典，或 None（无待审批）
    """
    pending = state.get("pending_human")
    if pending is None:
        return None
    if pending.get("approved") is not None:
        return None  # 已审批
    return pending


def is_human_approval_needed(state: LangGraphState) -> bool:
    """检查当前状态是否需要人工审批。"""
    pending = state.get("pending_human")
    return pending is not None and pending.get("approved") is None
