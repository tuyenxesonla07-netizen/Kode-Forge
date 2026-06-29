# tests/eval/test_ab_test.py
"""Tests for ABTestRunner — pipeline comparison."""

from tools.eval.runner import ABTestRunner


class TestABTestRunner:
    def test_compare_pipelines(self):
        def pipeline_a(input_str, context=None):
            return {
                "generated_modules": ["auth"],
                "code_artifact": {"auth": "class Auth: pass"},
                "blocked": False,
                "steps": 1, "iterations": 0,
                "max_steps": 10, "max_iterations": 3,
                "tools_used": ["generate_code"],
                "intent": "code_generation",
                "summary": "ok",
            }

        def pipeline_b(input_str, context=None):
            return {
                "generated_modules": ["auth"],
                "code_artifact": {"auth": "class AuthService: pass"},
                "blocked": False,
                "steps": 2, "iterations": 0,
                "max_steps": 10, "max_iterations": 3,
                "tools_used": ["generate_code"],
                "intent": "code_generation",
                "summary": "ok",
            }

        runner = ABTestRunner()
        cases = [
            {"id": "test_case", "input": "test", "checks": ["modules_generated"],
             "expected_modules": ["auth"]},
        ]
        report = runner.compare(pipeline_a, pipeline_b, cases=cases)
        assert report.winner is not None
        assert report.delta is not None
        assert "A/B COMPARISON" in report.render_table()
        assert '"winner"' in report.to_json()
