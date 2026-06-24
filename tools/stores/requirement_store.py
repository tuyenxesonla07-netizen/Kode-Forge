"""
tools/stores/requirement_store.py

需求上下文存储 — 按模块存储需求描述和约束
填充时机: Codex 完成需求拆分后
读取时机: ContextInjector 注入上下文时
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ModuleRequirement:
    """单个模块的需求上下文"""
    module_name: str
    description: str                       # 该模块的需求描述
    constraints: List[str] = field(default_factory=list)     # 技术约束
    priority: int = 1                      # 实现优先级（1=最高）
    business_rules: List[str] = field(default_factory=list)  # 业务规则
    security_requirements: List[str] = field(default_factory=list)
    compliance_requirements: List[str] = field(default_factory=list)
    search_requirements: List[str] = field(default_factory=list)
    custom_fields: Dict[str, str] = field(default_factory=dict)


class RequirementStore:
    """需求上下文存储"""

    def __init__(self):
        self._store: Dict[str, ModuleRequirement] = {}

    def put(self, module: str, requirement: ModuleRequirement) -> None:
        """存储模块需求"""
        self._store[module] = requirement

    def get(self, module: str) -> Optional[ModuleRequirement]:
        """获取模块需求"""
        return self._store.get(module)

    def get_for_injection(self, module: str) -> str:
        """
        返回格式化的需求描述，直接注入 Agent 上下文
        这是最小权限原则的核心：只返回该模块需要的信息
        """
        req = self._store.get(module)
        if not req:
            return ""

        lines = [f"## 模块: {req.module_name}", "", req.description, ""]

        if req.constraints:
            lines.append("## 技术约束")
            for c in req.constraints:
                lines.append(f"- {c}")
            lines.append("")

        if req.business_rules:
            lines.append("## 业务规则")
            for r in req.business_rules:
                lines.append(f"- {r}")
            lines.append("")

        if req.security_requirements:
            lines.append("## 安全要求")
            for s in req.security_requirements:
                lines.append(f"- {s}")
            lines.append("")

        if req.compliance_requirements:
            lines.append("## 合规要求")
            for c in req.compliance_requirements:
                lines.append(f"- {c}")
            lines.append("")

        if req.search_requirements:
            lines.append("## 搜索需求")
            for s in req.search_requirements:
                lines.append(f"- {s}")
            lines.append("")

        return "\n".join(lines)

    def get_all_modules(self) -> List[str]:
        """获取所有已注册的模块名"""
        return list(self._store.keys())

    def get_priority_order(self) -> List[str]:
        """按优先级返回模块列表"""
        sorted_reqs = sorted(self._store.items(), key=lambda x: x[1].priority)
        return [name for name, _ in sorted_reqs]

    def clear(self):
        """清空存储"""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
