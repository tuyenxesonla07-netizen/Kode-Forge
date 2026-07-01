# agents/supervisor/__init__.py

"""
Codex Supervisor Agent -- the sole decision node with global responsibility.

Responsibilities:
  - Understand user requirements, extract core function points
  - Decompose requirements into module tasks
  - Dispatch tasks via Superpowers plugin
  - Aggregate agent outputs, deliver to Claude Code
  - Decide fix strategy when code review fails

Sub-modules:
  types            — shared dataclasses (Requirement, ModuleTask, CompiledPipeline)
  code_generation  — LLM code generation with AST validation
  phase1           — Phase 1 orchestration pipeline
"""

import logging
import os
from typing import Any, Dict, List, Optional

from typing import TYPE_CHECKING

from agents.supervisor.types import Requirement, ModuleTask, CompiledPipeline
from agents.supervisor.code_generation import generate_code as _generate_code_impl
from agents.supervisor.phase1 import run_phase1 as _run_phase1_impl
from agents.supervisor.phase1 import generate_code_for_modules as _generate_code_for_modules_impl
from agents.supervisor.phase1 import _module_to_file_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agents.pipeline import KodeForge

# Re-export types for backward compatibility
__all__ = [
    "Requirement",
    "ModuleTask",
    "CompiledPipeline",
    "CodexSupervisor",
]


class CodexSupervisor:
    """
    Codex Supervisor Agent.

    In production, played by Codex (external LLM).
    Here we define the supervisor's interface contract and decision logic.
    """

    def __init__(self, agents_config: dict) -> None:
        self.agents_config = agents_config
        self.modules = self._load_module_registry()

    # ── Requirement parsing ─────────────────────────────────────

    def parse_requirement(self, raw_text: str) -> Requirement:
        """Parse natural-language requirement. In reality done by Codex."""
        return Requirement(raw_text=raw_text)

    def identify_modules(self, requirement: Requirement) -> List[ModuleTask]:
        """Identify functional modules and match to agents."""
        tasks = []
        for i, module in enumerate(requirement.functional_modules, 1):
            task = ModuleTask(
                module=module,
                priority=i,
                dependencies=self._get_dependencies(module),
            )
            tasks.append(task)
        return tasks

    # ── Task dispatch ───────────────────────────────────────────

    def dispatch_tasks(self, tasks: List[ModuleTask],
                       compiled_pipeline: CompiledPipeline) -> Dict[str, Any]:
        """Dispatch tasks via Superpowers, using context_strategies for injection."""
        dispatch_config = {}
        for task in tasks:
            strategy = compiled_pipeline.context_strategies.get(task.module, {})
            dispatch_config[task.module] = {
                "task": task,
                "context_strategy": strategy,
            }
        return dispatch_config

    # ── Review evaluation ───────────────────────────────────────

    def evaluate_review(self, review_results: List[Dict],
                        gate_results: List[Dict]) -> Dict[str, Any]:
        """Evaluate code review results against quality gates."""
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
        """Generate fix directives for Claude Code using fix_templates."""
        lines = ["## Fix Directives", ""]
        for inst in fix_instructions:
            lines.append(f"### [{inst.get('severity', 'unknown')}] {inst.get('module', 'unknown')}")
            lines.append(f"- Location: {inst.get('location', 'unknown')}")
            lines.append(f"- Description: {inst.get('description', '')}")
            lines.append(f"- Suggestion: {inst.get('suggested_fix', '')}")
            lines.append("")
        return "\n".join(lines)

    # ── Code generation (delegates to code_generation module) ──

    def generate_code(
        self,
        module_spec: Dict[str, Any],
        llm_provider,
        module_name: str,
        input_schema: Dict[str, Any] = None,
        timeout: float = 120.0,
    ) -> str:
        """Generate production-ready Python code using the real LLM."""
        return _generate_code_impl(module_spec, llm_provider, module_name, timeout=timeout)

    # ── Phase 1 pipeline (delegates to phase1 module) ───────────

    def run_phase1(
        self,
        requirement: Requirement,
        experts: Dict[str, Any],
        compiled_pipeline: CompiledPipeline,
        llm_provider=None,
        backend: Any = None,
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """Phase 1: Requirement decomposition -> Expert analysis -> [Approval Gate] -> Code Generation."""
        return _run_phase1_impl(
            self, requirement, experts, compiled_pipeline,
            llm_provider=llm_provider, backend=backend, auto_approve=auto_approve,
        )

    def approve_and_generate(
        self,
        module_specs: Dict[str, Any],
        backend: Any,
        requirement: Requirement,
    ) -> Dict[str, str]:
        """After user approval, trigger code generation."""
        return _generate_code_for_modules_impl(self, module_specs, backend, requirement)

    # ── Helpers ─────────────────────────────────────────────────

    def _load_module_registry(self) -> Dict[str, Any]:
        """Load module registry from agents config."""
        agents = self.agents_config.get("agents", {})
        return {
            name: cfg for name, cfg in agents.items()
            if cfg.get("role") == "expert"
        }

    def _get_dependencies(self, module: str) -> List[str]:
        """Get dependencies for a module."""
        for name, cfg in self.modules.items():
            if cfg.get("module") == module:
                return cfg.get("dependencies", [])
        return []

    def get_last_conflict_report(self) -> Optional[Dict]:
        """Get the conflict report from the last code generation run."""
        return getattr(self, '_last_conflict_report', None)

    def get_last_computer_use_report(self) -> Any:
        """Get the computer use report from the last code generation run."""
        return getattr(self, '_last_computer_use_report', None)
