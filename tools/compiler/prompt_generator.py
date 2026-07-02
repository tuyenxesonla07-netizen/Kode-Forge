"""
tools/compiler/prompt_generator.py

Prompt 模板生成器 — 从所有模块的 output_schema 自动生成 Prompt 模板

核心创新：不是手写一个通用模板，而是根据实际 Schema 生成精确匹配的模板。
如果订单模块有 state_machine 而支付模块没有，模板中只对订单模块生成状态机部分。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class PromptTemplate:
    """生成的 Prompt 模板 + 渲染后的 Prompt"""
    template_str: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def render(self, context: Dict) -> str:
        """用上下文数据渲染模板"""
        result = self.template_str
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result


class PromptTemplateGenerator:
    """从所有模块的 output_schema 自动生成 Prompt 模板"""

    def __init__(self, global_constraints: Optional[Dict] = None) -> None:
        self.global_constraints = global_constraints or {
            "language": "Python 3.12",
            "framework": "FastAPI",
            "database": "PostgreSQL",
            "coding_style": "Google Python Style Guide",
            "error_handling_policy": "RFC 7807 Problem Details",
            "logging_convention": "structured JSON logging",
        }

    def generate(self, module_schemas: Dict[str, dict],
                 implementation_order: List[str],
                 interface_contracts: Dict[str, str] = None) -> PromptTemplate:
        """
        输入:
          module_schemas: 所有模块的 output_schema
          implementation_order: 拓扑排序后的模块顺序
          interface_contracts: 跨模块接口契约（可选）

        输出: 完整的 Prompt 模板
        """
        sections = []

        # 头部
        sections.append(self._generate_header())

        # 全局约束
        sections.append(self._generate_global_constraints())

        # 实现顺序
        sections.append(self._generate_implementation_order(implementation_order))

        # 每个模块的规格
        module_sections = []
        for module_name in implementation_order:
            if module_name in module_schemas:
                module_sections.append(
                    self._generate_module_spec(module_name, module_schemas[module_name])
                )
        sections.append("\n\n".join(module_sections))

        # 跨模块接口契约
        if interface_contracts:
            sections.append(
                self._generate_interface_contracts(interface_contracts)
            )

        # 错误处理规范
        sections.append(self._generate_error_handling())

        # 日志规范
        sections.append(self._generate_logging_conventions())

        template_str = "\n\n---\n\n".join(sections)

        return PromptTemplate(
            template_str=template_str,
            metadata={
                "modules": implementation_order,
                "schema_count": len(module_schemas),
                "has_interface_contracts": bool(interface_contracts),
            }
        )

    def _generate_header(self) -> str:
        return (
            "# 项目: {{project_name}}\n\n"
            "## 概述\n"
            "{{project_description}}\n\n"
            "## 技术栈\n"
            "| 组件 | 选型 | 版本 |\n"
            "|------|------|------|"
        )

    def _generate_global_constraints(self) -> str:
        lines = ["## 全局约束"]
        for key, value in self.global_constraints.items():
            lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)

    def _generate_implementation_order(self, order: List[str]) -> str:
        lines = ["## 实现顺序（拓扑排序）"]
        for i, module in enumerate(order, 1):
            lines.append(f"{i}. {module}")
        return "\n".join(lines)

    def _generate_module_spec(self, module_name: str, schema: dict) -> str:
        """从单个模块的 output_schema 生成该模块的 Prompt 部分"""
        spec_props = schema.get("properties", {}).get("module_spec", {})
        required = spec_props.get("required", [])
        properties = spec_props.get("properties", {})

        lines = [f"## 模块: {module_name}\n"]

        # 组件列表
        if "components" in properties:
            lines.append("### 组件列表")
            comp_schema = properties["components"]
            comp_type_enum = (
                comp_schema.get("items", {})
                .get("properties", {})
                .get("type", {})
                .get("enum", [])
            )
            if comp_type_enum:
                lines.append(f"需要实现的代码类型: {', '.join(comp_type_enum)}")
            else:
                lines.append("需要实现的代码类型: service, model, route, util")
            lines.append("")

        # 接口定义（如果 Schema 中有 interfaces）
        if "interfaces" in properties:
            lines.append("### 接口定义")
            lines.append("请根据以下接口契约实现：")
            lines.append("```")
            lines.append(f"# {module_name} 接口定义")
            lines.append("```")
            lines.append("")

        # 状态机（仅当 Schema 包含 state_machine 时生成）
        if "state_machine" in properties:
            sm_schema = properties["state_machine"]
            sm_props = sm_schema.get("properties", {})
            lines.append("### 状态机")
            if "states" in sm_props:
                lines.append("需要定义的状态和转换：")
                lines.append("```")
                lines.append(f"# {module_name} 状态机")
                lines.append("```")
            lines.append("")

        # 验收标准
        if "acceptance_criteria" in required:
            lines.append("### 验收标准")
            lines.append("{{" + module_name + "_acceptance_criteria}}")
            lines.append("")

        return "\n".join(lines)

    def _generate_interface_contracts(self, contracts: Dict[str, str]) -> str:
        lines = ["## 跨模块接口契约"]
        for module_name, contract in contracts.items():
            lines.append(f"### {module_name}")
            lines.append(f"```\n{contract}\n```")
        return "\n".join(lines)

    def _generate_error_handling(self) -> str:
        return (
            "## 错误处理规范\n"
            "- 所有 API 返回遵循 RFC 7807\n"
            "- 错误码格式: {module}_{error_type}_{seq}\n"
            "- 全局异常处理器捕获未处理异常\n"
            "- 错误响应包含 trace_id 用于追踪"
        )

    def _generate_logging_conventions(self) -> str:
        return (
            "## 日志规范\n"
            "- 使用结构化 JSON 格式\n"
            "- 必须包含: timestamp, level, module, trace_id, message\n"
            "- 敏感信息脱敏（密码、token）\n"
            "- 错误日志附带完整堆栈"
        )
