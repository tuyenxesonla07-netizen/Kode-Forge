# tools/hitl/__init__.py

"""
HITL (Human-in-the-Loop) — 高风险操作的人工审批机制。

参考 customer-service-agent 的 ToolRuntime 审批流程：
- 低风险工具（查询、读取）自动放行
- 中风险工具（代码生成）可配置自动/手动
- 高风险工具（执行代码、文件写入）必须人工审批

V0.4.0 F3: 企业级审批工作流（多级审批链、状态机、SLA 升级、防篡改审计）。

用法:
    from tools.hitl import AutoApprovalHandler, ManualApprovalHandler, AuditLog
    from tools.hitl import EnterpriseApprovalHandler, RoleRegistry, HashChainedAuditLog

    # 企业级
    registry = RoleRegistry()
    registry.assign("tech_lead", "alice")
    handler = EnterpriseApprovalHandler(role_registry=registry)

    # V0.4.0 F4: 集成多渠道消息总线
    from tools.messaging import MultiChannelBus
    bus = MultiChannelBus(inner=MessageBus(), registry=ChannelRegistry(), routing_rules={
        "escalation.*": ["slack", "email"],
    })
    handler = EnterpriseApprovalHandler(role_registry=registry, messaging_bus=bus)
    result = handler.request_approval("write_file", {"path": "/etc/passwd"}, "high")
"""

from tools.hitl.approval import ApprovalHandler, AutoApprovalHandler, ManualApprovalHandler
from tools.hitl.approval import EnterpriseApprovalHandler
from tools.hitl.audit import AuditLog
from tools.hitl.audit_chain import HashChainedAuditLog
from tools.hitl.approval_state import ApprovalStatus, ApprovalStateMachine
from tools.hitl.approval_chain import ApprovalChain, ApprovalLevel, RoleRegistry
from tools.hitl.escalation import EscalationPolicy, SLATimer

__all__ = [
    # 基础审批
    "ApprovalHandler",
    "AutoApprovalHandler",
    "ManualApprovalHandler",
    # V0.4.0 F3: 企业级审批
    "EnterpriseApprovalHandler",
    "ApprovalStatus",
    "ApprovalStateMachine",
    "ApprovalChain",
    "ApprovalLevel",
    "RoleRegistry",
    "HashChainedAuditLog",
    "EscalationPolicy",
    "SLATimer",
    # 审计
    "AuditLog",
]
