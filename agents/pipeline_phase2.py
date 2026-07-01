# agents/pipeline_phase2.py
"""
Phase 2 pipeline logic — code review → fix loop with convergence detection.

This module is mixed into KodeForge via composition.
Do not import directly; use KodeForge instead.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class Phase2Pipeline:
    """Phase 2 logic — attached to KodeForge via composition."""

    def run_phase2(self, code_artifact, compiled_pipeline=None) -> dict:
        """Phase 2: Code Review → Fix Loop with Convergence Detection."""
        root_span = self.tracer.span("phase2") if self.enable_observability else None

        try:
            if compiled_pipeline is None:
                input_schemas, output_schemas = self._load_schemas()
                compiled_pipeline = self.compile_pipeline(output_schemas, input_schemas=input_schemas)

            from tools.quality import ConvergenceDetector

            detector = ConvergenceDetector(max_iterations=3)
            iteration = 0

            while True:
                iter_span = self.tracer.span(f"review_iter_{iteration}") if self.enable_observability else None

                review_results = self._run_real_reviews(
                    compiled_pipeline.implementation_order, code_artifact,
                )
                report = self.quality_evaluator.evaluate(review_results, iteration=iteration)

                if iter_span:
                    iter_span["attributes"]["quality_score"] = report.quality_score
                    iter_span["attributes"]["passed"] = report.passed

                if self.enable_hitl:
                    self.audit_log.record({
                        "tool": "code_review", "iteration": iteration,
                        "quality_score": report.quality_score, "passed": report.passed,
                        "risk": "low", "ok": report.passed,
                    })

                if self.enable_memory:
                    self.session_state.checkpoint(f"phase2_iter_{iteration}", {
                        "quality_score": report.quality_score, "passed": report.passed,
                    })

                should_continue, reason = detector.should_continue(
                    iteration=iteration, quality_score=report.quality_score,
                    has_critical=report.has_critical,
                )

                if iter_span:
                    iter_span["attributes"]["should_continue"] = should_continue
                    iter_span["status"] = "ok" if report.passed else "ok"

                if not should_continue:
                    break
                iteration += 1

            # Collect fix contexts from review results via RAG
            fix_contexts: list[str] = []
            for result in review_results:
                if result.verdict != "pass" and result.issues:
                    ctx = self._search_fix_context(result.issues, module_name=result.module)
                    if ctx:
                        fix_contexts.append(ctx)

            workflow_result = self._run_workflow_phase2(
                compiled_pipeline, code_artifact,
                fix_contexts=fix_contexts if fix_contexts else None,
            )

            if root_span:
                root_span["attributes"]["passed"] = report.passed
                root_span["attributes"]["iterations"] = iteration
                root_span["attributes"]["workflow_status"] = workflow_result.get("status", "skipped")
                root_span["status"] = "ok"

            return {
                "passed": report.passed, "quality_score": report.quality_score,
                "iterations": iteration, "convergence_status": reason,
                "workflow_result": workflow_result,
            }

        except Exception as e:
            if root_span:
                root_span["status"] = "error"
                root_span["attributes"]["error"] = f"{type(e).__name__}: {e}"
            if self.enable_hitl:
                self.audit_log.record({
                    "tool": "phase2_pipeline", "action": "error",
                    "error": str(e), "risk": "high", "ok": False,
                })
            raise

    def _run_real_reviews(self, module_order, code_artifact) -> list:
        """Run real LLM-based code reviews for each module.

        Uses ExpertAgent.review() with the actual generated code.
        Falls back to pass verdict when no LLM provider is available.
        """
        from agents.experts import ReviewInput
        from tools.quality import ReviewResult

        if not isinstance(code_artifact, dict):
            code_artifact = {}

        results = []
        for module_name in module_order:
            expert = self.expert_agents.get(module_name)
            if expert is None:
                short_name = self._module_to_short_name(module_name)
                expert = self.expert_agents.get(short_name)

            code = code_artifact.get(module_name, "")

            if expert and code:
                review = expert.review(ReviewInput(
                    module_name=module_name,
                    code_snippet=code,
                ))
                results.append(ReviewResult(
                    module=module_name, verdict=review.verdict, issues=review.issues,
                ))
            elif expert:
                # No code to review — return fail to signal the issue
                results.append(ReviewResult(
                    module=module_name, verdict="fail",
                    issues=[{"severity": "critical", "message": f"No code generated for {module_name}"}],
                ))
            else:
                results.append(ReviewResult(module=module_name, verdict="pass"))
        return results

    def _run_workflow_phase2(self, compiled, code_artifact, fix_contexts=None) -> dict:
        """Execute Phase 2 review+fix via WorkflowEngine DAG."""
        import asyncio
        from tools.workflow import build_pipeline_workflow

        if not compiled or not hasattr(compiled, "implementation_order"):
            return {"status": "skipped", "reason": "No compiled pipeline"}

        try:
            workflow = build_pipeline_workflow(
                compiled, llm_provider=self.llm_provider, agent_registry=self.expert_agents,
                fix_contexts=fix_contexts,
            )
            self.workflow_engine._workflows[workflow.id] = workflow
            input_data = {"phase": "review", "code_artifact": code_artifact, "modules": compiled.implementation_order}
            run_id = asyncio.run(self._execute_workflow_async(workflow.id, input_data))
            result = self.workflow_engine.get_run_result(run_id)
            if result:
                return {"status": result.status, "execution_time_ms": result.execution_time_ms, "node_count": len(result.logs)}
            return {"status": "no_result"}
        except Exception as e:
            logger.error("[WorkflowEngine] Phase 2 execution failed: %s", e)
            return {"status": "error", "error": str(e)}

    def _simulate_reviews(self, module_order) -> list:
        from agents.experts import ReviewInput
        from tools.quality import ReviewResult

        _rng = __import__("random").Random(42)
        results = []
        for module_name in module_order:
            expert = self.expert_agents.get(module_name)
            if expert:
                review = expert.review(ReviewInput(module_name=module_name, code_snippet="# simulated code"))
                results.append(ReviewResult(
                    module=module_name, verdict=review.verdict, issues=review.issues,
                ))
            else:
                results.append(ReviewResult(module=module_name, verdict="pass"))
        return results

    def _search_fix_context(self, issues: list, module_name: str = "") -> str:
        """Retrieve fix examples from RAG pipeline for the given issues.

        Searches the RAG knowledge base for documents relevant to the
        reported issues, returns formatted context string for prompt injection.
        """
        if not issues or self.rag_pipeline is None:
            return ""

        try:
            issue_messages = " ".join(i.get("message", "") for i in issues)
            query = f"fix: {issue_messages}"
            if module_name:
                query = f"{module_name} {query}"

            result = self.rag_pipeline.query(query, top_k=3)

            snippets: list[str] = []
            for doc in result.reranked_documents:
                snippet = doc.content[:200].strip()
                if snippet:
                    snippets.append(f"- [{doc.source}] {snippet}")

            if not snippets:
                return ""

            return "## Retrieved fix context\n" + "\n".join(snippets)
        except Exception as e:
            logger.warning("[Phase2] _search_fix_context failed: %s", e)
            return ""

    def _generate_fix_instructions(self, review_results, compiled_pipeline) -> list:
        all_instructions = []
        for result in review_results:
            if result.verdict != "pass":
                module_name = result.module
                fix_template = compiled_pipeline.fix_templates.get(module_name)
                if fix_template and result.issues:
                    instructions = fix_template.generate_fix_instructions(result.issues)
                    all_instructions.extend(instructions)
        return all_instructions
