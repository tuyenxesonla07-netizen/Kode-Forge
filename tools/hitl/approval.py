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
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 风险等级定义（从低到高）
RISK_LEVELS = ["low", "medium", "high", "critical"]

# Dual-factor enforcement: CRITICAL risk requires at least N distinct approvers
CRITICAL_MIN_APPROVERS = 2

@dataclass
class ApprovalResult:
    """审批结果"""
    approved: bool
    approver: str = ""
    comment: str = ""
    requires_human: bool = False
    approval_id: str = ""

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

    def __init__(self, auto_under_risk: str = "low") -> None:
        """
        Args:
            auto_under_risk: 低于等于此等级的风险自动放行。
                不允许设为 "critical" — critical 风险永远需要人工。
        """
        if auto_under_risk == "critical":
            raise ValueError("auto_under_risk cannot be 'critical'")
        self.auto_under_risk = auto_under_risk
        self._risk_order = {level: i for i, level in enumerate(RISK_LEVELS)}

    def request_approval(self, tool_name: str, args: dict, risk_level: str,
                         context: dict = None) -> ApprovalResult:
        if risk_level not in RISK_LEVELS:
            raise ValueError(f"Unknown risk level: {risk_level!r}")
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

    def __init__(self, callback_url: str = None) -> None:
        self.callback_url = callback_url
        self._pending: dict[str, ApprovalRequest] = {}

    def request_approval(self, tool_name: str, args: dict, risk_level: str,
                         context: dict = None) -> ApprovalResult:
        approval_id = f"approval_{uuid.uuid4().hex[:12]}"

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
        mode: "auto" | "manual" | "enterprise"
    """
    if mode == "enterprise":
        from tools.hitl.approval import EnterpriseApprovalHandler
        return EnterpriseApprovalHandler(**kwargs)
    if mode == "manual":
        return ManualApprovalHandler(**kwargs)
    return AutoApprovalHandler(**kwargs)

# ── EnterpriseApprovalHandler ──────────────────────────────────────────────

from typing import Any, Optional as _Optional

from tools.hitl.approval_state import ApprovalStateMachine, ApprovalStatus, InvalidTransitionError
from tools.hitl.approval_chain import ApprovalChain, RoleRegistry
from tools.hitl.audit_chain import HashChainedAuditLog
from tools.hitl.escalation import SLATimer, EscalationPolicy, EscalationState

@dataclass
class ApprovalRecord:
    """完整的审批记录，包含状态机、请求和元数据。"""
    approval_id: str
    request: ApprovalRequest
    state_machine: ApprovalStateMachine
    escalation_state: EscalationState
    result: _Optional[ApprovalResult] = None

class EnterpriseApprovalHandler(ApprovalHandler):
    """
    企业级审批处理器。

    特性：
    - 多级审批链（基于风险等级自动选择）
    - 状态机驱动（PENDING → APPROVED/REJECTED/ESCALATED/EXPIRED）
    - SLA 定时器自动升级
    - Hash-chained 审计日志（防篡改）
    - 角色注册表（审批人分配）

    用法:
        registry = RoleRegistry()
        registry.assign("tech_lead", "alice")
        registry.assign("manager", "bob")

        handler = EnterpriseApprovalHandler(role_registry=registry)
        result = handler.request_approval("write_file", {"path": "/etc/passwd"}, "high")
        # result.requires_human == True，等待审批
        result = handler.approve(result.approval_id, actor="alice")
    """

    def __init__(
        self,
        chain: _Optional[ApprovalChain] = None,
        role_registry: _Optional[RoleRegistry] = None,
        audit_log: _Optional[HashChainedAuditLog] = None,
        escalation_policy: _Optional[EscalationPolicy] = None,
        messaging_bus: Any = None,
    ) -> None:
        """
        Args:
            chain: 审批链
            role_registry: 角色注册表
            audit_log: 审计日志
            escalation_policy: 升级策略
            messaging_bus: 多渠道消息总线（V0.4.0 F4 集成）
        """
        self._role_registry = role_registry or RoleRegistry()
        self._chain = chain
        self._audit = audit_log or HashChainedAuditLog()
        self._escalation_policy = escalation_policy or EscalationPolicy()
        self._messaging_bus = messaging_bus
        self._records: dict[str, ApprovalRecord] = {}
        self._timers: dict[str, SLATimer] = {}

    def request_approval(
        self,
        tool_name: str,
        args: dict,
        risk_level: str,
        context: dict | None = None,
    ) -> ApprovalResult:
        """
        发起审批请求。

        根据风险等级构建审批链（如未手动指定），创建状态机实例，
        启动 SLA 定时器，并记录审计日志。
        """
        context = context or {}
        request = ApprovalRequest(
            tool_name=tool_name,
            args=args,
            risk_level=risk_level,
            context=context,
        )

        approval_id = uuid.uuid4().hex[:12]
        state_machine = ApprovalStateMachine()
        escalation_state = EscalationState(approval_id=approval_id, current_level=1)

        record = ApprovalRecord(
            approval_id=approval_id,
            request=request,
            state_machine=state_machine,
            escalation_state=escalation_state,
        )
        self._records[approval_id] = record

        # 记录审计日志
        self._audit.record({
            "event": "approval_requested",
            "approval_id": approval_id,
            "tool_name": tool_name,
            "risk_level": risk_level,
        })

        # 确定审批链
        chain = self._chain
        if chain is None:
            from tools.hitl.approval_chain import build_chain_from_registry
            chain = build_chain_from_registry(self._role_registry, risk_level)

        # 启动 SLA 定时器（如果审批链非空且风险不是 low）
        if not chain.is_empty:
            level = chain.get_level(1)
            if level is not None and risk_level != "low":
                timer = SLATimer(
                    approval_id=approval_id,
                    level=1,
                    sla=level.sla,
                    on_timeout=self._make_timeout_handler(approval_id, chain),
                )
                timer.start()
                self._timers[approval_id] = timer

        requires_human = risk_level == "critical" or (risk_level in ("medium", "high") and not chain.is_empty)

        # CRITICAL risk: publish immediate alert on message bus + audit event
        if risk_level == "critical":
            self._audit.record({
                "event": "critical_approval_required",
                "approval_id": approval_id,
                "tool_name": tool_name,
                "risk_level": risk_level,
                "min_approvers": CRITICAL_MIN_APPROVERS,
            })
            if self._messaging_bus is not None:
                try:
                    self._messaging_bus.publish("alert.critical", {
                        "approval_id": approval_id,
                        "tool_name": tool_name,
                        "risk_level": risk_level,
                    })
                except Exception as e:
                    logger.warning("Failed to publish CRITICAL alert: %s", e)

        if risk_level == "critical":
            comment = (
                f"Approval requested (id={approval_id}, risk=critical, "
                f"requires {CRITICAL_MIN_APPROVERS} distinct approvers)"
            )
        else:
            comment = f"Approval requested (id={approval_id}, risk={risk_level})"

        return ApprovalResult(
            approved=False,
            approver="",
            comment=comment,
            requires_human=requires_human,
            approval_id=approval_id,
        )

    def approve(
        self,
        approval_id: str,
        actor: str,
        comment: str = "",
        justification: str = "",
    ) -> ApprovalResult:
        """
        批准审批请求。

        For CRITICAL risk operations dual-factor enforcement applies:
        at least ``CRITICAL_MIN_APPROVERS`` *distinct* actors must approve
        before the request actually transitions to APPROVED.
        """
        record = self._records.get(approval_id)
        if record is None:
            return ApprovalResult(
                approved=False,
                approver=actor,
                comment=f"Unknown approval_id: {approval_id}",
                requires_human=False,
            )

        # CRITICAL dual-factor: track distinct approvers
        if record.request.risk_level == "critical":
            if not hasattr(record, '_approvers'):
                record._approvers = set()
            if actor in record._approvers:
                return ApprovalResult(
                    approved=False,
                    approver=actor,
                    comment=f"{actor} has already approved",
                    requires_human=False,
                )
            record._approvers.add(actor)
            if len(record._approvers) < CRITICAL_MIN_APPROVERS:
                # Record partial progress in audit log
                self._audit.record({
                    "event": "critical_approval_partial",
                    "approval_id": approval_id,
                    "actor": actor,
                    "count": f"{len(record._approvers)}/{CRITICAL_MIN_APPROVERS}",
                })
                return ApprovalResult(
                    approved=False,
                    approver=actor,
                    comment=f"Partial approval {len(record._approvers)}/{CRITICAL_MIN_APPROVERS}",
                    requires_human=True,
                )

        try:
            record.state_machine.approve(reason=f"approved by {actor}: {comment}")
        except InvalidTransitionError as e:
            return ApprovalResult(
                approved=False,
                approver=actor,
                comment=f"Cannot approve: {e}",
                requires_human=False,
            )

        # 取消 SLA 定时器
        self._cancel_timer(approval_id)

        result = ApprovalResult(
            approved=True,
            approver=actor,
            comment=comment or "Approved",
            requires_human=False,
        )
        record.result = result

        self._audit.record({
            "event": "approved",
            "approval_id": approval_id,
            "actor": actor,
            "justification": justification,
        })

        # V0.4.0 F4: 发布审批结果事件
        if self._messaging_bus is not None:
            try:
                self._messaging_bus.publish("events.approval", {
                    "approval_id": approval_id,
                    "status": "approved",
                    "actor": actor,
                })
            except Exception as e:
                logger.warning("Failed to publish approval event to message bus: %s", e)

        return result

    def reject(
        self,
        approval_id: str,
        actor: str,
        reason: str = "",
    ) -> ApprovalResult:
        """
        拒绝审批请求。

        Args:
            approval_id: 审批 ID
            actor: 审批人 ID
            reason: 拒绝原因
        """
        record = self._records.get(approval_id)
        if record is None:
            return ApprovalResult(
                approved=False,
                approver=actor,
                comment=f"Unknown approval_id: {approval_id}",
                requires_human=False,
            )

        try:
            record.state_machine.reject(reason=f"rejected by {actor}: {reason}")
        except InvalidTransitionError as e:
            return ApprovalResult(
                approved=False,
                approver=actor,
                comment=f"Cannot reject: {e}",
                requires_human=False,
            )

        # 取消 SLA 定时器
        self._cancel_timer(approval_id)

        result = ApprovalResult(
            approved=False,
            approver=actor,
            comment=reason or "Rejected",
            requires_human=False,
        )
        record.result = result

        self._audit.record({
            "event": "rejected",
            "approval_id": approval_id,
            "actor": actor,
            "reason": reason,
        })

        return result

    def escalate(
        self,
        approval_id: str,
        actor: str = "system",
        reason: str = "",
    ) -> ApprovalResult:
        """
        将审批升级到下一层级。

        Args:
            approval_id: 审批 ID
            actor: 触发升级的角色（通常是 system）
            reason: 升级原因
        """
        record = self._records.get(approval_id)
        if record is None:
            return ApprovalResult(
                approved=False,
                approver=actor,
                comment=f"Unknown approval_id: {approval_id}",
                requires_human=False,
            )

        if not record.escalation_state.can_escalate(self._escalation_policy):
            return ApprovalResult(
                approved=False,
                approver=actor,
                comment="Max escalations reached",
                requires_human=True,
            )

        try:
            record.state_machine.escalate(reason=f"escalated by {actor}: {reason}")
        except InvalidTransitionError as e:
            return ApprovalResult(
                approved=False,
                approver=actor,
                comment=f"Cannot escalate: {e}",
                requires_human=False,
            )

        # 更新升级状态
        new_level = record.escalation_state.current_level + 1
        record.escalation_state.record_escalation(target_level=new_level)

        # 取消旧的 SLA 定时器，启动新的
        self._cancel_timer(approval_id)

        chain = self._chain
        if chain is None:
            from tools.hitl.approval_chain import build_chain_from_registry
            chain = build_chain_from_registry(self._role_registry, record.request.risk_level)

        target_level = chain.get_level(new_level)
        if target_level is not None:
            timer = SLATimer(
                approval_id=approval_id,
                level=new_level,
                sla=target_level.sla,
                on_timeout=self._make_timeout_handler(approval_id, chain),
            )
            timer.start()
            self._timers[approval_id] = timer

        self._audit.record({
            "event": "escalated",
            "approval_id": approval_id,
            "actor": actor,
            "new_level": new_level,
            "reason": reason,
        })

        # V0.4.0 F4 集成：发布升级事件到多渠道消息总线
        if self._messaging_bus is not None:
            try:
                self._messaging_bus.publish("escalation.event", {
                    "approval_id": approval_id,
                    "new_level": new_level,
                    "risk_level": record.request.risk_level,
                    "reason": reason,
                    "actor": actor,
                })
            except Exception as e:
                logger.warning("Failed to publish escalation event to message bus (approval %s): %s", approval_id, e)  # 消息总线失败不影响审批流程

        return ApprovalResult(
            approved=False,
            approver=actor,
            comment=f"Escalated to level {new_level}",
            requires_human=True,
        )

    def get_status(self, approval_id: str) -> _Optional[ApprovalRecord]:
        """获取审批记录的完整状态。"""
        return self._records.get(approval_id)

    def get_audit_log(self) -> HashChainedAuditLog:
        """返回 hash-chained 审计日志实例。"""
        return self._audit

    @property
    def pending_count(self) -> int:
        """返回待处理的审批请求数量。"""
        return sum(
            1 for r in self._records.values()
            if not r.state_machine.is_terminal
        )

    def _cancel_timer(self, approval_id: str) -> None:
        """取消指定审批的 SLA 定时器。"""
        timer = self._timers.pop(approval_id, None)
        if timer is not None:
            timer.cancel()

    def _make_timeout_handler(self, approval_id: str, chain: ApprovalChain) -> Any:
        """创建 SLA 超时处理器闭包。"""
        async def handler(_approval_id: str, level: int) -> None:
            record = self._records.get(approval_id)
            if record is None or record.state_machine.is_terminal:
                return

            # 尝试升级
            target = chain.get_escalation_target(level)
            if target is not None and record.escalation_state.can_escalate(self._escalation_policy):
                self.escalate(approval_id, actor="system", reason="SLA timeout")
            else:
                # 无法升级，标记过期
                try:
                    record.state_machine.expire(reason="SLA timeout, no escalation target")
                    self._audit.record({
                        "event": "expired",
                        "approval_id": approval_id,
                        "reason": "SLA timeout",
                    })
                except InvalidTransitionError:
                    pass

        return handler
