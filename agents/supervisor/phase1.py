# agents/supervisor/phase1.py

"""
Codex Supervisor — Phase 1 orchestration.

Phase 1 pipeline:
  1. Identify functional modules
  2. Dispatch to expert agents
  3. Build approval request
  4. Generate code (auto-approve or user-approved)
"""

import logging
import os
from typing import Any, Dict, Optional

from agents.supervisor.types import Requirement, ModuleTask, CompiledPipeline

logger = logging.getLogger(__name__)


def run_phase1(
    supervisor,  # CodexSupervisor instance (avoids circular import)
    requirement: Requirement,
    experts: Dict[str, Any],
    compiled_pipeline: CompiledPipeline,
    llm_provider=None,
    backend: Any = None,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """
    Phase 1: Requirement decomposition -> Expert analysis -> [Approval Gate] -> Code Generation.

    Args:
        supervisor: CodexSupervisor instance (provides _generate_code_for_modules, etc.)
        requirement: Structured requirement
        experts: Dict of {module_name: expert_agent}
        compiled_pipeline: Compiled pipeline configuration
        llm_provider: LLM Provider (defaults to AnthropicClaudeProvider)
        backend: ExecutionBackend instance (defaults to inline backend)
        auto_approve: If True, skip approval gate (batch mode)

    Returns:
        {
            "module_specs": {module_name: spec_dict},
            "code_artifact": {module_name: code_string},
            "dispatch_config": {module_name: dispatch_info},
            "approval_request": {...},
            "approved": bool,
        }
    """
    from agents.supervisor.agent_executor import (
        ClaudeCodeExecutor,
        ExecutionBackend,
        TaskSpec,
    )

    # Use provided backend or create default
    if backend is None:
        if llm_provider is None:
            try:
                from tools.llm.anthropic import AnthropicClaudeProvider
                llm_provider = AnthropicClaudeProvider()
            except (ValueError, ImportError) as e:
                raise RuntimeError(
                    f"Failed to initialize LLM provider for code generation: {e}. "
                    f"Set LLM_API_KEY environment variable or install required dependencies."
                ) from e

        from agents.supervisor.agent_executor import ExecutionBackend as _EB

        class _DefaultBackend(_EB):
            def __init__(self, provider) -> None:
                self._provider = provider

            def execute_task(self, task) -> Any:
                from agents.supervisor.agent_executor import TaskResult
                code = ClaudeCodeExecutor(self._provider).generate_code(
                    spec=task.spec, module_name=task.module_name
                )
                return TaskResult(
                    module_name=task.module_name,
                    success=bool(code),
                    code=code,
                )

            def get_name(self) -> str:
                return "default"

        backend = _DefaultBackend(llm_provider=llm_provider)

    # Validate backend interface
    if not isinstance(backend, ExecutionBackend):
        raise TypeError(
            f"backend must be an ExecutionBackend instance, got {type(backend).__name__}"
        )

    # Store llm_provider for conflict resolver
    supervisor._llm_provider = llm_provider

    # Computer use settings
    supervisor._computer_use_enabled = os.environ.get("COMPUTER_USE", "1") == "1"
    supervisor._computer_use_backend = os.environ.get("COMPUTER_USE_BACKEND", "codex")
    supervisor._computer_use_workdir = os.environ.get("COMPUTER_USE_WORKDIR", ".")

    logger.info("[Supervisor] 使用执行后端: %s", backend.get_name())

    # Step 1: Identify functional modules
    logger.info("[Supervisor] Phase 1 started -- identifying functional modules")
    tasks = supervisor.identify_modules(requirement)
    logger.info("[Supervisor] Identified %d modules: %s", len(tasks), [t.module for t in tasks])

    # Step 2: Dispatch tasks and collect specs
    dispatch_config = supervisor.dispatch_tasks(tasks, compiled_pipeline)
    module_specs: Dict[str, Any] = {}

    for task in tasks:
        module_name = task.module
        expert = experts.get(module_name)

        if expert is None:
            logger.warning("[Supervisor] No expert for module '%s', skipping", module_name)
            continue

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
        deps = supervisor._get_dependencies(module_name)
        approval_modules.append({
            "name": module_name,
            "components_count": comp_count,
            "interfaces_count": iface_count,
            "acceptance_criteria_count": len(spec.get("acceptance_criteria", [])),
            "confidence": spec.get("confidence", 0.0),
            "dependencies": deps,
            "reasoning": spec.get("reasoning", ""),
        })

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
        code_artifact = _generate_code_for_modules(
            supervisor, module_specs, backend, requirement
        )
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


def generate_code_for_modules(
    supervisor,
    module_specs: Dict[str, Any],
    backend: Any,
    requirement: Requirement,
    enable_conflict_resolution: bool = True,
) -> Dict[str, str]:
    """
    Generate code for all modules using ExecutionBackend.

    Args:
        supervisor: CodexSupervisor instance
        module_specs: {module_name: spec_dict}
        backend: ExecutionBackend instance
        requirement: Original requirement (for context)
        enable_conflict_resolution: If True, detect and resolve file-level conflicts

    Returns:
        {module_name: code_string}
    """
    return _generate_code_for_modules(supervisor, module_specs, backend, requirement, enable_conflict_resolution)


def _generate_code_for_modules(
    supervisor,
    module_specs: Dict[str, Any],
    backend: Any,
    requirement: Requirement,
    enable_conflict_resolution: bool = True,
) -> Dict[str, str]:
    """Internal: generate code with optional conflict resolution."""
    from agents.supervisor.agent_executor import TaskSpec, MergeCoordinator

    code_artifact: Dict[str, str] = {}
    logger.info("[Supervisor] Starting real code generation for %d modules...", len(module_specs))

    # Initialize conflict coordinator
    coordinator = MergeCoordinator(
        llm_provider=getattr(supervisor, '_llm_provider', None),
    ) if enable_conflict_resolution else None

    # Pre-register file targets based on module specs
    if coordinator:
        for module_name, spec in module_specs.items():
            file_path = _module_to_file_path(module_name)
            coordinator.register_target(module_name, file_path, is_primary=True)

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

            if coordinator:
                file_path = _module_to_file_path(module_name)
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
                file_path = _module_to_file_path(module_name)
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
            for module_name in module_specs:
                file_path = _module_to_file_path(module_name)
                if file_path in final_files:
                    code_artifact[module_name] = final_files[file_path]

    # Log code generation statistics
    total_lines = 0
    logger.info("Phase 1 -- Code Generation Statistics")
    logger.info("=" * 60)
    for module_name, code in code_artifact.items():
        lines = code.count("\n") + 1 if code else 0
        status = "OK" if code else "FAIL"
        logger.info("  [%s] %s: %d lines", status, module_name, lines)
        total_lines += lines
    success_count = len([c for c in code_artifact.values() if c])
    logger.info("  --------------------------------")
    logger.info("  Total: %d lines (%d/%d succeeded)", total_lines, success_count, len(code_artifact))
    logger.info("=" * 60)

    supervisor._last_conflict_report = conflict_report

    # Computer use: post-generation verification
    if enable_conflict_resolution and supervisor._computer_use_enabled:
        from agents.supervisor.agent_executor import ComputerUseOrchestrator, create_computer_use_backend
        cu_backend = create_computer_use_backend(
            supervisor._computer_use_backend or "codex",
            workdir=supervisor._computer_use_workdir or ".",
        )
        if cu_backend.available:
            logger.info("[Supervisor] Running computer use verification (backend=%s)...", cu_backend.name)
            orchestrator = ComputerUseOrchestrator(
                cu_backend, llm_provider=supervisor._llm_provider)
            computer_use_report = orchestrator.verify_and_fix(code_artifact)
            supervisor._last_computer_use_report = computer_use_report

            if computer_use_report.verified:
                logger.info("[ComputerUse] 验证通过 ✓")
            else:
                logger.warning("[ComputerUse] 验证失败: %s", computer_use_report.output)

    return code_artifact


def _module_to_file_path(module_name: str) -> str:
    """Convert a module name to its target file path."""
    return f"src/{module_name}/service.py"
