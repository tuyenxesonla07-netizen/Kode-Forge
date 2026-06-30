# tools/hitl/approval_state.py

"""
审批状态机 — PENDING → APPROVED/REJECTED/ESCALATED/EXPIRED。

完整状态转换：
    PENDING ──approve──→ APPROVED [terminal]
    PENDING ──reject───→ REJECTED [terminal]
    PENDING ──escalate─→ ESCALATED
    PENDING ──expire───→ EXPIRED  [terminal]
    ESCALATED ─approve─→ APPROVED [terminal]
    ESCALATED ─reject──→ REJECTED [terminal]
    ESCALATED ─timeout─→ EXPIRED  [terminal]
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ApprovalStatus(str, Enum):
    """审批状态枚举。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"


# 合法状态转换表
VALID_TRANSITIONS: dict[ApprovalStatus, set[ApprovalStatus]] = {
    ApprovalStatus.PENDING: {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.ESCALATED,
        ApprovalStatus.EXPIRED,
    },
    ApprovalStatus.ESCALATED: {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
    },
}

# 终态集合
TERMINAL_STATES: frozenset[ApprovalStatus] = frozenset({
    ApprovalStatus.APPROVED,
    ApprovalStatus.REJECTED,
    ApprovalStatus.EXPIRED,
})


def is_terminal(status: ApprovalStatus) -> bool:
    """返回状态是否为终态。"""
    return status in TERMINAL_STATES


def can_transition(from_status: ApprovalStatus, to_status: ApprovalStatus) -> bool:
    """检查从 from_status 到 to_status 的转换是否合法。"""
    if is_terminal(from_status):
        return False
    allowed = VALID_TRANSITIONS.get(from_status, set())
    return to_status in allowed


class InvalidTransitionError(Exception):
    """非法状态转换异常。"""

    def __init__(self, from_status: ApprovalStatus, to_status: ApprovalStatus):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Invalid transition: {from_status.value} → {to_status.value}"
        )


class ApprovalStateMachine:
    """
    审批状态机实例。

    封装单个审批请求的状态和转换逻辑。

    用法:
        sm = ApprovalStateMachine()
        sm.transition(ApprovalStatus.ESCALATED)   # PENDING → ESCALATED
        sm.transition(ApprovalStatus.APPROVED)    # ESCALATED → APPROVED
        assert sm.is_terminal
    """

    __slots__ = ("_status", "_history")

    def __init__(self, initial: ApprovalStatus = ApprovalStatus.PENDING) -> None:
        if initial != ApprovalStatus.PENDING:
            raise ValueError(f"Initial state must be PENDING, got {initial.value}")
        self._status = initial
        self._history: list[tuple[ApprovalStatus, Optional[str]]] = [(initial, None)]

    @property
    def status(self) -> ApprovalStatus:
        """当前状态。"""
        return self._status

    @property
    def history(self) -> list[tuple[ApprovalStatus, Optional[str]]]:
        """状态转换历史（状态, 原因）。"""
        return list(self._history)

    @property
    def is_terminal(self) -> bool:
        """是否已到达终态。"""
        return is_terminal(self._status)

    def can(self, to_status: ApprovalStatus) -> bool:
        """检查是否可以转换到 to_status。"""
        return can_transition(self._status, to_status)

    def transition(
        self,
        to_status: ApprovalStatus,
        reason: Optional[str] = None,
    ) -> None:
        """
        执行状态转换。

        Args:
            to_status: 目标状态
            reason: 转换原因（可选，用于审计）

        Raises:
            InvalidTransitionError: 转换不合法时抛出
        """
        if not self.can(to_status):
            raise InvalidTransitionError(self._status, to_status)
        self._status = to_status
        self._history.append((to_status, reason))

    def approve(self, reason: Optional[str] = None) -> None:
        """便捷方法：转换到 APPROVED。"""
        self.transition(ApprovalStatus.APPROVED, reason)

    def reject(self, reason: Optional[str] = None) -> None:
        """便捷方法：转换到 REJECTED。"""
        self.transition(ApprovalStatus.REJECTED, reason)

    def escalate(self, reason: Optional[str] = None) -> None:
        """便捷方法：转换到 ESCALATED（仅 PENDING 状态可用）。"""
        self.transition(ApprovalStatus.ESCALATED, reason)

    def expire(self, reason: Optional[str] = None) -> None:
        """便捷方法：转换到 EXPIRED。"""
        self.transition(ApprovalStatus.EXPIRED, reason)

    def __repr__(self) -> str:
        return f"ApprovalStateMachine(status={self._status.value!r})"
