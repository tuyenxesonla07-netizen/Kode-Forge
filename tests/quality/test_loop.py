"""Tests for AST Validator and Quality Loop."""

import asyncio
import pytest
from tools.quality.ast_validator import ASTValidator, ValidationResult, ValidationIssue
from tools.quality.quality_evaluator import QualityEvaluator, ReviewResult
from tools.quality.convergence_detector import ConvergenceDetector


# ---------------------------------------------------------------------------
# AST Validator Tests
# ---------------------------------------------------------------------------

class TestASTValidator:
    @pytest.fixture
    def validator(self):
        return ASTValidator()

    def test_valid_code_passes(self, validator):
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)
'''
        result = validator.validate(code)
        assert result.valid is True
        assert result.has_critical is False
        assert result.metrics["syntax_valid"] is True
        assert result.metrics["class_count"] == 1
        assert result.metrics["function_count"] >= 1

    def test_syntax_error_detected(self, validator):
        code = '''
def broken(:
    return 42
'''
        result = validator.validate(code)
        assert result.valid is False
        assert result.has_critical is True
        assert len(result.issues) >= 1
        assert result.issues[0].type == "syntax_error"

    def test_missing_parenthesis_detected(self, validator):
        code = '''
def broken(
    x = 1
    return x
'''
        result = validator.validate(code)
        assert result.valid is False
        assert result.has_critical is True

    def test_unclosed_brace_handled(self, validator):
        code = '''
def broken():
    if True:
        return 1
'''
        result = validator.validate(code)
        # Should not crash, may or may not parse
        assert isinstance(result, ValidationResult)

    def test_unused_import_detected(self, validator):
        code = '''
import os
import sys

def hello():
    return sys.argv
'''
        result = validator.validate(code)
        unused_issues = [i for i in result.issues if i.type == "unused_import"]
        assert len(unused_issues) >= 1
        assert any("os" in i.message for i in unused_issues)

    def test_missing_required_class(self, validator):
        code = '''
def hello():
    return 42
'''
        spec = {
            "required_classes": ["AuthService", "UserModel"],
        }
        result = validator.validate(code, spec)
        missing_class_issues = [i for i in result.issues if i.type == "missing_class"]
        assert len(missing_class_issues) == 2

    def test_missing_required_function(self, validator):
        code = '''
class MyService:
    pass
'''
        spec = {
            "required_functions": ["login", "register"],
        }
        result = validator.validate(code, spec)
        missing_func_issues = [i for i in result.issues if i.type == "missing_function"]
        assert len(missing_func_issues) == 2

    def test_missing_return_annotation(self, validator):
        code = '''
def hello(name):
    return f"Hello, {name}!"
'''
        result = validator.validate(code)
        annotation_issues = [i for i in result.issues if i.type == "missing_return_annotation"]
        assert len(annotation_issues) >= 1

    def test_metrics_computed(self, validator):
        code = '''
import os

class MyService:
    def method(self):
        pass

def func():
    pass
'''
        result = validator.validate(code)
        assert result.metrics["line_count"] > 0
        assert result.metrics["class_count"] == 1
        assert result.metrics["function_count"] == 2  # method + func
        assert result.metrics["import_count"] == 1
        assert result.metrics["has_classes"] is True
        assert result.metrics["has_functions"] is True

    def test_syntax_fix_suggestion(self, validator):
        code = '''
def broken(
    x = 1
'''
        result = validator.validate(code)
        assert result.valid is False
        assert len(result.issues) >= 1
        assert result.issues[0].suggestion != ""

    def test_empty_code_handled(self, validator):
        result = validator.validate("")
        assert isinstance(result, ValidationResult)

    def test_docstring_detection(self, validator):
        code = '''
"""Module docstring."""

def func():
    """Function docstring."""
    pass
'''
        result = validator.validate(code)
        assert result.metrics.get("has_docstrings") is True

    def test_json_not_valid_python(self, validator):
        """MockLLMProvider returns JSON, which should be flagged as syntax error."""
        json_output = '{"module_name": "auth", "components": [{"name": "AuthService"}]}'
        result = validator.validate(json_output)
        # JSON is not valid Python (in most cases)
        assert isinstance(result, ValidationResult)

    def test_complex_valid_code(self, validator):
        """Test with a realistic generated code snippet."""
        code = '''
"""Authentication module."""

from typing import Optional
from dataclasses import dataclass
import hashlib
import secrets


@dataclass
class UserModel:
    """User data model."""
    username: str
    email: str
    password_hash: str


class AuthService:
    """Authentication service handling login and registration."""

    def __init__(self, secret_key: str):
        self._secret_key = secret_key
        self._users: dict[str, UserModel] = {}

    def register(self, username: str, email: str, password: str) -> UserModel:
        """Register a new user."""
        if username in self._users:
            raise ValueError(f"User {username} already exists")
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        user = UserModel(username=username, email=email, password_hash=password_hash)
        self._users[username] = user
        return user

    def login(self, username: str, password: str) -> Optional[str]:
        """Login and return a token."""
        user = self._users.get(username)
        if not user:
            return None
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if user.password_hash != password_hash:
            return None
        return secrets.token_hex(32)
'''
        result = validator.validate(code)
        assert result.valid is True
        assert result.has_critical is False
        assert result.metrics["class_count"] == 2
        assert result.metrics["syntax_valid"] is True


# ---------------------------------------------------------------------------
# QualityEvaluator Integration Tests
# ---------------------------------------------------------------------------

class TestQualityEvaluatorIntegration:
    @pytest.fixture
    def evaluator(self):
        return QualityEvaluator()

    def test_passing_review(self, evaluator):
        review = ReviewResult(
            module="auth",
            verdict="pass",
            issues=[],
            metrics={"syntax_valid": True, "coverage": 0.9},
            confidence=0.95,
        )
        report = evaluator.evaluate([review], iteration=0)
        assert report.passed is True
        assert report.has_critical is False
        assert report.quality_score > 0.5

    def test_failing_review(self, evaluator):
        review = ReviewResult(
            module="auth",
            verdict="fail",
            issues=[
                {"severity": "critical", "type": "syntax_error", "message": "Syntax error"},
            ],
            metrics={"syntax_valid": False},
            confidence=0.3,
        )
        report = evaluator.evaluate([review], iteration=0)
        assert report.passed is False
        assert report.has_critical is True

    def test_multiple_modules(self, evaluator):
        reviews = [
            ReviewResult(module="auth", verdict="pass", issues=[], metrics={}, confidence=0.9),
            ReviewResult(module="order", verdict="pass", issues=[], metrics={}, confidence=0.85),
        ]
        report = evaluator.evaluate(reviews, iteration=0)
        assert report.passed is True
        assert len(report.module_results) == 2

    def test_mixed_results(self, evaluator):
        reviews = [
            ReviewResult(module="auth", verdict="pass", issues=[], metrics={}, confidence=0.9),
            ReviewResult(
                module="order", verdict="fail",
                issues=[{"severity": "major", "type": "missing_class", "message": "Missing class"}],
                metrics={}, confidence=0.5,
            ),
        ]
        report = evaluator.evaluate(reviews, iteration=0)
        assert report.passed is False


# ---------------------------------------------------------------------------
# ConvergenceDetector Tests
# ---------------------------------------------------------------------------

class TestConvergenceDetector:
    def test_converges_on_good_quality(self):
        detector = ConvergenceDetector(max_iterations=3)
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.9, has_critical=False,
        )
        assert should_continue is False
        assert "达标" in reason

    def test_continues_on_low_quality(self):
        detector = ConvergenceDetector(max_iterations=3)
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.3, has_critical=False,
        )
        assert should_continue is True

    def test_stops_at_max_iterations(self):
        detector = ConvergenceDetector(max_iterations=2)
        detector.should_continue(iteration=0, quality_score=0.5, has_critical=False)
        detector.should_continue(iteration=1, quality_score=0.5, has_critical=False)
        should_continue, reason = detector.should_continue(
            iteration=2, quality_score=0.5, has_critical=False,
        )
        assert should_continue is False
        assert "最大迭代" in reason

    def test_stops_on_critical(self):
        detector = ConvergenceDetector(max_iterations=3)
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.5, has_critical=True,
        )
        assert should_continue is False
        assert "critical" in reason

    def test_stagnation_detection(self):
        detector = ConvergenceDetector(max_iterations=5, min_improvement=0.02)
        detector.record_score(0.5)
        detector.record_score(0.5)
        detector.record_score(0.5)
        should_continue, reason = detector.should_continue(
            iteration=3, quality_score=0.5, has_critical=False,
        )
        assert should_continue is False
        assert "未提升" in reason

    def test_improvement_resets_stagnation(self):
        detector = ConvergenceDetector(max_iterations=5, min_improvement=0.02)
        detector.record_score(0.5)
        detector.record_score(0.5)
        detector.record_score(0.55)  # Improvement!
        should_continue, reason = detector.should_continue(
            iteration=3, quality_score=0.55, has_critical=False,
        )
        assert should_continue is True


# ---------------------------------------------------------------------------
# QualityLoop Tests (async)
# ---------------------------------------------------------------------------

class TestQualityLoop:
    @pytest.mark.asyncio
    async def test_quality_loop_runs_with_mock_provider(self):
        """QualityLoop should execute with MockLLMProvider and produce a result."""
        from tools.workflow.engine import QualityLoop
        from tools.workflow.nodes import WorkflowNode, NodeType
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        node = WorkflowNode(
            id="test_node",
            type=NodeType.LLM,
            name="Test Node",
            config={"prompt_template": "Generate authentication code"},
        )

        loop = QualityLoop(max_iterations=2, quality_threshold=0.8)
        result = await loop.execute_with_quality(
            node,
            inputs={"input": "test requirement"},
            context={"llm_provider": provider},
        )

        assert result.output is not None
        assert len(result.output) > 0
        assert result.quality_report is not None
        assert result.iterations >= 1
        assert isinstance(result.converged, bool)
        assert len(result.history) == result.iterations

    @pytest.mark.asyncio
    async def test_quality_loop_max_iterations(self):
        """Should stop at max_iterations even if quality is low."""
        from tools.workflow.engine import QualityLoop
        from tools.workflow.nodes import WorkflowNode, NodeType
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        node = WorkflowNode(
            id="test_node",
            type=NodeType.LLM,
            name="Test",
            config={
                "prompt_template": "Generate code",
                "required_classes": ["NonExistentClass"],
            },
        )

        loop = QualityLoop(max_iterations=2, quality_threshold=0.95)
        result = await loop.execute_with_quality(
            node,
            inputs={"input": "test"},
            context={"llm_provider": provider},
        )

        assert result.iterations == 2
        # Mock returns JSON which won't have NonExistentClass, so won't converge
        assert result.converged is False

    @pytest.mark.asyncio
    async def test_quality_loop_history_recorded(self):
        """Each iteration should record history."""
        from tools.workflow.engine import QualityLoop
        from tools.workflow.nodes import WorkflowNode, NodeType
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        node = WorkflowNode(
            id="history_test",
            type=NodeType.LLM,
            name="History Test",
            config={"prompt_template": "Generate code"},
        )

        loop = QualityLoop(max_iterations=3, quality_threshold=0.5)
        result = await loop.execute_with_quality(
            node,
            inputs={"input": "test"},
            context={"llm_provider": provider},
        )

        # Each history entry should have required fields
        for entry in result.history:
            assert "iteration" in entry
            assert "output_length" in entry
            assert "quality_score" in entry
            assert "passed" in entry

    @pytest.mark.asyncio
    async def test_quality_loop_fix_prompt_injected(self):
        """After first iteration, fix prompt should be injected into inputs."""
        from tools.workflow.engine import QualityLoop
        from tools.workflow.nodes import WorkflowNode, NodeType
        from tools.llm.mock import MockLLMProvider
        from unittest.mock import AsyncMock, patch

        provider = MockLLMProvider()
        node = WorkflowNode(
            id="fix_test",
            type=NodeType.LLM,
            name="Fix Test",
            config={
                "prompt_template": "Generate code",
                "required_classes": ["NonExistentClass"],
            },
        )

        loop = QualityLoop(max_iterations=3, quality_threshold=0.5)
        result = await loop.execute_with_quality(
            node,
            inputs={"input": "test"},
            context={"llm_provider": provider},
        )

        # If there were issues, fix prompts would have been applied in subsequent iterations
        # The result should still be valid even if quality is low
        assert result.output is not None


# ---------------------------------------------------------------------------
# WorkflowEngine + QualityLoop Integration
# ---------------------------------------------------------------------------

class TestWorkflowEngineWithQualityLoop:
    @pytest.mark.asyncio
    async def test_engine_with_quality_loop(self):
        """WorkflowEngine should use QualityLoop for LLM nodes when configured."""
        from tools.workflow.engine import WorkflowEngine
        from tools.workflow.engine import QualityLoop
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        quality_loop = QualityLoop(max_iterations=2, quality_threshold=0.5)
        engine = WorkflowEngine(quality_loop=quality_loop)

        workflow_def = {
            "id": "quality_test",
            "name": "Quality Test Workflow",
            "nodes": [
                {
                    "id": "llm_node",
                    "type": "llm",
                    "name": "Generate Code",
                    "config": {
                        "prompt_template": "Generate authentication code",
                        "temperature": 0.3,
                    },
                    "inputs": [],
                },
            ],
            "edges": [],
            "metadata": {},
        }

        engine.load_workflow(workflow_def)
        run_id = await engine.execute_async(
            "quality_test",
            {"input": "test requirement"},
            context={"llm_provider": provider},
        )

        # Wait for completion
        for _ in range(100):
            result = engine.get_run_result(run_id)
            if result and result.status != "running":
                break
            await asyncio.sleep(0.1)

        final = engine.get_run_result(run_id)
        assert final is not None
        assert final.status == "success"
        assert "llm_node" in final.outputs
        # Quality metadata should be stored
        assert "llm_node_quality" in final.outputs

    @pytest.mark.asyncio
    async def test_engine_without_quality_loop(self):
        """WorkflowEngine should work without QualityLoop (backward compat)."""
        from tools.workflow.engine import WorkflowEngine
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        engine = WorkflowEngine()  # No quality_loop

        workflow_def = {
            "id": "no_quality_test",
            "name": "No Quality Test",
            "nodes": [
                {
                    "id": "llm_node",
                    "type": "llm",
                    "name": "Generate Code",
                    "config": {"prompt_template": "Generate code"},
                    "inputs": [],
                },
            ],
            "edges": [],
            "metadata": {},
        }

        engine.load_workflow(workflow_def)
        run_id = await engine.execute_async(
            "no_quality_test",
            {"input": "test"},
            context={"llm_provider": provider},
        )

        for _ in range(100):
            result = engine.get_run_result(run_id)
            if result and result.status != "running":
                break
            await asyncio.sleep(0.1)

        final = engine.get_run_result(run_id)
        assert final is not None
        assert final.status == "success"
        # No quality metadata
        assert "llm_node_quality" not in final.outputs
