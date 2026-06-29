# -*- coding: utf-8 -*-
"""
tools/compiler/pipeline_compiler.py

流水线编译器 — 核心编排器

串联所有子推导器，读 Schema + pipeline.yaml → 生成完整的 Superpowers 配置包。
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
class PipelineConfig:
    """pipeline.yaml 加载结果"""
    name: str = "claude-codex-multi-agent"
    version: str = "1.0.0"
    quality_gates: List[Dict[str, Any]] = field(default_factory=list)
    timeouts: Dict[str, Any] = field(default_factory=dict)
    retry: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str = "config/pipeline.yaml") -> "PipelineConfig":
        """
        从 pipeline.yaml 加载配置。

        支持两种格式:
          1. 纯 YAML 文件
          2. 包含在 Markdown 代码块中的 YAML（自动提取 ```yaml ... ``` 部分）

        pipeline.yaml 结构:
          quality_gates:
            - name: "模块审查通过"
              metric: "all_modules_passed"
              operator: "=="
              value: true
              blocking: true
          timeouts:
            default_step_timeout_ms: 30000
            max_pipeline_timeout_minutes: 30
          retry:
            max_iterations: 3
            backoff_strategy: "exponential"
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "pyyaml is required for loading pipeline.yaml. "
                "Install with: pip install pyyaml"
            )

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取 YAML 内容（处理 Markdown 代码块包裹的情况）
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

        # 如果没有 Markdown 代码块标记，使用全部内容
        if not yaml_lines:
            yaml_lines = lines

        raw = yaml.safe_load("\n".join(yaml_lines))
        if not raw:
            return cls()

        return cls(
            name=raw.get("name", cls.name),
            version=raw.get("version", cls.version),
            quality_gates=raw.get("quality_gates", []),
            timeouts=raw.get("timeouts", {}),
            retry=raw.get("retry", {}),
        )


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
                 project_description: str = "",
                 pipeline_config: Optional[PipelineConfig] = None) -> CompiledPipeline:
        """
        主编译流程:
          0. 标准化模块名（短名 → 完整名，统一 agents_config 中的命名）
          1. 推导上下文注入策略
          2. 构建依赖图 + 拓扑排序
          3. 生成 Prompt 模板
          4. 推导修复指令模板
          5. 生成质量门禁（合并 pipeline.yaml 配置）
        """
        # Step 0: 标准化模块名 — 将 module_schemas 和 input_schemas 的短名映射为完整名
        module_schemas, input_schemas = self._normalize_module_names(
            module_schemas, input_schemas, agents_config
        )
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

        # Step 5: 质量门禁生成（合并 YAML 配置）
        quality_gates = self.quality_gate_generator.generate(
            module_schemas,
            external_gates=pipeline_config.quality_gates if pipeline_config else None,
        )

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
                "pipeline_config_loaded": pipeline_config is not None,
                "pipeline_name": pipeline_config.name if pipeline_config else None,
                "pipeline_version": pipeline_config.version if pipeline_config else None,
            },
        )

    def compile_incremental(
        self,
        new_module_schemas: Dict[str, dict],
        previous_compiled: "CompiledPipeline",
        agents_config: Optional[dict] = None,
        input_schemas: Optional[Dict[str, dict]] = None,
        project_name: str = "Untitled",
        project_description: str = "",
        pipeline_config: Optional[PipelineConfig] = None,
    ) -> "CompiledPipeline":
        """
        增量编译 — 只重新编译变更的模块，复用未变更模块的结果。

        对比 new_module_schemas 与 previous_compiled.module_schemas:
          - 新增模块: 完整编译
          - 删除模块: 移除
          - 变更模块: 重新推导 context_strategy / fix_template
          - 未变更模块: 复用 previous_compiled 中的结果

        dependency_graph 和 implementation_order 始终重新计算（因为依赖关系可能变化）。

        返回新的 CompiledPipeline，未变更的部分从 previous_compiled 复制。
        """
        old_schemas = previous_compiled.module_schemas

        # 1. 检测变更模块
        changed_modules = set()
        for name, new_schema in new_module_schemas.items():
            old_schema = old_schemas.get(name)
            if old_schema is None:
                changed_modules.add(name)  # 新增
            elif json.dumps(new_schema, sort_keys=True) != json.dumps(old_schema, sort_keys=True):
                changed_modules.add(name)  # 变更

        deleted_modules = set(old_schemas.keys()) - set(new_module_schemas.keys())

        # 2. 增量推导 context_strategies
        new_strategies = dict(previous_compiled.context_strategies)
        if changed_modules:
            changed_schemas = {name: new_module_schemas[name] for name in changed_modules if name in new_module_schemas}
            if input_schemas:
                changed_input = {name: input_schemas[name] for name in changed_modules if name in input_schemas}
                if changed_input:
                    derived = self.context_deriver.derive_all(changed_input)
                else:
                    derived = self.context_deriver.derive_all(changed_schemas)
            else:
                derived = self.context_deriver.derive_all(changed_schemas)
            new_strategies.update(derived)

        # 删除已移除模块的策略
        for name in deleted_modules:
            new_strategies.pop(name, None)

        # 3. 增量推导 fix_templates
        new_fix_templates = dict(previous_compiled.fix_templates)
        if changed_modules:
            changed_schemas = {name: new_module_schemas[name] for name in changed_modules if name in new_module_schemas}
            derived_fix = self.fix_deriver.derive_all(changed_schemas)
            new_fix_templates.update(derived_fix)

        for name in deleted_modules:
            new_fix_templates.pop(name, None)

        # 4. 重新构建依赖图和拓扑排序（依赖关系可能变化）
        dep_graph = self._build_dependency_graph(agents_config or {}, new_module_schemas)
        implementation_order = dep_graph.topological_sort()

        # 5. 重新生成 prompt_template（模块集合可能变化）
        prompt_template = self.prompt_generator.generate(
            module_schemas=new_module_schemas,
            implementation_order=implementation_order,
        )

        # 6. 质量门禁（模块数量可能变化，重新生成）
        quality_gates = self.quality_gate_generator.generate(
            new_module_schemas,
            external_gates=pipeline_config.quality_gates if pipeline_config else None,
        )

        return CompiledPipeline(
            module_schemas=new_module_schemas,
            agents_config=agents_config or {},
            context_strategies=new_strategies,
            implementation_order=implementation_order,
            dependency_graph=dep_graph,
            prompt_template=prompt_template,
            fix_templates=new_fix_templates,
            quality_gates=quality_gates,
            metadata={
                "project_name": project_name,
                "project_description": project_description,
                "module_count": len(new_module_schemas),
                "total_quality_gates": len(quality_gates.gates),
                "total_fix_rules": sum(len(ft.rules) for ft in new_fix_templates.values()),
                "pipeline_config_loaded": pipeline_config is not None,
                "pipeline_name": pipeline_config.name if pipeline_config else None,
                "pipeline_version": pipeline_config.version if pipeline_config else None,
                "incremental": True,
                "changed_modules": sorted(changed_modules),
                "deleted_modules": sorted(deleted_modules),
            },
        )

    def compile_from_config(self, config_dir: str = "config") -> CompiledPipeline:
        """
        从配置文件目录自动加载并编译

        自动读取:
          - config/agents.yaml → 模块注册信息
          - config/schemas/*.json → 所有模块的 output_schema
          - config/pipeline.yaml → 流水线配置（质量门禁、超时、重试）
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "pyyaml is required for compile_from_config(). "
                "Install with: pip install pyyaml"
            )

        # 读取 agents.yaml
        agents_path = os.path.join(config_dir, "agents.yaml")
        with open(agents_path, "r", encoding="utf-8") as f:
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

        # 读取 pipeline.yaml
        pipeline_cfg = self._load_pipeline_config(os.path.join(config_dir, "pipeline.yaml"))

        # 读取所有输出 Schema
        schemas_dir = os.path.join(config_dir, "schemas")
        module_schemas = {}

        if os.path.exists(schemas_dir):
            for filename in os.listdir(schemas_dir):
                if filename.endswith("_output.json"):
                    module_name = filename.replace("_output.json", "")
                    with open(os.path.join(schemas_dir, filename), "r", encoding="utf-8") as f:
                        module_schemas[module_name] = json.load(f)

        return self.compile(module_schemas, agents_config, pipeline_config=pipeline_cfg)

    @staticmethod
    def _load_pipeline_config(yaml_path: str) -> Optional[PipelineConfig]:
        """加载 pipeline.yaml 配置文件（不存在则返回 None）"""
        if not os.path.exists(yaml_path):
            return None
        return PipelineConfig.load(yaml_path)

    # 短名 → 完整模块名映射（schema 文件名前缀 → agents.yaml 中的名称）
    _SHORT_TO_FULL_NAME = {
        "auth": "authentication",
        "data_processing": "data_processing",
        "api_integration": "api_integration",
    }

    def _normalize_module_names(
        self,
        module_schemas: Dict[str, dict],
        input_schemas: Optional[Dict[str, dict]],
        agents_config: Optional[dict],
    ) -> tuple:
        """
        将 module_schemas / input_schemas 的短名(key)映射为完整模块名。

        当 agents_config 提供了模块注册信息时，将 schema 文件名前缀
        (auth, data_processing) 转换为完整名称 (authentication, data_processing)，
        使 compile() 内部所有数据结构使用统一的命名。
        """
        # 优先使用 agents_config 中的模块名映射
        name_map = dict(self._SHORT_TO_FULL_NAME)
        if agents_config:
            agents = agents_config.get("agents", {})
            for agent_id, agent_cfg in agents.items():
                if agent_cfg.get("role") != "expert":
                    continue
                full_name = agent_cfg.get("module", agent_id.replace("expert_", ""))
                # 从 full_name 反推文件前缀
                for short, full in self._SHORT_TO_FULL_NAME.items():
                    if full == full_name:
                        name_map[short] = full_name
                        break

        if not name_map:
            return module_schemas, input_schemas

        # 重映射 module_schemas
        new_module_schemas = {}
        for key, val in module_schemas.items():
            new_key = name_map.get(key, key)
            new_module_schemas[new_key] = val

        # 重映射 input_schemas
        new_input_schemas = None
        if input_schemas:
            new_input_schemas = {}
            for key, val in input_schemas.items():
                new_key = name_map.get(key, key)
                new_input_schemas[new_key] = val

        return new_module_schemas, new_input_schemas

    def _build_dependency_graph(self, agents_config: dict,
                                module_schemas: Dict[str, dict] = None) -> DependencyGraph:
        """从 agents.yaml 构建依赖图，无配置时从 Schema 推导

        处理模块名映射: 文件前缀名(auth) → 完整模块名(authentication)
        """
        builder = DependencyGraphBuilder(agents_config)
        graph = builder.build()

        # 模块名映射: schema 文件名前缀 → agents.yaml 中的完整模块名
        name_prefix_map = {
            "auth": "authentication",
            "data_processing": "data_processing",
            "api_integration": "api_integration",
        }

        # 如果 agents_config 没有提供足够的模块信息，从 schema keys 补充
        if module_schemas:
            existing_nodes = set(graph.nodes)
            for module_name in module_schemas:
                # 跳过已在图中的模块
                if module_name in existing_nodes:
                    continue
                # 检查是否是某个已知模块的文件前缀名
                full_name = name_prefix_map.get(module_name, module_name)
                if full_name in existing_nodes:
                    # 已在图中（用完整名称），不重复添加
                    continue
                # 新模块，独立添加
                graph.add_module(module_name, [])

        # 如果图为空（完全没有依赖信息），添加所有模块为独立节点
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
