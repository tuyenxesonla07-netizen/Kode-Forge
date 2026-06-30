# tools/hitl/approval_chain.py

"""
多级审批链 — 基于角色的审批人分配和 SLA 配置。

结构：
    ApprovalLevel      — 单个审批层级（角色、审批人、SLA、升级目标）
    ApprovalChain      — 有序的审批层级列表
    RoleRegistry       — 角色 → 审批人列表映射
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional


@dataclass(frozen=True)
class ApprovalLevel:
    """
    单个审批层级。

    Attributes:
        level: 层级编号（从 1 开始）
        role_required: 所需角色（如 "tech_lead", "manager", "director"）
        approvers: 该层级的审批人 ID 列表
        sla: SLA 时间限制
        escalation_target: SLA 超时时升级的层级编号（None 表示不升级）
    """
    level: int
    role_required: str
    approvers: tuple[str, ...]
    sla: timedelta
    escalation_target: Optional[int] = None

    def __post_init__(self) -> None:
        if self.level < 1:
            raise ValueError(f"level must be >= 1, got {self.level}")
        if not self.approvers:
            raise ValueError(f"level {self.level}: approvers cannot be empty")
        if self.sla.total_seconds() <= 0:
            raise ValueError(f"level {self.level}: sla must be positive")

    @property
    def primary_approver(self) -> str:
        """返回主审批人（approvers 列表第一个）。"""
        return self.approvers[0]


@dataclass
class ApprovalChain:
    """
    多级审批链。

    有序的审批层级列表，支持按层级查询和升级。

    用法:
        chain = ApprovalChain([
            ApprovalLevel(1, "tech_lead", ("alice",), timedelta(hours=24), escalation_target=2),
            ApprovalLevel(2, "manager", ("bob",), timedelta(hours=48)),
        ])
        level = chain.get_level(1)  # level 1
        next_level = chain.get_escalation_target(1)  # level 2
    """
    levels: list[ApprovalLevel] = field(default_factory=list)

    def add_level(self, level: ApprovalLevel) -> None:
        """添加审批层级（按 level 编号排序）。"""
        if any(l.level == level.level for l in self.levels):
            raise ValueError(f"Duplicate level {level.level}")
        self.levels.append(level)
        self.levels.sort(key=lambda l: l.level)

    def get_level(self, level_num: int) -> Optional[ApprovalLevel]:
        """获取指定层级。"""
        for l in self.levels:
            if l.level == level_num:
                return l
        return None

    def get_escalation_target(self, level_num: int) -> Optional[ApprovalLevel]:
        """获取指定层级的升级目标层级。"""
        level = self.get_level(level_num)
        if level is None or level.escalation_target is None:
            return None
        return self.get_level(level.escalation_target)

    @property
    def max_level(self) -> int:
        """最大层级编号。"""
        if not self.levels:
            return 0
        return max(l.level for l in self.levels)

    @property
    def is_empty(self) -> bool:
        """审批链是否为空。"""
        return len(self.levels) == 0

    def __len__(self) -> int:
        return len(self.levels)

    def __iter__(self):
        return iter(self.levels)


@dataclass
class RoleRegistry:
    """
    角色注册表 — 角色到审批人列表的映射。

    支持多对多关系：一个角色可有多个审批人，一个审批人可持有多个角色。

    用法:
        registry = RoleRegistry()
        registry.assign("tech_lead", "alice")
        registry.assign("tech_lead", "charlie")
        approvers = registry.get_approvers("tech_lead")  # ["alice", "charlie"]
    """
    _roles: dict[str, list[str]] = field(default_factory=dict)

    def assign(self, role: str, approver: str) -> None:
        """将审批人分配到角色。"""
        if role not in self._roles:
            self._roles[role] = []
        if approver not in self._roles[role]:
            self._roles[role].append(approver)

    def remove(self, role: str, approver: str) -> bool:
        """从角色中移除审批人。返回是否成功移除。"""
        if role not in self._roles:
            return False
        if approver in self._roles[role]:
            self._roles[role].remove(approver)
            if not self._roles[role]:
                del self._roles[role]
            return True
        return False

    def get_approvers(self, role: str) -> list[str]:
        """获取角色的所有审批人列表。"""
        return list(self._roles.get(role, []))

    def has_role(self, approver: str, role: str) -> bool:
        """检查审批人是否持有指定角色。"""
        return approver in self._roles.get(role, [])

    def roles_for(self, approver: str) -> list[str]:
        """获取审批人持有的所有角色。"""
        return [role for role, approvers in self._roles.items() if approver in approvers]

    @property
    def roles(self) -> list[str]:
        """所有已注册的角色列表。"""
        return list(self._roles.keys())

    def __len__(self) -> int:
        return len(self._roles)

    def __contains__(self, item: str) -> bool:  # type: ignore[override]
        """支持 'role' in registry 语法。"""
        return item in self._roles


def build_chain_from_registry(
    registry: RoleRegistry,
    risk_level: str,
) -> ApprovalChain:
    """
    根据风险等级和角色注册表构建默认审批链。

    - low:     1 级（tech_lead）
    - medium:  2 级（tech_lead → manager）
    - high:    3 级（tech_lead → manager → director）

    如果某个角色没有审批人，则跳过该层级。
    """
    chain = ApprovalChain()

    role_map = {
        "low": [
            (1, "tech_lead", timedelta(hours=24), None),
        ],
        "medium": [
            (1, "tech_lead", timedelta(hours=12), 2),
            (2, "manager", timedelta(hours=24), None),
        ],
        "high": [
            (1, "tech_lead", timedelta(hours=6), 2),
            (2, "manager", timedelta(hours=12), 3),
            (3, "director", timedelta(hours=24), None),
        ],
    }

    levels = role_map.get(risk_level, role_map["low"])
    for level_num, role, sla, escalation in levels:
        approvers = registry.get_approvers(role)
        if approvers:
            chain.add_level(ApprovalLevel(
                level=level_num,
                role_required=role,
                approvers=tuple(approvers),
                sla=sla,
                escalation_target=escalation,
            ))

    return chain
