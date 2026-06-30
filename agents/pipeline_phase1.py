# agents/pipeline_phase1.py
"""
Phase 1 pipeline logic — requirement decomposition → expert analysis → code generation.

This module is mixed into KodeForge via composition.
Do not import directly; use KodeForge instead.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict

logger = logging.getLogger(__name__)


class Phase1Pipeline:
    """Phase 1 logic — attached to KodeForge via composition."""

    def run_phase1(self, user_requirement):
        """Phase 1: Requirement → Module Specs → Code Generation."""
        from tools.observability import Tracer, PipelineMetrics

        root_span = self.tracer.span("phase1", input_preview=user_requirement[:80]) if self.enable_observability else None

        try:
            # ── Step 0: Guardrails — input check ──
            if self.enable_guardrails:
                guard_span = self.tracer.span("input_guard") if self.enable_observability else None
                guard_result = self.input_guard.check(user_requirement)
                if guard_span:
                    guard_span["attributes"]["passed"] = guard_result.passed
                    guard_span["attributes"]["pii_found"] = guard_result.pii_found

                if not guard_result.passed:
                    logger.warning("[Guardrails] Input blocked: %s", guard_result.reason)
                    if self.enable_hitl:
                        self.audit_log.record({
                            "tool": "input_guard", "action": "blocked",
                            "reason": guard_result.reason, "risk": "high", "blocked": True,
                        })
                    return {
                        "blocked": True, "reason": guard_result.reason,
                        "compiled": None, "module_specs": {}, "code_artifact": {},
                    }
                user_requirement = guard_result.text
                if guard_result.pii_found:
                    logger.info("[Guardrails] PII masked: %s", guard_result.pii_found)
                if guard_span:
                    guard_span["status"] = "ok"

            # ── Step 0.5: Memory ──
            memory_context = ""
            if self.enable_memory:
                mem_span = self.tracer.span("memory_load") if self.enable_observability else None
                memory_context = self.memory.context_for_prompt()
                self.memory.save_interaction("user", user_requirement)
                if mem_span:
                    mem_span["attributes"]["context_length"] = len(memory_context)
                    mem_span["status"] = "ok"

            # ── Step 1: Parse requirement + compile pipeline ──
            compile_span = self.tracer.span("compile_pipeline") if self.enable_observability else None
            from agents.supervisor import Requirement

            requirement = self.supervisor.parse_requirement(user_requirement)
            input_schemas, output_schemas = self._load_schemas()
            compiled = self.compile_pipeline(output_schemas, input_schemas=input_schemas)
            if compile_span:
                compile_span["attributes"]["modules"] = len(compiled.implementation_order)
                compile_span["attributes"]["order"] = compiled.implementation_order
                compile_span["status"] = "ok"

            # ── Step 2: HITL — Approval gate ──
            if self.enable_hitl:
                approval_span = self.tracer.span("approval_gate") if self.enable_observability else None
                approval_result = self.approval_handler.request_approval(
                    tool_name="generate_code",
                    args={"modules": compiled.implementation_order},
                    risk_level="medium",
                    context={"module_count": len(compiled.implementation_order)},
                )
                if approval_span:
                    approval_span["attributes"]["approved"] = approval_result.approved
                    approval_span["attributes"]["risk"] = "medium"
                self.audit_log.record({
                    "tool": "generate_code", "action": "approval_request",
                    "risk": "medium", "approved": approval_result.approved,
                    "requires_human": approval_result.requires_human,
                })
                if not approval_result.approved and approval_result.requires_human:
                    logger.info("[HITL] Code generation requires human approval")
                    if approval_span:
                        approval_span["status"] = "ok"
                    return {
                        "blocked": False, "awaiting_approval": True,
                        "reason": approval_result.comment, "compiled": compiled,
                        "module_specs": {}, "code_artifact": {},
                        "approval_id": getattr(approval_result, "approval_id", ""),
                    }
                if approval_span:
                    approval_span["status"] = "ok"

            # ── Step 3: Generate module specs via experts ──
            expert_span = self.tracer.span("expert_analysis") if self.enable_observability else None
            module_specs: Dict[str, Any] = {}
            _specs_lock = threading.Lock()

            parallel_groups = compiled.dependency_graph.get_parallel_groups()
            _max_workers = min(self.max_workers, len(compiled.implementation_order))
            # SQLite-backed stores are not thread-safe — force sequential mode
            if self._has_sqlite_stores():
                _max_workers = 1

            for group_idx, group in enumerate(parallel_groups):
                group_modules = [m for m in group if m in compiled.implementation_order]
                if not group_modules:
                    continue

                if len(group_modules) == 1 or _max_workers <= 1:
                    for module_name in group_modules:
                        strategy = compiled.context_strategies.get(module_name)
                        input_schema = input_schemas.get(module_name, {})
                        expert_input = self._build_expert_input(
                            module_name, input_schema, strategy, compiled,
                            processed_specs=module_specs,  # pass already-processed specs for dep injection
                        )
                        expert = self.expert_agents.get(module_name)
                        if expert is None:
                            short_name = self._module_to_short_name(module_name)
                            expert = self.expert_agents.get(short_name)
                        if expert:
                            output = expert.process(expert_input)
                            with _specs_lock:
                                module_specs[module_name] = output
                            # Convert dict interfaces to InterfaceDef for the store
                            from tools.stores.interface_store import InterfaceDef
                            iface_defs = []
                            for iface in output.interfaces:
                                if isinstance(iface, dict):
                                    iface_defs.append(InterfaceDef(
                                        name=iface.get("name", "unknown"),
                                        method=iface.get("method", "POST"),
                                        path=iface.get("path", "/"),
                                        description=iface.get("description", ""),
                                    ))
                                else:
                                    iface_defs.append(iface)
                            self.interface_store.register_module(module_name, iface_defs)
                            from tools.stores import ModuleSpec
                            self.spec_store.put(
                                module_name,
                                ModuleSpec(
                                    module_name=module_name,
                                    components=[
                                        {"name": c.get("name", "Unknown"), "type": c.get("type", "service"),
                                         "description": c.get("description", "")}
                                        for c in output.components
                                    ],
                                    interfaces=[
                                        {"name": i.get("name", "unknown"), "method": i.get("method", "POST"),
                                         "path": i.get("path", "/")}
                                        for i in output.interfaces
                                    ],
                                    acceptance_criteria=output.acceptance_criteria,
                                    state_machine=output.state_machine,
                                    confidence=output.confidence,
                                ),
                            )
                            if self.enable_observability:
                                self.metrics.record_agent_call(
                                    agent_id=f"expert_{module_name}",
                                    tokens=len(str(output)) // 4,
                                )
                else:
                    def _process_expert(module_name):
                        strategy = compiled.context_strategies.get(module_name)
                        input_schema = input_schemas.get(module_name, {})
                        expert_input = self._build_expert_input(
                            module_name, input_schema, strategy, compiled,
                            processed_specs=module_specs,  # pass already-processed specs
                        )
                        expert = self.expert_agents.get(module_name)
                        if expert is None:
                            short_name = self._module_to_short_name(module_name)
                            expert = self.expert_agents.get(short_name)
                        if expert:
                            output = expert.process(expert_input)
                            with _specs_lock:
                                module_specs[module_name] = output
                            self.interface_store.put(module_name, output.interfaces)
                            from tools.stores import ModuleSpec
                            self.spec_store.put(
                                module_name,
                                ModuleSpec(
                                    module_name=module_name,
                                    components=[
                                        {"name": c.get("name", "Unknown"), "type": c.get("type", "service"),
                                         "description": c.get("description", "")}
                                        for c in output.components
                                    ],
                                    interfaces=[
                                        {"name": i.get("name", "unknown"), "method": i.get("method", "POST"),
                                         "path": i.get("path", "/")}
                                        for i in output.interfaces
                                    ],
                                    acceptance_criteria=output.acceptance_criteria,
                                    state_machine=output.state_machine,
                                    confidence=output.confidence,
                                ),
                            )
                            if self.enable_observability:
                                self.metrics.record_agent_call(
                                    agent_id=f"expert_{module_name}",
                                    tokens=len(str(output)) // 4,
                                )
                        return module_name

                    with ThreadPoolExecutor(max_workers=_max_workers) as executor:
                        futures = {executor.submit(_process_expert, m): m for m in group_modules}
                        for future in as_completed(futures):
                            try:
                                future.result()
                            except Exception as e:
                                logger.error("[Parallel] Expert processing failed: %s", e)

            if expert_span:
                expert_span["attributes"]["modules_processed"] = len(module_specs)
                expert_span["attributes"]["parallel_groups"] = len(parallel_groups)
                expert_span["status"] = "ok"

            # ── Step 4: Generate code ──
            gen_span = self.tracer.span("code_generation") if self.enable_observability else None
            code_artifact: Dict[str, str] = {}
            _code_lock = threading.Lock()

            for group_idx, group in enumerate(parallel_groups):
                group_modules = [m for m in group if m in module_specs]
                if not group_modules:
                    continue

                if len(group_modules) == 1 or _max_workers <= 1:
                    for module_name in group_modules:
                        spec = module_specs[module_name]
                        code = self.supervisor.generate_code(
                            module_spec=spec.__dict__ if hasattr(spec, "__dict__") else spec,
                            llm_provider=self.llm_provider,
                            module_name=module_name,
                        )
                        if code:
                            with _code_lock:
                                code_artifact[module_name] = code
                else:
                    def _generate_code(module_name):
                        spec = module_specs[module_name]
                        code = self.supervisor.generate_code(
                            module_spec=spec.__dict__ if hasattr(spec, "__dict__") else spec,
                            llm_provider=self.llm_provider,
                            module_name=module_name,
                        )
                        if code:
                            with _code_lock:
                                code_artifact[module_name] = code
                        return module_name

                    with ThreadPoolExecutor(max_workers=_max_workers) as executor:
                        futures = {executor.submit(_generate_code, m): m for m in group_modules}
                        for future in as_completed(futures):
                            try:
                                future.result()
                            except Exception as e:
                                logger.error("[Parallel] Code generation failed: %s", e)

            if gen_span:
                gen_span["attributes"]["modules_generated"] = len(code_artifact)
                gen_span["attributes"]["total_lines"] = sum(c.count("\n") + 1 for c in code_artifact.values())
                gen_span["status"] = "ok"

            # ── Step 5: Guardrails — output check ──
            if self.enable_guardrails:
                out_span = self.tracer.span("output_guard") if self.enable_observability else None
                for module_name, code in code_artifact.items():
                    out_result = self.output_guard.check(code, is_code=True)
                    if out_result.issues:
                        logger.warning("[Guardrails] Output issues for %s: %s", module_name, out_result.issues)
                        if self.enable_hitl:
                            self.audit_log.record({
                                "tool": "output_guard", "module": module_name,
                                "issues": out_result.issues, "risk": "low", "ok": False,
                            })
                    code_artifact[module_name] = out_result.text
                if out_span:
                    out_span["status"] = "ok"

            # ── Step 6: Memory — save ──
            total_lines = sum(c.count("\n") + 1 for c in code_artifact.values())
            summary = f"Generated {len(code_artifact)} modules, {total_lines} total lines"
            if self.enable_memory:
                self.memory.save_interaction("assistant", summary)
                self.session_state.checkpoint("phase1_complete", {
                    "modules": list(code_artifact.keys()), "total_lines": total_lines,
                })

            # ── Step 7: Metrics ──
            if self.enable_observability:
                self.metrics.record_agent_call(agent_id="phase1_pipeline", tokens=total_lines * 4)

            # ── Step 8: Workflow DAG ──
            workflow_result = self._run_workflow_phase1(compiled, code_artifact)

            if root_span:
                root_span["attributes"]["success"] = True
                root_span["attributes"]["modules"] = len(code_artifact)
                root_span["attributes"]["workflow_status"] = workflow_result.get("status", "skipped")
                root_span["status"] = "ok"

            print(f"[MultiAgent] {summary}")
            for mod, code in code_artifact.items():
                print(f"  {mod}: {code.count(chr(10)) + 1} lines")

            return {
                "blocked": False, "awaiting_approval": False, "reason": "",
                "compiled": compiled, "module_specs": module_specs,
                "prompt": compiled.prompt_template.template_str,
                "code_artifact": code_artifact,
                "memory_context": memory_context if self.enable_memory else "",
                "workflow_result": workflow_result,
            }

        except Exception as e:
            if root_span:
                root_span["status"] = "error"
                root_span["attributes"]["error"] = f"{type(e).__name__}: {e}"
            if self.enable_hitl:
                self.audit_log.record({
                    "tool": "phase1_pipeline", "action": "error",
                    "error": str(e), "risk": "high", "ok": False,
                })
            raise

    def _run_workflow_phase1(self, compiled, code_artifact):
        """Execute Phase 1 compiled pipeline via WorkflowEngine DAG."""
        import asyncio
        from tools.workflow import build_pipeline_workflow

        if not compiled or not hasattr(compiled, "implementation_order"):
            return {"status": "skipped", "reason": "No compiled pipeline"}

        workflow_span = None
        if self.enable_observability:
            workflow_span = self.tracer.span("workflow_execution_phase1")

        try:
            workflow = build_pipeline_workflow(
                compiled,
                llm_provider=self.llm_provider,
                agent_registry=self.expert_agents,
            )
            self.workflow_engine._workflows[workflow.id] = workflow
            input_data = {
                "user_requirement": getattr(compiled, "user_requirement", ""),
                "modules": compiled.implementation_order,
                "code_artifact": code_artifact,
            }
            run_id = asyncio.run(self._execute_workflow_async(workflow.id, input_data))
            result = self.workflow_engine.get_run_result(run_id)

            if workflow_span:
                workflow_span["attributes"]["workflow_id"] = workflow.id
                workflow_span["attributes"]["status"] = result.status if result else "unknown"
                if result:
                    workflow_span["attributes"]["node_count"] = len(result.logs)
                    workflow_span["attributes"]["execution_time_ms"] = result.execution_time_ms
                workflow_span["status"] = "ok"

            if result:
                return {
                    "status": result.status,
                    "node_outputs": result.outputs,
                    "execution_time_ms": result.execution_time_ms,
                    "node_count": len(result.logs),
                    "logs": [
                        {"node_id": log.node_id, "status": log.status, "duration_ms": log.duration_ms}
                        for log in result.logs
                    ],
                }
            return {"status": "no_result"}

        except Exception as e:
            logger.error("[WorkflowEngine] Phase 1 execution failed: %s", e)
            if workflow_span:
                workflow_span["status"] = "error"
                workflow_span["attributes"]["error"] = str(e)
            return {"status": "error", "error": str(e)}
