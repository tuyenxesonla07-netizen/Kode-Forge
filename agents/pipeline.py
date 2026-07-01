# agents/pipeline.py
"""
KodeForge — the full multi-agent pipeline orchestrator.

Integrates:
  Phase 1: Schema-driven requirement decomposition → code generation
  Phase 2: Code review → fix loop with convergence detection
  + Guardrails (injection/PII) + Memory + HITL + Workflow + Observability
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class KodeForge:
    """
    KodeForge Pipeline — Full Architecture.

    Usage:
        pipeline = KodeForge(
            config_dir="config",
            llm_backend="mock",
            enable_guardrails=True,
            enable_memory=True,
            enable_hitl=True,
            enable_observability=True,
        )

        # Phase 1: Generate code from requirement
        result = pipeline.run_phase1("Build auth module with JWT")
        print(result["code_artifact"])

        # Phase 2: Review and fix loop
        phase2 = pipeline.run_phase2(result["code_artifact"])
        print(f"Passed: {phase2['passed']}, Iterations: {phase2['iterations']}")
    """

    def __init__(
        self,
        config_dir: str = "config",
        llm_backend: str = "mock",
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        enable_guardrails: bool = True,
        enable_memory: bool = True,
        enable_hitl: bool = True,
        enable_observability: bool = True,
        hitl_mode: str = "auto",
        hitl_auto_under_risk: str = "medium",
        max_workers: int = 3,
    ):
        from tools.stores import StoreDatabase, RequirementStore, InterfaceStore, SpecStore
        from tools.workflow.messaging import MessageBus
        from tools.quality import QualityEvaluator
        from tools.guardrails import InputGuard, OutputGuard
        from tools.memory import Memory, SessionState
        from tools.hitl import AutoApprovalHandler, ManualApprovalHandler, AuditLog
        from tools.observability import Tracer, PipelineMetrics
        from tools.plugins import PluginSkillRegistry
        from tools.workflow import WorkflowEngine
        from agents.supervisor.agent_executor import write_code_artifacts, CodeWriterConfig
        from agents.experts import create_expert_agents

        # ── Core stores ──
        self._store_db = StoreDatabase()
        self.requirement_store = RequirementStore()
        self.interface_store = InterfaceStore()
        self.spec_store = SpecStore(db=self._store_db)
        self.message_bus = MessageBus()

        # ── LLM Provider ──
        from tools.llm import create_llm_provider

        if llm_backend == "mock" and os.environ.get("ANTHROPIC_API_KEY") and not llm_api_key:
            llm_backend = "anthropic"
            llm_api_key = os.environ["ANTHROPIC_API_KEY"]

        self.llm_backend = llm_backend
        if llm_backend == "anthropic":
            base_url = llm_base_url or os.environ.get("ANTHROPIC_BASE_URL")
            model = os.environ.get("ANTHROPIC_MODEL")
            try:
                provider_kwargs = {"api_key": llm_api_key, "base_url": base_url}
                if model:
                    provider_kwargs["model"] = model
                self.llm_provider = create_llm_provider(backend="anthropic", **provider_kwargs)
                test_response = self.llm_provider.complete("Hello", max_tokens=10, output_format="text")
                if not test_response.success:
                    logger.warning("[LLM] Anthropic provider failed (%s), falling back to mock", test_response.error)
                    self.llm_provider = create_llm_provider(backend="mock")
                    self.llm_backend = "mock (fallback)"
            except Exception as e:
                logger.warning("[LLM] Failed to create Anthropic provider (%s), falling back to mock", e)
                self.llm_provider = create_llm_provider(backend="mock")
                self.llm_backend = "mock (fallback)"
        elif llm_backend == "openai-compatible":
            self.llm_provider = create_llm_provider(backend=llm_backend, api_key=llm_api_key, base_url=llm_base_url)
        else:
            self.llm_provider = create_llm_provider(backend="mock")

        # ── Compiler ──
        from tools.compiler import PipelineCompiler

        self._pipeline_config = PipelineCompiler._load_pipeline_config(os.path.join(config_dir, "pipeline.yaml"))
        self.compiler = PipelineCompiler(
            requirement_store=self.requirement_store,
            interface_store=self.interface_store,
            spec_store=self.spec_store,
            message_bus=self.message_bus,
        )

        # ── Quality ──
        self.quality_evaluator = QualityEvaluator(message_bus=self.message_bus)

        # ── Guardrails ──
        self.enable_guardrails = enable_guardrails
        if enable_guardrails:
            self.input_guard = InputGuard(max_length=5000)
            self.output_guard = OutputGuard(strict=False)

        # ── Memory ──
        self.enable_memory = enable_memory
        if enable_memory:
            self.memory = Memory(session_id="default", persist_path="data/memory_store.json")
            self.session_state = SessionState()

        # ── HITL ──
        self.enable_hitl = enable_hitl
        self.max_workers = max_workers
        if enable_hitl:
            self.approval_handler = (
                AutoApprovalHandler(auto_under_risk=hitl_auto_under_risk)
                if hitl_mode == "auto"
                else ManualApprovalHandler()
            )
            self.audit_log = AuditLog(persist_path="data/audit_log.jsonl")

        # ── Observability ──
        self.enable_observability = enable_observability
        if enable_observability:
            self.tracer = Tracer("kodeforge_pipeline")
            self.metrics = PipelineMetrics()

        # ── Skills (Plugin-based) ──
        from tools.plugins import PluginSkillRegistry

        self.skill_manager = PluginSkillRegistry(plugins_dir=Path("plugins"))
        self.skill_manager.load()

        # ── Agents ──
        from agents.supervisor import CodexSupervisor, Requirement

        self.agents_config = self._load_agents_config(config_dir)
        self.supervisor = CodexSupervisor(self.agents_config)
        self.expert_agents = create_expert_agents(
            os.path.join(config_dir, "schemas"),
            agents_config=self.agents_config,
            llm_provider=self.llm_provider,
            skill_manager=self.skill_manager,
        )

        # ── Workflow Engine ──
        self.workflow_engine = WorkflowEngine()

        # ── Code Writer ──
        self._code_writer_config = CodeWriterConfig()

        # ── Phase methods (composition over inheritance) ──
        # Phase1Pipeline and Phase2Pipeline methods use `self` — bind them here
        # so they operate on this instance without multi-inheritance MRO issues.
        import types
        from agents.pipeline_phase1 import Phase1Pipeline
        from agents.pipeline_phase2 import Phase2Pipeline
        for _cls in (Phase1Pipeline, Phase2Pipeline):
            for _name, _fn in vars(_cls).items():
                if callable(_fn) and not _name.startswith("__"):
                    setattr(self, _name, types.MethodType(_fn, self))

    def compile_pipeline(self, module_schemas, input_schemas=None) -> CompiledPipeline:
        return self.compiler.compile(
            module_schemas,
            input_schemas=input_schemas,
            agents_config=self.agents_config,
            pipeline_config=self._pipeline_config,
        )

    def run_full_pipeline(self, user_requirement) -> dict:
        """Run Phase 1 + Phase 2 as a single end-to-end pipeline.

        V0.5.0: 保留旧 Phase1+Phase2 路径（完整功能：编译/代码生成/质量审查/文件写入）。
        AgentOrchestrator 路径通过 generate_code() 的新选项或 AgentConversationManager 使用。
        """
        # Guardrails 注入检测
        if self.enable_guardrails and hasattr(self, 'input_guard') and self.input_guard is not None:
            guard_result = self.input_guard.check(user_requirement)
            if not guard_result.passed:
                return {"status": "blocked", "reason": guard_result.reason or "Security violation detected"}

        return self._run_legacy_pipeline(user_requirement)

    def run_full_pipeline_v2(self, user_requirement, conversation_id: str = "") -> dict:
        """V0.5.0 新路径：通过 AgentOrchestrator 执行。

        适用于对话式交互场景。返回格式与 run_full_pipeline 兼容。
        """
        from agents.runtime.orchestrator import AgentOrchestrator, AgentOrchestratorConfig
        from agents.runtime.state import StopReason

        # Guardrails 注入检测
        if self.enable_guardrails and hasattr(self, 'input_guard') and self.input_guard is not None:
            guard_result = self.input_guard.check(user_requirement)
            if not guard_result.passed:
                return {"status": "blocked", "reason": guard_result.reason or "Security violation detected"}

        config = AgentOrchestratorConfig(
            max_steps=10,
            llm_provider=self.llm_provider,
            skill_registry=self.skill_manager,
        )
        orchestrator = AgentOrchestrator(config=config)
        state = orchestrator.run_agent_sync(user_requirement, conversation_id=conversation_id)

        return {
            "status": "success" if state.stop_reason == StopReason.ANSWERED else state.stop_reason,
            "intent": state.intent,
            "reply": state.reply,
            "trace": state.trace,
            "history": [{"role": m.role, "content": m.content} for m in state.history],
            "tool_history_count": len(state.tool_history),
            "step_count": state.step_count,
            "phase1": {"intent": state.intent, "reply": state.reply},
            "phase2": {"passed": state.stop_reason == StopReason.ANSWERED},
            "written_files": [],
        }

    def _run_legacy_pipeline(self, user_requirement) -> dict:
        """旧 Phase1+Phase2 路径（保留为 fallback）。"""
        root_span = self.tracer.span("full_pipeline") if self.enable_observability else None

        try:
            phase1_result = self.run_phase1(user_requirement)

            if phase1_result.get("blocked"):
                return {"status": "blocked", "reason": phase1_result["reason"], "phase1": phase1_result, "phase2": None}
            if phase1_result.get("awaiting_approval"):
                return {
                    "status": "awaiting_approval", "reason": phase1_result["reason"],
                    "phase1": phase1_result, "phase2": None,
                }

            phase2_result = self.run_phase2(phase1_result["code_artifact"], phase1_result["compiled"])

            written_files = []
            if phase1_result.get("code_artifact"):
                try:
                    written_files = write_code_artifacts(phase1_result["code_artifact"], self._code_writer_config)
                    logger.info("[Pipeline] Wrote %d code files", len(written_files))
                except Exception as e:
                    logger.error("[Pipeline] Code writer failed: %s", e)

            if root_span:
                root_span["attributes"]["phase1_modules"] = len(phase1_result["code_artifact"])
                root_span["attributes"]["phase2_passed"] = phase2_result["passed"]
                root_span["attributes"]["phase2_iterations"] = phase2_result["iterations"]
                root_span["attributes"]["files_written"] = len(written_files)
                root_span["status"] = "ok"

            return {
                "status": "success", "phase1": phase1_result, "phase2": phase2_result,
                "written_files": written_files,
                "observability": self.get_observability_summary() if self.enable_observability else None,
                "audit_summary": self.audit_log.summary() if self.enable_hitl else None,
            }

        except Exception as e:
            if root_span:
                root_span["status"] = "error"
                root_span["attributes"]["error"] = f"{type(e).__name__}: {e}"
            raise

    async def _execute_workflow_async(self, workflow_id, input_data) -> str:
        """Execute workflow asynchronously and wait for completion."""
        import asyncio
        run_id = await self.workflow_engine.execute_async(
            workflow_id, input_data,
            context={"llm_provider": self.llm_provider, "agent_registry": self.expert_agents},
        )
        while True:
            result = self.workflow_engine.get_run_result(run_id)
            if result and result.status != "running":
                return run_id
            await asyncio.sleep(0.01)

    def run_eval(self, cases=None, verbose=True) -> EvalReport:
        """Run behavioral evaluation suite."""
        from tools.eval import EvalRunner, EVAL_CASES

        runner = EvalRunner(verbose=verbose)
        selected_cases = cases or EVAL_CASES
        report = runner.run_all(cases=selected_cases, verbose=verbose)

        if self.enable_hitl:
            self.audit_log.record({
                "tool": "eval_suite", "action": "run",
                "total_cases": report.cases_total, "passed": report.cases_passed,
                "pass_rate": report.pass_rate, "risk": "low",
                "ok": report.pass_percentage >= 60,
            })
        return report

    def get_observability_summary(self) -> dict:
        """Get full observability summary for the last pipeline run."""
        if not self.enable_observability:
            return {}
        return {
            "trace": self.tracer.to_dict(),
            "metrics": self.metrics.to_dict(),
            "trace_tree": self.tracer.render_tree(),
        }

    # ── Private helpers ──────────────────────────────────────────────────────

    def _load_agents_config(self, config_dir) -> dict:
        try:
            import yaml
        except ImportError:
            logger.warning("pyyaml not installed, agents config will be empty")
            return {}
        agents_path = os.path.join(config_dir, "agents.yaml")
        if os.path.exists(agents_path):
            with open(agents_path, "r", encoding="utf-8") as f:
                content = f.read()
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
                return yaml.safe_load("\n".join(yaml_lines)) if yaml_lines else {}
        return {}

    def _load_schemas(self) -> tuple:
        schemas_dir = os.path.join(os.path.dirname(__file__), "..", "config", "schemas")
        input_schemas = {}
        output_schemas = {}
        if os.path.exists(schemas_dir):
            for filename in os.listdir(schemas_dir):
                path = os.path.join(schemas_dir, filename)
                with open(path, encoding="utf-8") as f:
                    schema = json.load(f)
                if filename.endswith("_input.json"):
                    module = filename.replace("_input.json", "")
                    input_schemas[module] = schema
                elif filename.endswith("_output.json"):
                    module = filename.replace("_output.json", "")
                    output_schemas[module] = schema
        return input_schemas, output_schemas

    _MODULE_NAME_MAP = {
        "authentication": "authentication",
        "data_processing": "data_processing",
        "api_integration": "api_integration",
    }

    @classmethod
    def _module_to_short_name(cls, full_name: str) -> str:
        return cls._MODULE_NAME_MAP.get(full_name, full_name)

    def _build_expert_input(self, module_name, input_schema, strategy, compiled, processed_specs=None) -> ExpertInput:
        from agents.experts import ExpertInput

        requirement_text = input_schema.get("description", module_name)
        constraints = []
        dependency_interfaces = {}
        if input_schema.get("properties"):
            props = input_schema["properties"]
            if "constraints" in props:
                constraints = props["constraints"].get("default", [])
            if "security_requirements" in props:
                constraints.extend(props["security_requirements"].get("default", []))
            if "compliance_requirements" in props:
                constraints.extend(props["compliance_requirements"].get("default", []))
        if strategy and strategy.needs_dependency_interfaces:
            deps = strategy.depends_on
            for dep in deps:
                # First try: get from already-processed module specs (in-memory)
                if processed_specs and dep in processed_specs:
                    dep_spec = processed_specs[dep]
                    if hasattr(dep_spec, 'interfaces'):
                        dependency_interfaces[dep] = dep_spec.interfaces
                    elif isinstance(dep_spec, dict):
                        dependency_interfaces[dep] = dep_spec.get('interfaces', [])
                # Fallback: try the interface store
                if dep not in dependency_interfaces:
                    dep_interfaces = self.interface_store.get_for_injection(dep)
                    if dep_interfaces:
                        dependency_interfaces[dep] = dep_interfaces
        return ExpertInput(
            module_name=module_name,
            requirement=requirement_text,
            constraints=constraints,
            dependency_interfaces=dependency_interfaces,
            global_constraints={
                "language": "Python 3.12",
                "framework": "FastAPI",
                "coding_style": "Google Python Style Guide",
            },
        )

    def _has_sqlite_stores(self) -> bool:
        """Check if any stores use SQLite (not thread-safe)."""
        try:
            store_db = getattr(self, "_store_db", None)
            if store_db is not None:
                import sqlite3
                if isinstance(store_db, sqlite3.Connection):
                    return True
                # Check for DatabaseWrapper with sqlite connection
                conn = getattr(store_db, "connection", None) or getattr(store_db, "_connection", None)
                if isinstance(conn, sqlite3.Connection):
                    return True
        except Exception as e:
            logger.warning("SQLite store detection failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Layer 1 + Layer 2 Public API
# ---------------------------------------------------------------------------

def generate_code(
    requirement: str,
    config_dir: str = "config",
    llm_backend: str = "mock",
    llm_api_key: Optional[str] = None,
    llm_base_url: Optional[str] = None,
    enable_guardrails: bool = True,
) -> Dict[str, Any]:
    """One-liner code generation.

    Args:
        requirement: Natural language requirement description
        config_dir: Path to config directory with schemas/ and agents.yaml
        llm_backend: LLM provider ("mock", "anthropic", "openai-compatible")
        llm_api_key: API key (optional, reads from env vars)
        llm_base_url: Custom LLM endpoint URL
        enable_guardrails: Whether to run input/output security checks

    Returns:
        Dict with keys: status, code_artifact, module_specs, quality_score
    """
    pipeline = _create_pipeline(
        config_dir=config_dir,
        llm_backend=llm_backend,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        enable_guardrails=enable_guardrails,
    )
    return pipeline.run(requirement)


class Pipeline:
    """Standard pipeline interface.

    Usage:
        pipe = Pipeline(config_dir="config", llm_backend="mock")
        result = pipe.run("Build auth module with JWT")
        print(result["code_artifact"])
    """

    def __init__(
        self,
        config_dir: str = "config",
        llm_backend: str = "mock",
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        enable_guardrails: bool = True,
        enable_memory: bool = True,
        enable_hitl: bool = True,
        enable_observability: bool = True,
        hitl_mode: str = "auto",
        max_workers: int = 3,
    ):
        self.config_dir = config_dir
        self.llm_backend = llm_backend
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url
        self.enable_guardrails = enable_guardrails
        self.enable_memory = enable_memory
        self.enable_hitl = enable_hitl
        self.enable_observability = enable_observability
        self.hitl_mode = hitl_mode
        self.max_workers = max_workers

        # Lazy-init the heavy pipeline
        self._inner: Any = None

    @property
    def inner(self) -> "KodeForge":
        if self._inner is None:
            self._inner = KodeForge(
                config_dir=self.config_dir,
                llm_backend=self.llm_backend,
                llm_api_key=self.llm_api_key,
                llm_base_url=self.llm_base_url,
                enable_guardrails=self.enable_guardrails,
                enable_memory=self.enable_memory,
                enable_hitl=self.enable_hitl,
                enable_observability=self.enable_observability,
                hitl_mode=self.hitl_mode,
                max_workers=self.max_workers,
            )
        return self._inner

    def run(self, requirement: str) -> Dict[str, Any]:
        """Run the full pipeline (Phase 1 + Phase 2).

        Args:
            requirement: Natural language requirement

        Returns:
            Dict with: status, code_artifact, module_specs, quality_score, iterations
        """
        return self.inner.run_full_pipeline(requirement)

    def compile_only(self, requirement: str) -> Dict[str, Any]:
        """Only run compilation (no code generation).

        Returns:
            Dict with: compiled pipeline, modules, implementation_order
        """
        compiled = self.inner.compile_pipeline(self.inner._load_schemas()[1])
        return {
            "compiled": compiled,
            "modules": compiled.implementation_order,
            "parallel_groups": compiled.dependency_graph.get_parallel_groups(),
            "context_strategies": {
                name: strategy
                for name, strategy in compiled.context_strategies.items()
            },
        }

    def run_phase1(self, requirement: str) -> Dict[str, Any]:
        """Run Phase 1 only (requirement → module specs → code)."""
        return self.inner.run_phase1(requirement)

    def run_phase2(self, code_artifact: Dict, compiled_pipeline: Any = None) -> Dict[str, Any]:
        """Run Phase 2 only (code review → fix loop)."""
        return self.inner.run_phase2(code_artifact, compiled_pipeline)

    def get_observability(self) -> Dict[str, Any]:
        """Get observability summary from the last run."""
        return self.inner.get_observability_summary()


def _create_pipeline(
    config_dir: str,
    llm_backend: str,
    llm_api_key: Optional[str],
    llm_base_url: Optional[str],
    enable_guardrails: bool,
) -> Pipeline:
    """Helper to create a Pipeline instance."""
    return Pipeline(
        config_dir=config_dir,
        llm_backend=llm_backend,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        enable_guardrails=enable_guardrails,
    )
