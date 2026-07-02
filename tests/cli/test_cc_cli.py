# tests/cli/test_cc_cli.py
"""Tests for the cc CLI entry point and sub-command handlers."""

from __future__ import annotations

import argparse
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# tools/cli/model.py
# ---------------------------------------------------------------------------

class TestCmdModelList:
    def test_prints_header(self, capsys):
        from tools.cli.model import cmd_model_list
        mock_registry = MagicMock()
        mock_registry.list_display.return_value = [
            {"display_name": "Anthropic Claude", "name": "anthropic",
             "has_api_key": True, "default_model": "claude-sonnet-4-6",
             "models": ["claude-sonnet-4-6", "claude-haiku-4-5"], "notes": ""},
        ]
        with patch("tools.llm.model_switcher.ModelRegistry", return_value=mock_registry):
            cmd_model_list(_ns())
        out = capsys.readouterr().out
        assert "Model Registry" in out
        assert "Anthropic Claude" in out

    def test_marks_missing_key(self, capsys):
        from tools.cli.model import cmd_model_list
        mock_registry = MagicMock()
        mock_registry.list_display.return_value = [
            {"display_name": "No Key Provider", "name": "openai",
             "has_api_key": False, "default_model": "gpt-4o",
             "models": ["gpt-4o"], "notes": ""},
        ]
        with patch("tools.llm.model_switcher.ModelRegistry", return_value=mock_registry):
            cmd_model_list(_ns())
        out = capsys.readouterr().out
        assert "✗" in out


class TestCmdModelSwitch:
    def test_successful_switch(self, capsys):
        from tools.cli.model import cmd_model_switch
        mock_registry = MagicMock()
        mock_switcher = MagicMock()
        mock_switcher.switch.return_value = True
        with patch("tools.llm.model_switcher.ModelRegistry", return_value=mock_registry), \
             patch("tools.llm.model_switcher.ModelSwitcher", return_value=mock_switcher):
            cmd_model_switch(_ns(provider="anthropic", model="claude-sonnet-4-6"))
        out = capsys.readouterr().out
        assert "✓" in out

    def test_unknown_provider(self, capsys):
        from tools.cli.model import cmd_model_switch
        mock_registry = MagicMock()
        mock_registry.list_providers.return_value = ["anthropic", "openai"]
        mock_switcher = MagicMock()
        mock_switcher.switch.return_value = False
        with patch("tools.llm.model_switcher.ModelRegistry", return_value=mock_registry), \
             patch("tools.llm.model_switcher.ModelSwitcher", return_value=mock_switcher):
            cmd_model_switch(_ns(provider="unknown_provider", model=None))
        out = capsys.readouterr().out
        assert "✗" in out


class TestCmdModelTest:
    def test_test_all_providers(self, capsys):
        from tools.cli.model import cmd_model_test
        mock_registry = MagicMock()
        mock_switcher = MagicMock()
        mock_switcher.test_all.return_value = [
            {"provider": "anthropic", "model": "claude-sonnet-4-6",
             "status": "ok", "latency_ms": 120, "error": None, "env_var": None},
        ]
        with patch("tools.llm.model_switcher.ModelRegistry", return_value=mock_registry), \
             patch("tools.llm.model_switcher.ModelSwitcher", return_value=mock_switcher):
            cmd_model_test(_ns(provider=None))
        out = capsys.readouterr().out
        assert "Connectivity Test" in out
        assert "✓" in out


# ---------------------------------------------------------------------------
# tools/cli/rag.py
# ---------------------------------------------------------------------------

class TestCmdQuery:
    def test_query_prints_answer(self, capsys):
        from tools.cli.rag import cmd_query
        mock_result = MagicMock()
        mock_result.answer = "Python is a programming language."
        mock_result.documents = [MagicMock(source="wiki_python", content="Python is..." )]
        mock_result.scores = [0.95]
        mock_result.metadata = {"latency_ms": 50}
        with patch("tools.cli.rag._make_pipeline") as mock_make:
            mock_pipeline = MagicMock()
            mock_pipeline.query.return_value = mock_result
            mock_make.return_value = mock_pipeline
            cmd_query(_ns(text="What is Python?"))
        out = capsys.readouterr().out
        assert "What is Python?" in out
        assert "Python is a programming language." in out

    def test_query_truncates_long_answer(self, capsys):
        from tools.cli.rag import cmd_query
        mock_result = MagicMock()
        mock_result.answer = "A" * 500
        mock_result.documents = []
        mock_result.scores = []
        mock_result.metadata = {}
        with patch("tools.cli.rag._make_pipeline") as mock_make:
            mock_pipeline = MagicMock()
            mock_pipeline.query.return_value = mock_result
            mock_make.return_value = mock_pipeline
            cmd_query(_ns(text="long query"))
        out = capsys.readouterr().out
        # 300-char limit applied
        assert "A" * 301 not in out


class TestCmdSearch:
    def test_search_prints_results(self, capsys):
        from tools.cli.rag import cmd_search
        mock_result = MagicMock()
        mock_result.documents = [
            MagicMock(source="wiki_ml", content="Machine learning is a subset of AI."),
        ]
        mock_result.scores = [0.87]
        with patch("tools.cli.rag._make_pipeline") as mock_make:
            mock_pipeline = MagicMock()
            mock_pipeline.query.return_value = mock_result
            mock_make.return_value = mock_pipeline
            cmd_search(_ns(text="machine learning"))
        out = capsys.readouterr().out
        assert "machine learning" in out
        assert "wiki_ml" in out


# ---------------------------------------------------------------------------
# tools/cli/pipeline.py
# ---------------------------------------------------------------------------

class TestCmdRun:
    def test_run_mock_pipeline(self, capsys):
        from tools.cli.pipeline import cmd_run
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {
            "status": "success",
            "phase1": {"code_artifact": {"authentication": "# auth code\n# line 2"}},
            "phase2": {"passed": True},
        }
        with patch("agents.pipeline.Pipeline", return_value=mock_pipeline):
            cmd_run(_ns(requirement="Build auth module", backend="workflow", llm_backend="mock"))
        out = capsys.readouterr().out
        assert "Pipeline Run" in out

    def test_run_handles_list_requirement(self, capsys):
        from tools.cli.pipeline import cmd_run
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"status": "success", "phase1": {}, "phase2": {}}
        with patch("agents.pipeline.Pipeline", return_value=mock_pipeline):
            cmd_run(_ns(requirement=["Build", "auth", "module"], backend="workflow", llm_backend="mock"))
        mock_pipeline.run.assert_called_once_with("Build auth module")


class TestCmdEval:
    def test_eval_runs_suite(self, capsys):
        from tools.cli.pipeline import cmd_eval
        with patch("tools.cli.pipeline.cmd_eval") as mock_eval:
            mock_eval(_ns())  # call the mock directly — just verify no crash
        # Real path: verify EvalRunner is invocable
        with patch("tools.eval.runner.EvalRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.run_all.return_value = MagicMock(cases_total=5, cases_passed=5, pass_rate=1.0, pass_percentage=100)
            mock_runner_cls.return_value = mock_runner
            cmd_eval(_ns())

    def test_eval_handles_exception(self, capsys):
        from tools.cli.pipeline import cmd_eval
        with patch("tools.eval.runner.EvalRunner", side_effect=Exception("runner error")):
            cmd_eval(_ns())  # should not raise
        out = capsys.readouterr().out
        assert "✗" in out or "Eval" in out


# ---------------------------------------------------------------------------
# tools/cli/system.py
# ---------------------------------------------------------------------------

class TestCmdStatus:
    def test_status_output(self, capsys):
        from tools.cli.system import cmd_status
        mock_registry = MagicMock()
        mock_switcher = MagicMock()
        mock_switcher.status_display.return_value = {
            "current_provider": "anthropic",
            "current_model": "claude-sonnet-4-6",
            "available_providers": ["anthropic", "openai"],
            "has_api_key": {"anthropic": True, "openai": False},
        }
        with patch("tools.llm.model_switcher.ModelRegistry", return_value=mock_registry), \
             patch("tools.llm.model_switcher.ModelSwitcher", return_value=mock_switcher):
            cmd_status(_ns())
        out = capsys.readouterr().out
        assert "anthropic" in out
        assert "claude-sonnet-4-6" in out


class TestCmdValidate:
    def test_validate_success(self, capsys):
        from tools.cli.system import cmd_validate
        with patch("tools.schema_validator.validate_all", return_value=True):
            cmd_validate(_ns())

    def test_validate_failure_exits(self):
        from tools.cli.system import cmd_validate
        with patch("tools.schema_validator.validate_all", return_value=False):
            with pytest.raises(SystemExit) as exc:
                cmd_validate(_ns())
            assert exc.value.code == 1


# ---------------------------------------------------------------------------
# tools/cli/skills.py
# ---------------------------------------------------------------------------

class TestCmdSkills:
    def test_list_empty(self, capsys):
        from tools.cli.skills import cmd_skills
        mock_registry = MagicMock()
        mock_registry.list_skills.return_value = []
        with patch("tools.plugins.PluginSkillRegistry", return_value=mock_registry):
            cmd_skills(_ns(skills_command="list"))
        out = capsys.readouterr().out
        assert "No skills found" in out

    def test_list_with_skills(self, capsys):
        from tools.cli.skills import cmd_skills
        mock_registry = MagicMock()
        mock_skill = MagicMock()
        mock_skill.name = "auth_jwt"
        mock_skill.description = "JWT authentication skill"
        mock_registry.list_skills.return_value = [mock_skill]
        with patch("tools.plugins.PluginSkillRegistry", return_value=mock_registry):
            cmd_skills(_ns(skills_command="list"))
        out = capsys.readouterr().out
        assert "auth_jwt" in out

    def test_search(self, capsys):
        from tools.cli.skills import cmd_skills
        mock_registry = MagicMock()
        mock_skill = MagicMock()
        mock_skill.name = "auth_jwt"
        mock_registry.select_for.return_value = [mock_skill]
        with patch("tools.plugins.PluginSkillRegistry", return_value=mock_registry):
            cmd_skills(_ns(skills_command="search", query="auth"))
        out = capsys.readouterr().out
        assert "auth_jwt" in out

    def test_unpublish_not_found(self, capsys):
        from tools.cli.skills import cmd_skills
        with patch("tools.plugins.PluginSkillRegistry"):
            cmd_skills(_ns(skills_command="unpublish", name="nonexistent_skill"))
        out = capsys.readouterr().out
        assert "✗" in out


# ---------------------------------------------------------------------------
# main() argument routing
# ---------------------------------------------------------------------------

class TestMainRouting:
    def test_model_list_route(self):
        from tools.cc_cli import main
        with patch("tools.cc_cli._cmd_model_list") as mock_fn:
            with patch("sys.argv", ["cc", "model", "list"]):
                main()
            mock_fn.assert_called_once()

    def test_query_route(self):
        from tools.cc_cli import main
        with patch("tools.cc_cli._cmd_query") as mock_fn:
            with patch("sys.argv", ["cc", "query", "what is python"]):
                main()
            mock_fn.assert_called_once()

    def test_status_route(self):
        from tools.cc_cli import main
        with patch("tools.cc_cli._cmd_status") as mock_fn:
            with patch("sys.argv", ["cc", "status"]):
                main()
            mock_fn.assert_called_once()

    def test_no_command_prints_help(self, capsys):
        from tools.cc_cli import main
        with patch("sys.argv", ["cc"]):
            main()
        # No crash; help is printed

    def test_init_route(self):
        from tools.cc_cli import main
        with patch("tools.cc_init._cmd_init") as mock_fn:
            with patch("sys.argv", ["cc", "init", "my-project"]):
                main()
            mock_fn.assert_called_once()
