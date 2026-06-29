# tools/schema_validator.py
"""
P2-2: Schema 验证工具。

验证:
  1. JSON Schema 文件格式合法性
  2. agents.yaml 中引用的模块与 schema 文件一致
  3. input/output schema 必填字段匹配
  4. 依赖关系引用完整性
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning" | "info"
    message: str
    file: str = ""
    detail: str = ""

    def __str__(self) -> str:
        prefix = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(self.severity, "?")
        loc = f" [{self.file}]" if self.file else ""
        detail = f"\n   └─ {self.detail}" if self.detail else ""
        return f"{prefix} {self.message}{loc}{detail}"


@dataclass
class ValidationReport:
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, severity: str, message: str, file: str = "", detail: str = ""):
        self.issues.append(ValidationIssue(severity, message, file, detail))

    def merge(self, other: "ValidationReport"):
        self.issues.extend(other.issues)

    def summary(self) -> str:
        lines = []
        if self.is_valid:
            lines.append("✅ All validations passed!")
        else:
            lines.append(f"❌ {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        for issue in self.issues:
            lines.append(str(issue))
        return "\n".join(lines)


def validate_json_schemas(schemas_dir: str = "config/schemas") -> ValidationReport:
    """验证所有 JSON Schema 文件格式合法。"""
    report = ValidationReport()

    if not os.path.isdir(schemas_dir):
        report.add("error", f"Schemas directory not found: {schemas_dir}")
        return report

    schema_files = sorted(
        f for f in os.listdir(schemas_dir) if f.endswith(".json")
    )

    if not schema_files:
        report.add("warning", "No JSON Schema files found", schemas_dir)
        return report

    for filename in schema_files:
        filepath = os.path.join(schemas_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            report.add("error", f"Invalid JSON: {e}", filename)
            continue
        except Exception as e:
            report.add("error", f"Cannot read file: {e}", filename)
            continue

        # 检查必需字段
        if not isinstance(data, dict):
            report.add("error", "Schema root must be a JSON object", filename)
            continue

        schema_type = data.get("type")
        if schema_type is None:
            report.add("warning", "Missing 'type' field at root", filename)
        elif schema_type != "object":
            report.add("warning", f"Root type is '{schema_type}', expected 'object'", filename)

        # 检查 input schema 有 required 和 properties
        if "_input." in filename:
            if "required" not in data:
                report.add("warning", "Input schema missing 'required' field", filename)
            props = data.get("properties")
            if props and "requirement" not in props:
                report.add("warning", "Input schema missing 'requirement' property", filename)

        # 检查 output schema 有 module_spec
        if "_output." in filename:
            props = data.get("properties", {})
            if "module_spec" not in props:
                report.add("error", "Output schema missing 'module_spec' property", filename)

    return report


def validate_agents_schemas_consistency(
    agents_path: str = "config/agents.yaml",
    schemas_dir: str = "config/schemas",
) -> ValidationReport:
    """验证 agents.yaml 引用的模块与 schema 文件一致。"""
    report = ValidationReport()

    try:
        import yaml
    except ImportError:
        report.add("warning", "pyyaml not installed, skipping agents.yaml validation")
        return report

    # 读取 agents.yaml
    if not os.path.exists(agents_path):
        report.add("error", f"agents.yaml not found: {agents_path}")
        return report

    with open(agents_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取 YAML 部分
    lines = content.split("\n")
    yaml_lines = []
    in_yaml = False
    for line in lines:
        if line.strip().startswith("```yaml"):
            in_yaml = True
            continue
        if line.strip() == "```" and in_yaml:
            break
        if in_yaml:
            yaml_lines.append(line)
    if not yaml_lines:
        yaml_lines = lines

    try:
        agents_config = yaml.safe_load("\n".join(yaml_lines))
    except yaml.YAMLError as e:
        report.add("error", f"Invalid YAML in agents.yaml: {e}")
        return report

    if not agents_config or "agents" not in agents_config:
        report.add("error", "agents.yaml missing 'agents' section")
        return report

    # 获取所有 schema 文件对应的模块名
    schema_modules = set()
    if os.path.isdir(schemas_dir):
        for filename in os.listdir(schemas_dir):
            if filename.endswith("_output.json"):
                module_name = filename.replace("_output.json", "")
                schema_modules.add(module_name)

    # 检查每个 expert agent 是否有对应的 schema 文件
    for agent_id, agent_cfg in agents_config["agents"].items():
        if agent_cfg.get("role") != "expert":
            continue

        module_name = agent_cfg.get("module", agent_id.replace("expert_", ""))

        # 检查是否有对应的 input schema
        input_schema_path = os.path.join(schemas_dir, f"{module_name}_input.json")
        if not os.path.exists(input_schema_path):
            report.add(
                "error",
                f"Agent '{agent_id}' (module '{module_name}') missing input schema",
                detail=f"Expected: {module_name}_input.json",
            )

        # 检查是否有对应的 output schema
        output_schema_path = os.path.join(schemas_dir, f"{module_name}_output.json")
        if not os.path.exists(output_schema_path):
            report.add(
                "error",
                f"Agent '{agent_id}' (module '{module_name}') missing output schema",
                detail=f"Expected: {module_name}_output.json",
            )

    # 反向检查：schema 文件是否有对应的 agent
    agent_modules = set()
    for agent_id, agent_cfg in agents_config["agents"].items():
        if agent_cfg.get("role") == "expert":
            module_name = agent_cfg.get("module", agent_id.replace("expert_", ""))
            agent_modules.add(module_name)

    for module_name in schema_modules:
        if module_name not in agent_modules:
            report.add(
                "warning",
                f"Schema '{module_name}' has no corresponding expert agent in agents.yaml",
            )

    return report


def validate_dependency_references(
    agents_path: str = "config/agents.yaml",
    schemas_dir: str = "config/schemas",
) -> ValidationReport:
    """验证依赖关系引用完整性。"""
    report = ValidationReport()

    try:
        import yaml
    except ImportError:
        return report

    if not os.path.isdir(schemas_dir):
        return report

    # 读取所有 input schema 中的依赖声明
    declared_deps: dict[str, list] = {}
    for filename in os.listdir(schemas_dir):
        if not filename.endswith("_input.json"):
            continue
        module_name = filename.replace("_input.json", "")
        filepath = os.path.join(schemas_dir, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                schema = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        props = schema.get("properties", {})
        dep_prop = props.get("dependencies", {})
        items = dep_prop.get("items", {})
        enum_values = items.get("enum", [])
        if enum_values:
            declared_deps[module_name] = enum_values

    # 验证所有依赖引用指向已知模块
    all_modules = set()
    for filename in os.listdir(schemas_dir):
        if filename.endswith("_output.json"):
            all_modules.add(filename.replace("_output.json", ""))

    for module_name, deps in declared_deps.items():
        for dep in deps:
            if dep not in all_modules:
                report.add(
                    "warning",
                    f"Module '{module_name}' depends on '{dep}' which has no schema file",
                    file=f"{module_name}_input.json",
                )

    return report


def validate_all(config_dir: str = "config") -> ValidationReport:
    """运行所有验证，返回完整报告。"""
    report = ValidationReport()

    schemas_dir = os.path.join(config_dir, "schemas")
    agents_path = os.path.join(config_dir, "agents.yaml")

    report.merge(validate_json_schemas(schemas_dir))
    report.merge(validate_agents_schemas_consistency(agents_path, schemas_dir))
    report.merge(validate_dependency_references(agents_path, schemas_dir))

    return report
