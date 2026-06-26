# tools/hitl/approval.py

"""
审批处理器 — 控制高风险工具调用是否需要人工介入。

参考 customer-service-agent 的 ToolRuntime：
- 6步执行管道的第4步：风险审批
- 演示模式可自动放行，生产模式接真实审批台

审批策略:
- low risk: 自动放行（如 query_order, search_kb）
- medium risk: 可配置（如 generate_code）
- high risk: 必须人工审批（如 execute_code, write_file）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 风险等级定义
RISK_LEVELS = ["low", "medium", "high"]


@dataclass
class ApprovalResult:
    """审批结果"""
    approved: bool
    approver: str = ""
    comment: str = ""
    requires_human: bool = False


@dataclass
class ApprovalRequest:
    """审批请求"""
    tool_name: str
    args: dict
    risk_level: str
    context: dict


class ApprovalHandler(ABC):
    """审批处理器抽象接口"""

    @abstractmethod
    def request_approval(self, tool_name: str, args: dict, risk_level: str,
                         context: dict = None) -> ApprovalResult:
        """请求审批"""
        ...

    def callback(self, approval_id: str, approved: bool, comment: str = "") -> None:
        """审批回调（生产模式：审批台异步回调）"""
        ...


class AutoApprovalHandler(ApprovalHandler):
    """
    自动审批处理器。

    根据风险等级自动决定是否放行。
    用于开发和演示模式。

    用法:
        handler = AutoApprovalHandler(auto_under_risk="medium")
        result = handler.request_approval("write_file", {"path": "/tmp/test.py"}, "high")
        # result.approved = False (high risk requires human)
    """

    def __init__(self, auto_under_risk: str = "low"):
        """
        Args:
            auto_under_risk: 低于等于此等级的风险自动放行
        """
        self.auto_under_risk = auto_under_risk
        self._risk_order = {level: i for i, level in enumerate(RISK_LEVELS)}

    def request_approval(self, tool_name: str, args: dict, risk_level: str,
                         context: dict = None) -> ApprovalResult:
        risk_idx = self._risk_order.get(risk_level, 0)
        threshold_idx = self._risk_order.get(self.auto_under_risk, 0)

        if risk_idx <= threshold_idx:
            return ApprovalResult(
                approved=True,
                approver="auto",
                comment=f"Auto-approved (risk={risk_level} <= {self.auto_under_risk})",
            )

        return ApprovalResult(
            approved=False,
            approver="",
            comment=f"Risk level '{risk_level}' exceeds auto-approval threshold '{self.auto_under_risk}'",
            requires_human=True,
        )

    def callback(self, approval_id: str, approved: bool, comment: str = "") -> None:
        logger.info("[AutoApproval] callback %s: %s", approval_id, approved)


class ManualApprovalHandler(ApprovalHandler):
    """
    手动审批处理器。

    所有操作都需要人工审批（通过回调确认）。
    用于生产模式，对接真实审批台。

    用法:
        handler = ManualApprovalHandler()
        result = handler.request_approval("query_order", {"order_id": "ORD-0001"}, "low")
        # result.requires_human = True
        # 审批台回调: handler.callback(result_id, True, "approved")
    """

    def __init__(self, callback_url: str = None):
        self.callback_url = callback_url
        self._pending: dict[str, ApprovalRequest] = {}
        self._counter = 0

    def request_approval(self, tool_name: str, args: dict, risk_level: str,
                         context: dict = None) -> ApprovalResult:
        self._counter += 1
        approval_id = f"approval_{self._counter}"

        self._pending[approval_id] = ApprovalRequest(
            tool_name=tool_name,
            args=args,
            risk_level=risk_level,
            context=context or {},
        )

        return ApprovalResult(
            approved=False,
            approver="",
            comment=f"Approval required: {approval_id}",
            requires_human=True,
        )

    def callback(self, approval_id: str, approved: bool, comment: str = "") -> bool:
        """审批台回调"""
        if approval_id in self._pending:
            del self._pending[approval_id]
            logger.info("[ManualApproval] %s approved=%s: %s", approval_id, approved, comment)
            return True
        return False

    def get_pending(self) -> list[dict]:
        """获取待审批列表"""
        return [
            {"id": k, "tool": v.tool_name, "risk": v.risk_level}
            for k, v in self._pending.items()
        ]


# 便捷函数
def get_approval_handler(mode: str = "auto", **kwargs) -> ApprovalHandler:
    """
    工厂函数，创建审批处理器。

    Args:
        mode: "auto" | "manual"
    """
    if mode == "manual":
        return ManualApprovalHandler(**kwargs)
    return AutoApprovalHandler(**kwargs)
