# agents/supervisor/__init__.py

"""
Codex 主管 Agent — 全局视角的唯一决策节点

职责:
  - 理解用户需求，提取核心功能点
  - 将需求拆解为功能模块任务
  - 通过 Superpowers 插件分发任务
  - 汇总各 Agent 产出，交付给 Claude Code
  - 代码审查不通过时，决定修复策略
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class Requirement:
    """结构化需求"""
    functional_modules: List[str] = field(default_factory=list)
    non_functional: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    priority: str = "medium"
    raw_text: str = ""


@dataclass
class ModuleTask:
    """模块任务"""
    module: str
    priority: int = 1
    dependencies: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledPipeline:
    """编译后的流水线配置"""
    context_strategies: Dict[str, Any]
    implementation_order: List[str]
    fix_templates: Dict[str, Any]
    quality_gates: List[Dict[str, Any]]


class CodexSupervisor:
    """
    Codex 主管 Agent

    实际运行时由 Codex（外部 LLM）扮演，
    这里定义的是主管的接口契约和决策逻辑。
    """

    def __init__(self, agents_config: dict):
        self.agents_config = agents_config
        self.modules = self._load_module_registry()

    def parse_requirement(self, raw_text: str) -> Requirement:
        """
        解析自然语言需求

        实际由 Codex 完成，这里提供结构化输出格式。
        编译器推导的上下文策略可以指导 Codex 的解析。
        """
        return Requirement(raw_text=raw_text)

    def identify_modules(self, requirement: Requirement) -> List[ModuleTask]:
        """
        识别功能模块并匹配 Agent

        编译器推导的 context_strategies 可用于指导识别。
        """
        tasks = []
        for i, module in enumerate(requirement.functional_modules, 1):
            task = ModuleTask(
                module=module,
                priority=i,
                dependencies=self._get_dependencies(module),
            )
            tasks.append(task)
        return tasks

    def dispatch_tasks(self, tasks: List[ModuleTask],
                       compiled_pipeline: CompiledPipeline) -> Dict[str, Any]:
        """
        通过 Superpowers 分发任务

        使用编译器推导的 context_strategies 进行上下文注入。
        """
        dispatch_config = {}
        for task in tasks:
            strategy = compiled_pipeline.context_strategies.get(task.module, {})
            dispatch_config[task.module] = {
                "task": task,
                "context_strategy": strategy,
            }
        return dispatch_config

    def evaluate_review(self, review_results: List[Dict],
                        gate_results: List[Dict]) -> Dict[str, Any]:
        """
        评估代码审查结果

        综合:
          - 各模块审查是否通过
          - 质量门禁是否通过
          - 修复循环是否收敛
        """
        all_passed = all(r.get("verdict") == "pass" for r in review_results)
        has_critical = any(
            i.get("severity") == "critical"
            for r in review_results
            for i in r.get("issues", [])
        )

        return {
            "all_passed": all_passed,
            "has_critical": has_critical,
            "should_fix": not all_passed or has_critical,
            "gates_passed": all(g.get("passed", False) for g in gate_results),
        }

    def generate_fix_directive(self, fix_instructions: List[Dict]) -> str:
        """
        生成修复指令给 Claude Code

        使用编译器推导的 fix_templates 格式化修复指令。
        """
        lines = ["## 修复指令", ""]
        for inst in fix_instructions:
            lines.append(f"### [{inst.get('severity', 'unknown')}] {inst.get('module', 'unknown')}")
            lines.append(f"- 位置: {inst.get('location', 'unknown')}")
            lines.append(f"- 描述: {inst.get('description', '')}")
            lines.append(f"- 建议: {inst.get('suggested_fix', '')}")
            lines.append("")
        return "\n".join(lines)

    def _load_module_registry(self) -> Dict[str, Any]:
        """加载模块注册表"""
        agents = self.agents_config.get("agents", {})
        return {
            name: cfg for name, cfg in agents.items()
            if cfg.get("role") == "expert"
        }

    def _get_dependencies(self, module: str) -> List[str]:
        """获取模块依赖"""
        for name, cfg in self.modules.items():
            if cfg.get("module") == module:
                return cfg.get("dependencies", [])
        return []
