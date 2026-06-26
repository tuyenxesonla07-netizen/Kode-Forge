# agents/supervisor/__init__.py

"""
Codex Supervisor Agent -- the sole decision node with global responsibility.

Responsibilities:
  - Understand user requirements, extract core function points
  - Decompose requirements into module tasks
  - Dispatch tasks via Superpowers plugin
  - Aggregate agent outputs, deliver to Claude Code
  - Decide fix strategy when code review fails
"""

import ast
import logging
import os
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field


@dataclass
class Requirement:
    """Structured requirement"""
    functional_modules: List[str] = field(default_factory=list)
    non_functional: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    priority: str = "medium"
    raw_text: str = ""


@dataclass
class ModuleTask:
    """Module task"""
    module: str
    priority: int = 1
    dependencies: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledPipeline:
    """Compiled pipeline configuration"""
    context_strategies: Dict[str, Any]
    implementation_order: List[str]
    fix_templates: Dict[str, Any]
    quality_gates: List[Dict[str, Any]]


class CodexSupervisor:
    """
    Codex Supervisor Agent.

    In production, played by Codex (external LLM).
    Here we define the supervisor's interface contract and decision logic.
    """

    def __init__(self, agents_config: dict):
        self.agents_config = agents_config
        self.modules = self._load_module_registry()

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

    def _load_module_registry(self) -> Dict[str, Any]:
        """Load module registry from agents config."""
        agents = self.agents_config.get("agents", {})
        return {
            name: cfg for name, cfg in agents.items()
            if cfg.get("role") == "expert"
        }

    def generate_code(
        self,
        module_spec: Dict[str, Any],
        llm_provider,
        module_name: str,
        input_schema: Dict[str, Any] = None,
    ) -> str:
        """Generate production-ready Python code using the real LLM. Validates with ast.parse()."""
        try:
            from tools.agent import ClaudeCodeExecutor

            executor = ClaudeCodeExecutor(llm_provider=llm_provider)
            code = executor.generate_code(spec=module_spec, module_name=module_name)
            return code
        except (ImportError, RuntimeError) as e:
            logger.warning("[Supervisor] ClaudeCodeExecutor not available (%s), falling back to inline", e)
            return self._generate_code_inline(module_spec, llm_provider, module_name)

    def _generate_code_inline(
        self,
        module_spec: Dict[str, Any],
        llm_provider,
        module_name: str,
    ) -> str:
        """Inline code generation fallback."""
        try:
            components = module_spec.get("components", [])
            interfaces = module_spec.get("interfaces", [])
            acceptance_criteria = module_spec.get("acceptance_criteria", [])

            spec_lines = []
            for comp in components:
                if isinstance(comp, dict):
                    spec_lines.append(f'- {comp.get("name", "?")} ({comp.get("type", "?")}): {comp.get("description", "")}')
                else:
                    spec_lines.append(f"- {comp}")

            interface_lines = []
            for iface in interfaces:
                if isinstance(iface, dict):
                    interface_lines.append(f'- {iface.get("name", "?")} {iface.get("method", "?")} {iface.get("path", "?")}')
                else:
                    interface_lines.append(f"- {iface}")

            criteria_lines = [f"- {c}" for c in acceptance_criteria]

            prompt_parts = [
                f"You are a senior Python developer. Generate production-ready code for the '{module_name}' module.",
                "",
                "## Module Specification",
                "Components:",
            ] + spec_lines + [
                "",
                "Interfaces:",
            ] + interface_lines + [
                "",
                "Acceptance Criteria:",
            ] + criteria_lines + [
                "",
                "## Requirements",
                "- Valid, parseable Python 3.12+ code with type hints and docstrings",
                "- Follow Google Python Style Guide",
                "- Use FastAPI framework",
                "- Implement ALL acceptance criteria listed above",
                "- Include proper error handling and logging",
                "- Output ONLY the Python code. No markdown fences, no explanation.",
            ]
            prompt = "\n".join(prompt_parts)

            system_prompt = (
                "You are an expert Python code generator. "
                "Generate complete, runnable Python code. "
                "Output ONLY raw Python code -- no markdown, no explanation, no code fences."
            )

            response = llm_provider.complete(
                prompt=prompt,
                system_prompt=system_prompt,
                output_format="text",
                max_tokens=8192,
                temperature=0.2,
            )

            if not response.success or not response.content:
                logger.warning("[Supervisor] LLM generation failed for %s: %s", module_name, response.error)
                return ""

            code = response.content.strip()
            if code.startswith("```"):
                parts = code.split("\n", 1)
                if len(parts) > 1:
                    code = parts[1]
                else:
                    code = code[3:]
                if code.endswith("```"):
                    code = code[:-3]
                code = code.strip()

            try:
                ast.parse(code)
            except SyntaxError as e:
                logger.warning(
                    "[Supervisor] AST validation failed for %s: %s (response length: %d)",
                    module_name, e, len(response.content or ""),
                )
                return ""

            logger.info("[Supervisor] Generated %d lines for %s", code.count("\n") + 1, module_name)
            return code

        except Exception as exc:
            logger.error("[Supervisor] Code gen error for %s: %s", module_name, exc)
            return ""

    def run_phase1(
        self,
        requirement: Requirement,
        experts: Dict[str, Any],
        compiled_pipeline: CompiledPipeline,
        llm_provider=None,
        backend: Any = None,
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """
        Phase 1: Requirement decomposition -> Expert analysis -> [Approval Gate] -> Code Generation.

        Steps:
          1. Identify functional modules
          2. Dispatch to expert agents in parallel (simulated sequentially here)
          3. Collect module specs from experts
          4. Build approval request (module decomposition, confidence, dependencies)
          5. If auto_approve=False, return approval_request for user review
          6. If auto_approve=True or after user approval, generate code via ExecutionBackend

        Args:
            requirement: Structured requirement
            experts: Dict of {module_name: expert_agent}
            compiled_pipeline: Compiled pipeline configuration
            llm_provider: LLM Provider (defaults to DayueAIProvider)
            backend: ExecutionBackend instance (defaults to ClaudeCodeBackend)
            auto_approve: If True, skip approval gate (batch mode)

        Returns:
            {
                "module_specs": {module_name: spec_dict},
                "code_artifact": {module_name: code_string},  # empty if awaiting approval
                "dispatch_config": {module_name: dispatch_info},
                "approval_request": {  # present when approval needed
                    "modules": [{name, components_count, interfaces_count, confidence, dependencies}],
                    "total_components": int,
                    "total_interfaces": int,
                    "estimated_tokens": int,
                },
                "approved": bool,
            }
        """
        from tools.agent import ClaudeCodeExecutor, ExecutionBackend, TaskSpec

        # Use provided backend or create default ClaudeCodeBackend
        if backend is None:
            if llm_provider is None:
                try:
                    from tools.agent.claude_code import DayueAIProvider
                    llm_provider = DayueAIProvider()
                except (ValueError, ImportError) as e:
                    raise RuntimeError(
                        f"Failed to initialize LLM provider for code generation: {e}. "
                        f"Set LLM_API_KEY environment variable or install required dependencies."
                    ) from e

            from tools.agent.claude_code_backend import ClaudeCodeBackend
            backend = ClaudeCodeBackend(llm_provider=llm_provider)

        # Validate backend interface
        if not isinstance(backend, ExecutionBackend):
            raise TypeError(
                f"backend must be an ExecutionBackend instance, got {type(backend).__name__}"
            )

        # Store llm_provider for conflict resolver (used in code generation)
        self._llm_provider = llm_provider

        # Computer use settings (can be overridden via env or config)
        self._computer_use_enabled = os.environ.get("COMPUTER_USE", "1") == "1"
        self._computer_use_backend = os.environ.get("COMPUTER_USE_BACKEND", "codex")
        self._computer_use_workdir = os.environ.get("COMPUTER_USE_WORKDIR", ".")

        logger.info("[Supervisor] 使用执行后端: %s", backend.get_name())

        # Step 1: Identify functional modules
        logger.info("[Supervisor] Phase 1 started -- identifying functional modules")
        tasks = self.identify_modules(requirement)
        logger.info("[Supervisor] Identified %d modules: %s", len(tasks), [t.module for t in tasks])

        # Step 2: Dispatch tasks and collect specs
        dispatch_config = self.dispatch_tasks(tasks, compiled_pipeline)
        module_specs: Dict[str, Any] = {}

        for task in tasks:
            module_name = task.module
            expert = experts.get(module_name)

            if expert is None:
                logger.warning("[Supervisor] No expert for module '%s', skipping", module_name)
                continue

            # Build expert input and call process
            try:
                from agents.experts import ExpertInput
                expert_input = ExpertInput(
                    module_name=module_name,
                    requirement=requirement.raw_text,
                    constraints=requirement.constraints,
                    dependency_interfaces=task.context.get("dependency_interfaces", {}),
                    global_constraints={},
                )
                expert_output = expert.process(expert_input)
                spec = {
                    "module_name": expert_output.module_name,
                    "components": expert_output.components,
                    "interfaces": expert_output.interfaces,
                    "acceptance_criteria": expert_output.acceptance_criteria,
                    "state_machine": expert_output.state_machine,
                    "confidence": expert_output.confidence,
                    "reasoning": expert_output.reasoning,
                }
                module_specs[module_name] = spec
                logger.info(
                    "[Supervisor] Expert '%s' analysis complete: %d components, %d interfaces",
                    module_name,
                    len(spec.get("components", [])),
                    len(spec.get("interfaces", [])),
                )
            except Exception as e:
                logger.error("[Supervisor] Expert '%s' analysis failed: %s", module_name, e)

        # Step 3: Build approval request
        approval_modules = []
        total_components = 0
        total_interfaces = 0
        for module_name, spec in module_specs.items():
            comp_count = len(spec.get("components", []))
            iface_count = len(spec.get("interfaces", []))
            total_components += comp_count
            total_interfaces += iface_count
            deps = self._get_dependencies(module_name)
            approval_modules.append({
                "name": module_name,
                "components_count": comp_count,
                "interfaces_count": iface_count,
                "acceptance_criteria_count": len(spec.get("acceptance_criteria", [])),
                "confidence": spec.get("confidence", 0.0),
                "dependencies": deps,
                "reasoning": spec.get("reasoning", ""),
            })

        # Estimate tokens: ~50 tokens per component/interface, ~20 per acceptance criterion
        estimated_tokens = total_components * 50 + total_interfaces * 50 + sum(
            len(spec.get("acceptance_criteria", [])) * 20 for spec in module_specs.values()
        )

        approval_request = {
            "modules": approval_modules,
            "total_components": total_components,
            "total_interfaces": total_interfaces,
            "estimated_tokens": estimated_tokens,
            "backend": backend.get_name(),
        }

        # Step 4: Auto-approve or pause for user review
        if auto_approve:
            logger.info("[Supervisor] Auto-approval enabled, proceeding to code generation")
            code_artifact = self._generate_code_for_modules(module_specs, backend, requirement)
            return {
                "module_specs": module_specs,
                "code_artifact": code_artifact,
                "dispatch_config": dispatch_config,
                "approval_request": approval_request,
                "approved": True,
            }

        logger.info(
            "[Supervisor] Phase 1 analysis complete. Awaiting user approval (%d modules, ~%d tokens)",
            len(approval_modules), estimated_tokens,
        )
        return {
            "module_specs": module_specs,
            "code_artifact": {},
            "dispatch_config": dispatch_config,
            "approval_request": approval_request,
            "approved": False,
        }

    def _generate_code_for_modules(
        self,
        module_specs: Dict[str, Any],
        backend: Any,
        requirement: Requirement,
        enable_conflict_resolution: bool = True,
    ) -> Dict[str, str]:
        """
        Generate code for all modules using ExecutionBackend.

        Args:
            module_specs: {module_name: spec_dict}
            backend: ExecutionBackend instance
            requirement: Original requirement (for context)
            enable_conflict_resolution: If True, detect and resolve file-level conflicts

        Returns:
            {module_name: code_string} — if conflicts resolved, some module names
            may share the same code (from merged files)
        """
        from tools.agent import TaskSpec, MergeCoordinator

        code_artifact: Dict[str, str] = {}
        logger.info("[Supervisor] Starting real code generation for %d modules...", len(module_specs))

        # Initialize conflict coordinator
        coordinator = MergeCoordinator(
            llm_provider=getattr(self, '_llm_provider', None),
        ) if enable_conflict_resolution else None

        # Pre-register file targets based on module specs
        if coordinator:
            for module_name, spec in module_specs.items():
                # Each module generates its own primary file
                file_path = self._module_to_file_path(module_name)
                coordinator.register_target(module_name, file_path, is_primary=True)

                # Register shared files from interfaces
                for iface in spec.get("interfaces", []):
                    if isinstance(iface, dict) and iface.get("shared_file"):
                        shared_path = iface["shared_file"]
                        coordinator.register_target(module_name, shared_path, is_primary=False)

        # Generate code for each module
        for module_name, spec in module_specs.items():
            logger.info("[Supervisor] Generating code for module '%s'...", module_name)

            task = TaskSpec(
                module_name=module_name,
                spec=spec,
                requirement=requirement.raw_text,
                constraints=requirement.constraints,
                context={},
            )
            result = backend.execute_task(task)

            if result.success and result.code:
                code_artifact[module_name] = result.code
                lines = result.code.count("\n") + 1
                logger.info("[Supervisor] Module '%s' code generated: %d lines", module_name, lines)

                # Register generation with conflict detector
                if coordinator:
                    file_path = self._module_to_file_path(module_name)
                    coordinator.register_generation(
                        file_path=file_path,
                        module_name=module_name,
                        code=result.code,
                        success=True,
                    )
            else:
                logger.warning("[Supervisor] Module '%s' code generation failed: %s",
                               module_name, result.error or "Unknown error")
                code_artifact[module_name] = ""

                if coordinator:
                    file_path = self._module_to_file_path(module_name)
                    coordinator.register_generation(
                        file_path=file_path,
                        module_name=module_name,
                        code="",
                        success=False,
                        error=result.error,
                    )

        # Detect and resolve conflicts
        conflict_report = None
        if coordinator and len(module_specs) > 1:
            logger.info("[Supervisor] Checking for file-level conflicts...")
            final_files = coordinator.resolve_all()
            conflict_report = coordinator.get_resolution_report()

            if conflict_report["resolutions"]:
                logger.info(
                    "[Supervisor] Conflict resolution report: %s",
                    conflict_report["resolutions"],
                )
                # Map resolved files back to modules
                for module_name in module_specs:
                    file_path = self._module_to_file_path(module_name)
                    if file_path in final_files:
                        code_artifact[module_name] = final_files[file_path]

        # Print code generation statistics
        total_lines = 0
        print("\n" + "=" * 60)
        print("  Phase 1 -- Code Generation Statistics")
        print("=" * 60)
        for module_name, code in code_artifact.items():
            lines = code.count("\n") + 1 if code else 0
            status = "OK" if code else "FAIL"
            print(f"  [{status}] {module_name}: {lines} lines")
            total_lines += lines
        print(f"  --------------------------------")
        success_count = len([c for c in code_artifact.values() if c])
        print(f"  Total: {total_lines} lines ({success_count}/{len(code_artifact)} succeeded)")
        print("=" * 60 + "\n")

        # Store conflict report for caller
        self._last_conflict_report = conflict_report

        # ── Computer Use: Post-generation verification ──
        computer_use_report = None
        if enable_conflict_resolution and self._computer_use_enabled:
            from tools.agent import ComputerUseOrchestrator, create_computer_use_backend
            backend = create_computer_use_backend(
                self._computer_use_backend or "codex",
                workdir=self._computer_use_workdir or ".",
            )
            if backend.available:
                logger.info("[Supervisor] Running computer use verification (backend=%s)...", backend.name)
                orchestrator = ComputerUseOrchestrator(
                    backend, llm_provider=self._llm_provider)
                computer_use_report = orchestrator.verify_and_fix(code_artifact)
                self._last_computer_use_report = computer_use_report

                if computer_use_report.verified:
                    logger.info("[ComputerUse] 验证通过 ✓")
                else:
                    logger.warning("[ComputerUse] 验证失败: %s", computer_use_report.output)

        return code_artifact

    def get_last_conflict_report(self) -> Optional[Dict]:
        """Get the conflict report from the last code generation run."""
        return getattr(self, '_last_conflict_report', None)

    @staticmethod
    def _module_to_file_path(module_name: str) -> str:
        """Convert a module name to its target file path."""
        # Convention: module_name -> src/{module_name}/service.py
        return f"src/{module_name}/service.py"

    def approve_and_generate(
        self,
        module_specs: Dict[str, Any],
        backend: Any,
        requirement: Requirement,
    ) -> Dict[str, str]:
        """
        After user approval, trigger code generation.

        This is the entry point for the approval callback — separates the
        analysis/review cycle from code generation so the user can inspect
        the decomposition before committing LLM tokens.
        """
        return self._generate_code_for_modules(module_specs, backend, requirement)

    def get_last_computer_use_report(self):
        """Get the computer use report from the last code generation run."""
        return getattr(self, '_last_computer_use_report', None)

    def _get_dependencies(self, module: str) -> List[str]:
        """Get dependencies for a module."""
        for name, cfg in self.modules.items():
            if cfg.get("module") == module:
                return cfg.get("dependencies", [])
        return []
