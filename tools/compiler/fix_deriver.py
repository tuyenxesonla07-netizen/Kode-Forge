"""
tools/compiler/fix_deriver.py

修复指令推导器 — 从 output_schema 自动推导修复指令模板

核心创新：不是固定 7 种 fix_type，而是根据 Schema 动态生成修复规则。
订单模块会多出 fix_state_machine，认证模块会多出 fix_security。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import json


@dataclass
class FixRule:
    """单条修复规则的模板"""
    trigger: str                          # 触发条件描述
    fix_type: str                         # 修复类型标识
    required_fields: List[str] = field(default_factory=list)
    template: str = ""                    # 修复指令模板
    severity_filter: str = "all"          # 适用的严重级别


@dataclass
class FixTemplate:
    """某模块的完整修复指令模板"""
    module_name: str
    rules: List[FixRule] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def generate_fix_instructions(self, issues: List[dict]) -> List[dict]:
        """根据问题和规则生成具体的修复指令"""
        instructions = []
        for issue in issues:
            matching_rule = self._find_matching_rule(issue)
            if matching_rule:
                instruction = {
                    "type": "fix_instruction",
                    "module": self.module_name,
                    "fix_type": matching_rule.fix_type,
                    "issue_id": issue.get("issue_id", "unknown"),
                    "severity": issue.get("severity", "unknown"),
                    "location": issue.get("location", ""),
                    "description": issue.get("description", ""),
                    "suggested_fix": matching_rule.template.format(**issue),
                    "validation": issue.get("validation", "修复后验证"),
                    "estimated_effort": self._estimate_effort(matching_rule.fix_type),
                }
                instructions.append(instruction)
        return instructions

    def _find_matching_rule(self, issue: dict) -> Optional[FixRule]:
        """根据问题特征匹配修复规则"""
        for rule in self.rules:
            if self._matches(issue, rule):
                return rule
        return None

    def _matches(self, issue: dict, rule: FixRule) -> bool:
        """判断问题是否匹配某条规则"""
        if rule.severity_filter != "all":
            if issue.get("severity") not in rule.severity_filter:
                return False
        # 根据 fix_type 和 issue description 匹配
        desc = issue.get("description", "")
        if rule.fix_type == "add_component":
            return "缺少组件" in desc or "missing" in desc.lower()
        if rule.fix_type == "fix_interface":
            return "接口" in desc or "interface" in desc.lower()
        if rule.fix_type == "fix_state_machine":
            return ("状态" in desc or "transition" in desc.lower()
                    or "状态机" in desc or "from" in desc)
        if rule.fix_type == "fix_security":
            return "安全" in desc or "security" in desc.lower()
        return True  # 默认匹配

    def _estimate_effort(self, fix_type: str) -> str:
        """估算修复工作量"""
        effort_map = {
            "add_component": "medium",
            "fix_interface": "low",
            "fix_state_machine": "medium",
            "fix_security": "high",
            "add_test": "low",
            "fix_validation": "low",
            "fix_error_handling": "low",
            "refactor": "high",
        }
        return effort_map.get(fix_type, "medium")


class FixInstructionDeriver:
    """从 output_schema 自动推导修复指令模板"""

    def derive(self, module_name: str, output_schema: dict) -> FixTemplate:
        """
        输入: 模块的 output_schema
        输出: 该模块的修复指令模板
        """
        template = FixTemplate(module_name=module_name)
        spec_schema = output_schema.get("properties", {}).get("module_spec", {})
        spec_properties = spec_schema.get("properties", {})
        spec_required = spec_schema.get("required", [])

        # 规则 1: 组件修复（所有有 components 的模块）
        if "components" in spec_properties:
            comp_schema = spec_properties["components"]
            comp_required = comp_schema.get("items", {}).get("required", ["name", "type", "description"])
            template.rules.append(FixRule(
                trigger="missing_component",
                fix_type="add_component",
                required_fields=comp_required,
                template="缺少组件 '{name}'，类型应为 '{type}'，描述为 '{description}'",
            ))

        # 规则 2: 接口修复（所有有 interfaces 的模块）
        if "interfaces" in spec_properties:
            template.rules.append(FixRule(
                trigger="interface_mismatch",
                fix_type="fix_interface",
                template="接口 '{name}' 签名不一致，期望 {expected}，实际 {actual}",
            ))

        # 规则 3: 状态机修复（仅对有 state_machine 的模块）
        if "state_machine" in spec_properties:
            template.rules.append(FixRule(
                trigger="invalid_transition",
                fix_type="fix_state_machine",
                template="状态机转换无效: {from} -> {to}，缺少触发器 '{trigger}'",
                severity_filter=["critical", "major"],
            ))

        # 规则 4: 验收标准修复（所有有 acceptance_criteria 的模块）
        if "acceptance_criteria" in spec_required:
            template.rules.append(FixRule(
                trigger="acceptance_criteria_not_met",
                fix_type="add_test",
                template="验收标准未满足: {criteria}，需要添加测试验证",
            ))

        # 规则 5: 安全修复（检测安全相关字段）
        if "security_requirements" in spec_properties or module_name in ["authentication", "payment", "payment_integration"]:
            template.rules.append(FixRule(
                trigger="security_issue",
                fix_type="fix_security",
                template="安全问题: {description}，需要修复为安全实现",
                severity_filter=["critical"],
            ))

        # 规则 6: 校验修复（通用）
        template.rules.append(FixRule(
            trigger="validation_failure",
            fix_type="fix_validation",
            template="校验失败: {field} — {description}",
        ))

        # 规则 7: 错误处理修复（通用）
        template.rules.append(FixRule(
            trigger="error_handling_issue",
            fix_type="fix_error_handling",
            template="错误处理问题: {description}",
        ))

        # 元数据
        template.metadata = {
            "derived_from": f"{module_name}_output.json",
            "rule_count": len(template.rules),
            "has_state_machine_rule": "state_machine" in spec_properties,
            "has_security_rule": (
                "security_requirements" in spec_properties
                or module_name in ["authentication", "payment", "payment_integration"]
            ),
        }

        return template

    def derive_all(self, module_schemas: Dict[str, dict]) -> Dict[str, FixTemplate]:
        """批量推导所有模块的修复模板"""
        templates = {}
        for module_name, schema in module_schemas.items():
            templates[module_name] = self.derive(module_name, schema)
        return templates
