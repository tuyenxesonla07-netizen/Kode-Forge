# tests/eval/test_eval_isolation.py
"""Tests for EvalRunner — per-case context isolation and new assertions."""

import pytest

from tools.eval.runner import EvalRunner


class TestEvalRunnerIsolation:
    def test_isolate_false_by_default(self):
        runner = EvalRunner()
        assert runner.isolate is False

    def test_isolate_true(self):
        runner = EvalRunner(isolate=True)
        assert runner.isolate is True

    def test_run_case_with_context_isolated(self):
        """When isolate=True, mutating context in one case doesn't affect next."""
        contexts_seen = []

        def pipeline_fn(input_str, context=None):
            ctx = context or {}
            contexts_seen.append(dict(ctx))
            ctx["last_input"] = input_str  # mutate context
            return {
                "generated_modules": ["test"],
                "code_artifact": {"test": "class Test: pass"},
                "blocked": False, "steps": 1, "iterations": 0,
                "max_steps": 10, "max_iterations": 3,
                "summary": "ok",
            }

        runner = EvalRunner(run_pipeline_fn=pipeline_fn, isolate=True)
        cases = [
            {"id": "c1", "input": "first", "checks": []},
            {"id": "c2", "input": "second", "checks": []},
        ]
        shared_ctx = {"shared": True}
        runner.run_all(cases, context=shared_ctx, verbose=False)

        assert contexts_seen[0].get("last_input") is None
        assert contexts_seen[1].get("last_input") is None

    def test_run_case_without_isolation(self):
        """When isolate=False, mutations leak between cases."""
        contexts_seen = []

        def pipeline_fn(input_str, context=None):
            ctx = context if context is not None else {}
            contexts_seen.append(dict(ctx))
            ctx["last_input"] = input_str
            return {
                "generated_modules": ["test"],
                "code_artifact": {},
                "blocked": False, "steps": 1, "iterations": 0,
                "max_steps": 10, "max_iterations": 3,
                "summary": "ok",
            }

        runner = EvalRunner(run_pipeline_fn=pipeline_fn, isolate=False)
        cases = [
            {"id": "c1", "input": "first", "checks": []},
            {"id": "c2", "input": "second", "checks": []},
        ]
        shared_ctx = {"shared": True}
        runner.run_all(cases, context=shared_ctx, verbose=False)

        assert contexts_seen[1].get("last_input") == "first"

    def test_new_assertions_in_eval(self):
        """Test that new assertions (intent, tools_used, forbid_tools) work in EvalRunner."""
        def pipeline_fn(input_str, context=None):
            return {
                "intent": "code_generation",
                "tools_used": ["generate_code"],
                "blocked": False, "steps": 1, "iterations": 0,
                "max_steps": 10, "max_iterations": 3,
                "generated_modules": ["auth"],
                "code_artifact": {"auth": "class Auth: pass"},
                "summary": "ok",
            }

        runner = EvalRunner(run_pipeline_fn=pipeline_fn, verbose=False)
        cases = [
            {"id": "intent_match", "input": "test", "checks": ["intent"],
             "expected_intent": "code_generation"},
            {"id": "tools_match", "input": "test", "checks": ["tools_used"],
             "expected_tools": ["generate_code"]},
            {"id": "forbid_clean", "input": "test", "checks": ["forbid_tools"],
             "forbidden_tools": ["execute_code"]},
        ]
        report = runner.run_all(cases, verbose=False)
        assert report.cases_total == 3
        assert report.cases_passed == 3
