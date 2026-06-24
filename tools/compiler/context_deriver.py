"""
tools/compiler/context_deriver.py

上下文注入推导器 — 从 input_schema 自动推导上下文注入策略

核心创新：不需要人工定义每个 Agent 需要什么上下文，
编译器读 Schema 的 required/properties，自动推导。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ContextStrategy:
    """推导出的上下文注入策略"""
    module_name: str
    needs_dependency_interfaces: bool = False
    needs_global_constraints: bool = True
    needs_security_context: bool = False
    needs_compliance_context: bool = False
    needs_business_rules: bool = False
    needs_search_requirements: bool = False
    depends_on: List[str] = field(default_factory=list)
    injectable_fields: List[str] = field(default_factory=list)


class ContextDeriver:
    """从 input_schema 自动推导上下文注入策略"""

    # Schema required 字段 → 上下文需求的映射规则
    REQUIRED_FIELD_RULES = {
        "dependencies": ("needs_dependency_interfaces", True),
        "constraints": ("needs_global_constraints", True),
        "requirement": ("injectable_fields", "requirement"),
    }

    # Schema properties → 上下文需求的映射规则
    PROPERTY_RULES = {
        "security_requirements": "needs_security_context",
        "compliance_requirements": "needs_compliance_context",
        "business_rules": "needs_business_rules",
        "search_requirements": "needs_search_requirements",
    }

    def derive(self, module_name: str, input_schema: dict) -> ContextStrategy:
        """
        输入: 模块的 input_schema (JSON Schema 对象)
        输出: 完整的上下文注入策略

        推导规则:
          1. required 含 "dependencies" → 需要注入依赖模块的 InterfaceDef
          2. required 含 "constraints" → 需要 GlobalConstraints
          3. properties 含 "security_requirements" → 注入安全规则
          4. properties 含 "compliance_requirements" → 注入合规规则
          5. properties 含 "business_rules" → 注入业务规则
          6. properties 含 "search_requirements" → 注入搜索需求
          7. 不含的字段 → 不注入（最小权限）
        """
        strategy = ContextStrategy(module_name=module_name)

        # 分析 required 字段
        for field_name in input_schema.get("required", []):
            if field_name in self.REQUIRED_FIELD_RULES:
                rule = self.REQUIRED_FIELD_RULES[field_name]
                if rule[1] is True:
                    setattr(strategy, rule[0], True)
                elif rule[1] == "requirement":
                    strategy.injectable_fields.append("requirement")

        # 分析 properties
        for prop_name, prop_value in input_schema.get("properties", {}).items():
            if prop_name == "dependencies":
                # 从 dependencies 数组推导依赖模块列表
                strategy.depends_on = self._extract_dependency_names(prop_value)

            if prop_name == "dependency_interfaces":
                # 需要依赖模块的接口定义
                strategy.needs_dependency_interfaces = True
                strategy.injectable_fields.append("dependency_interfaces")

            if prop_name in self.PROPERTY_RULES:
                attr_name = self.PROPERTY_RULES[prop_name]
                setattr(strategy, attr_name, True)
                strategy.injectable_fields.append(prop_name)

        return strategy

    def derive_all(self, module_schemas: Dict[str, dict]) -> Dict[str, ContextStrategy]:
        """批量推导所有模块的上下文策略"""
        strategies = {}
        for module_name, schema in module_schemas.items():
            strategies[module_name] = self.derive(module_name, schema)
        return strategies

    def _extract_dependency_names(self, deps_property: dict) -> List[str]:
        """从 dependencies 属性中提取依赖模块名称列表"""
        if "items" in deps_property and "type" in deps_property["items"]:
            # 这是一个数组类型，items 中的 enum 或 description 可能包含模块名
            items = deps_property["items"]
            if "enum" in items:
                return list(items["enum"])
            # 从 description 中提取（如 "依赖的外部模块列表"）
            # 实际依赖关系需要从 agents.yaml 的 dependencies 字段获取
        return []

    def explain(self, strategy: ContextStrategy) -> str:
        """生成人类可读的推导说明（用于调试和审计）"""
        lines = [f"ContextStrategy for '{strategy.module_name}':"]

        if strategy.needs_dependency_interfaces:
            lines.append(f"  ✓ 需要依赖接口 (依赖: {strategy.depends_on})")
        if strategy.needs_global_constraints:
            lines.append("  ✓ 需要全局约束")
        if strategy.needs_security_context:
            lines.append("  ✓ 需要安全上下文")
        if strategy.needs_compliance_context:
            lines.append("  ✓ 需要合规上下文")
        if strategy.needs_business_rules:
            lines.append("  ✓ 需要业务规则")
        if strategy.needs_search_requirements:
            lines.append("  ✓ 需要搜索需求")

        # 明确不注入的（最小权限）
        all_possible = [
            "security_requirements",
            "compliance_requirements",
            "business_rules",
            "search_requirements",
        ]
        excluded = [p for p in all_possible if not getattr(strategy, f"needs_{p}", False)]

        if excluded:
            lines.append(f"  ✗ 不注入（最小权限）: {excluded}")

        return "\n".join(lines)
