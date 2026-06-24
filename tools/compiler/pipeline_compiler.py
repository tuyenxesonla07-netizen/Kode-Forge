# -*- coding: utf-8 -*-
"""
tools/compiler/pipeline_compiler.py

流水线编译器 — 核心编排器

串联所有子推导器，读 Schema → 生成完整的 Superpowers 配置包。
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from tools.compiler.context_deriver import ContextDeriver, ContextStrategy
from tools.compiler.prompt_generator import PromptTemplateGenerator, PromptTemplate
from tools.compiler.fix_deriver import FixInstructionDeriver, FixTemplate
from tools.compiler.dependency_graph import DependencyGraphBuilder, DependencyGraph
from tools.compiler.quality_gate_gen import QualityGateGenerator, QualityGateSuite


@dataclass
class CompiledPipeline:
    """编译产物 — Superpowers 可直接消费的配置包"""
    # 原始输入
    module_schemas: Dict[str, dict]
    agents_config: dict

    # 编译产物
    context_strategies: Dict[str, ContextStrategy]
    implementation_order: List[str]
    dependency_graph: DependencyGraph
    prompt_template: PromptTemplate
    fix_templates: Dict[str, FixTemplate]
    quality_gates: QualityGateSuite

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_superpowers_config(self) -> dict:
        """转换为 Superpowers 运行时配置"""
        return {
            "version": "1.0",
            "pipeline": {
                "phases": {
                    "requirement_decomposition": {
                        "context_strategies": {
                            name: {
                                "needs_dependency_interfaces": s.needs_dependency_interfaces,
                                "needs_global_constraints": s.needs_global_constraints,
                                "needs_security_context": s.needs_security_context,
                                "needs_compliance_context": s.needs_compliance_context,
                                "depends_on": s.depends_on,
                                "injectable_fields": s.injectable_fields,
                            }
                            for name, s in self.context_strategies.items()
                        },
                        "implementation_order": self.implementation_order,
                    },
                    "code_review": {
                        "fix_templates": {
                            name: {
                                "rules": [
                                    {
                                        "trigger": r.trigger,
                                        "fix_type": r.fix_type,
                                        "template": r.template,
                                    }
                                    for r in template.rules
                                ]
                            }
                            for name, template in self.fix_templates.items()
                        },
                        "quality_gates": [
                            {
                                "name": g.name,
                                "metric": g.metric,
                                "operator": g.operator,
                                "threshold": g.threshold,
                                "blocking": g.blocking,
                            }
                            for g in self.quality_gates.gates
                        ],
                    },
                }
            },
            "metadata": self.metadata,
        }

    def explain(self) -> str:
        """生成人类可读的编译报告"""
        lines = [
            "=" * 60,
            "Pipeline Compilation Report",
            "=" * 60,
            "",
            f"Modules: {len(self.module_schemas)}",
            f"Implementation order: {' → '.join(self.implementation_order)}",
            f"Parallel groups: {self.dependency_graph.get_parallel_groups()}",
            "",
            "--- Context Injection Strategies ---",
        ]

        for name, strategy in self.context_strategies.items():
            lines.append(f"  {name}:")
            if strategy.needs_dependency_interfaces:
                lines.append(f"    → needs dependency interfaces (deps: {strategy.depends_on})")
            if strategy.needs_security_context:
                lines.append("    → needs security context")
            if strategy.needs_compliance_context:
                lines.append("    → needs compliance context")
            if strategy.needs_business_rules:
                lines.append("    → needs business rules")

        lines.extend([
            "",
            "--- Fix Template Summary ---",
        ])
        for name, template in self.fix_templates.items():
            lines.append(f"  {name}: {len(template.rules)} rules")
            for rule in template.rules:
                lines.append(f"    - {rule.fix_type} ({rule.trigger})")

        lines.extend([
            "",
            "--- Quality Gates ---",
        ])
        for gate in self.quality_gates.gates:
            blocking = "BLOCKING" if gate.blocking else "advisory"
            lines.append(f"  [{blocking}] {gate.name}: {gate.metric} {gate.operator} {gate.threshold}")

        lines.extend([
            "",
            "=" * 60,
        ])

        return "\n".join(lines)


class PipelineCompiler:
    """核心编译器入口"""

    def __init__(
        self,
        requirement_store=None,
        interface_store=None,
        spec_store=None,
        message_bus=None,
        global_constraints: Optional[Dict] = None,
    ):
        self.context_deriver = ContextDeriver()
        self.prompt_generator = PromptTemplateGenerator(global_constraints)
        self.fix_deriver = FixInstructionDeriver()
        self.quality_gate_generator = QualityGateGenerator()

        # Store 引用（可选，运行时填充）
        self.requirement_store = requirement_store
        self.interface_store = interface_store
        self.spec_store = spec_store
        self.message_bus = message_bus

    def compile(self, module_schemas: Dict[str, dict],
                 agents_config: Optional[dict] = None,
                 input_schemas: Optional[Dict[str, dict]] = None,
                 project_name: str = "Untitled",
                 project_description: str = "") -> CompiledPipeline:
        """
        主编译流程:
          1. 推导上下文注入策略
          2. 构建依赖图 + 拓扑排序
          3. 生成 Prompt 模板
          4. 推导修复指令模板
          5. 生成质量门禁
        """
        # Step 1: 上下文策略推导（需要 input_schema）
        # 如果没有提供 input_schemas，从 output_schemas 的 properties 推导
        if input_schemas:
            context_strategies = self.context_deriver.derive_all(input_schemas)
        else:
            # 从 output_schemas 推导（降级模式）
            context_strategies = self.context_deriver.derive_all(module_schemas)

        # Step 2: 依赖图构建和拓扑排序
        dep_graph = self._build_dependency_graph(agents_config or {}, module_schemas)
        implementation_order = dep_graph.topological_sort()

        # Step 3: Prompt 模板生成
        prompt_template = self.prompt_generator.generate(
            module_schemas=module_schemas,
            implementation_order=implementation_order,
        )

        # Step 4: 修复指令推导
        fix_templates = self.fix_deriver.derive_all(module_schemas)

        # Step 5: 质量门禁生成
        quality_gates = self.quality_gate_generator.generate(module_schemas)

        return CompiledPipeline(
            module_schemas=module_schemas,
            agents_config=agents_config or {},
            context_strategies=context_strategies,
            implementation_order=implementation_order,
            dependency_graph=dep_graph,
            prompt_template=prompt_template,
            fix_templates=fix_templates,
            quality_gates=quality_gates,
            metadata={
                "project_name": project_name,
                "project_description": project_description,
                "module_count": len(module_schemas),
                "total_quality_gates": len(quality_gates.gates),
                "total_fix_rules": sum(len(ft.rules) for ft in fix_templates.values()),
            },
        )

    def compile_from_config(self, config_dir: str = "config") -> CompiledPipeline:
        """
        从配置文件目录自动加载并编译

        自动读取:
          - config/agents.yaml → 模块注册信息
          - config/schemas/*.json → 所有模块的 output_schema
        """
        import yaml

        # 读取 agents.yaml
        agents_path = os.path.join(config_dir, "agents.yaml")
        with open(agents_path, "r") as f:
            # 提取 YAML 部分（去掉 markdown 代码块标记）
            content = f.read()
            # 简单处理：找到第一个 ```yaml 和最后一个 ```
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
            agents_config = yaml.safe_load("\n".join(yaml_lines)) if yaml_lines else {}

        # 读取所有 output Schema
        schemas_dir = os.path.join(config_dir, "schemas")
        module_schemas = {}

        if os.path.exists(schemas_dir):
            for filename in os.listdir(schemas_dir):
                if filename.endswith("_output.json"):
                    module_name = filename.replace("_output.json", "")
                    with open(os.path.join(schemas_dir, filename), "r") as f:
                        module_schemas[module_name] = json.load(f)

        return self.compile(module_schemas, agents_config)

    def _build_dependency_graph(self, agents_config: dict,
                                module_schemas: Dict[str, dict] = None) -> DependencyGraph:
        """从 agents.yaml \u6784\u5efa\u4f9d\u8d56\u56fe\uff0c\u65e0\u914d\u7f6e\u65f6\u4ece Schema \u63a8\u5bfc"""
        builder = DependencyGraphBuilder(agents_config)
        graph = builder.build()

        # \u5982\u679c agents_config \u6ca1\u6709\u63d0\u4f9b\u8db3\u591f\u7684\u6a21\u5757\u4fe1\u606f\uff0c\u4ece schema keys \u8865\u5145
        if module_schemas:
            existing_nodes = set(graph.nodes)
            for module_name in module_schemas:
                if module_name not in existing_nodes:
                    graph.add_module(module_name, [])

        # \u5982\u679c\u56fe\u4e3a\u7a7a\uff08\u5b8c\u5168\u6ca1\u6709\u4f9d\u8d56\u4fe1\u606f\uff09\uff0c\u6dfb\u52a0\u6240\u6709\u6a21\u5757\u4e3a\u72ec\u7acb\u8282\u70b9
        if not graph.nodes and module_schemas:
            for module_name in module_schemas:
                graph.add_module(module_name, [])

        return graph

    def _extract_deps_from_schema(self, schema: dict) -> List[str]:
        """\u4ece input_schema \u63d0\u53d6\u4f9d\u8d56\u5173\u7cfb"""
        deps = []
        props = schema.get("properties", {})

        if "dependencies" in props:
            dep_prop = props["dependencies"]
            if "items" in dep_prop and "enum" in dep_prop["items"]:
                deps = list(dep_prop["items"]["enum"])

        return deps
