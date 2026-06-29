"""Tests for CC Switch, CLI, and GUI modules."""

import argparse
import os
import tempfile
from unittest.mock import patch

import pytest

from tools.llm.model_switcher import (
    ModelRegistry,
    ModelSwitcher,
    ProviderConfig,
    DEFAULT_PROVIDERS,
)


# ---------------------------------------------------------------------------
# ModelRegistry tests
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def test_default_providers_loaded(self):
        registry = ModelRegistry()
        providers = registry.list_providers()
        assert "anthropic" in providers
        assert "openai" in providers
        assert "gemini" in providers
        assert len(providers) >= 10

    def test_get_provider(self):
        registry = ModelRegistry()
        cfg = registry.get("anthropic")
        assert cfg is not None
        assert cfg.name == "anthropic"
        assert cfg.default_model == "claude-sonnet-4-6"

    def test_get_unknown_provider(self):
        registry = ModelRegistry()
        assert registry.get("nonexistent") is None

    def test_list_display(self):
        registry = ModelRegistry()
        entries = registry.list_display()
        assert len(entries) > 0
        assert all("name" in e for e in entries)
        assert all("has_api_key" in e for e in entries)

    def test_add_provider(self):
        registry = ModelRegistry()
        custom = ProviderConfig(
            name="custom_llm",
            display_name="Custom LLM",
            default_model="custom-v1",
            api_key_env="CUSTOM_API_KEY",
            models=["custom-v1", "custom-v2"],
        )
        registry.add_provider(custom)
        assert registry.get("custom_llm") is not None
        assert registry.get("custom_llm").default_model == "custom-v1"

    def test_remove_provider(self):
        registry = ModelRegistry()
        assert registry.remove_provider("nonexistent") is False
        # Cannot remove built-in but test the API
        registry.add_provider(ProviderConfig(
            name="temp", display_name="Temp", default_model="m",
            api_key_env="TEMP_KEY",
        ))
        assert registry.remove_provider("temp") is True

    def test_get_api_key(self):
        registry = ModelRegistry()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            key = registry.get_api_key("openai")
            assert key == "test-key"

    def test_get_base_url(self):
        registry = ModelRegistry()
        with patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "http://test"}):
            url = registry.get_base_url("anthropic")
            assert url == "http://test"

    def test_to_json(self):
        registry = ModelRegistry()
        json_str = registry.to_json()
        assert "anthropic" in json_str
        assert "openai" in json_str

    def test_case_insensitive(self):
        registry = ModelRegistry()
        cfg = registry.get("ANTHROPIC")
        assert cfg is not None
        assert cfg.name == "anthropic"


# ---------------------------------------------------------------------------
# ModelSwitcher tests
# ---------------------------------------------------------------------------

class TestModelSwitcher:
    @pytest.fixture
    def switcher(self):
        return ModelSwitcher(ModelRegistry())

    def test_switch_provider(self, switcher):
        assert switcher.switch("openai", "gpt-4o") is True
        assert switcher.current == ("openai", "gpt-4o")

    def test_switch_without_model(self, switcher):
        assert switcher.switch("anthropic") is True
        provider, model = switcher.current
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"  # default

    def test_switch_unknown_provider(self, switcher):
        assert switcher.switch("nonexistent") is False

    def test_auto_select_with_no_keys(self, switcher):
        with patch.dict(os.environ, {}, clear=True):
            provider, model = switcher.auto_select()
            assert provider == "mock"

    def test_auto_select_with_openai_key(self, switcher):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            provider, model = switcher.auto_select()
            assert provider == "openai"
            assert model == "gpt-4o"

    def test_auto_select_priority(self, switcher):
        """Anthropic should be selected over OpenAI when both keys present."""
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sk-ant",
            "OPENAI_API_KEY": "sk-openai",
        }):
            provider, model = switcher.auto_select()
            assert provider == "anthropic"

    def test_set_fallback_chain(self, switcher):
        chain = [("anthropic", "claude-sonnet-4-6"), ("openai", "gpt-4o")]
        switcher.set_fallback_chain(chain)
        assert switcher._fallback_chain == chain

    def test_create_provider_mock(self, switcher):
        switcher.switch("mock")
        provider = switcher.create_provider()
        assert provider.get_name() == "mock"

    def test_create_provider_anthropic(self, switcher):
        switcher.switch("anthropic", "claude-sonnet-4-6")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            provider = switcher.create_provider()
            assert "Claude" in provider.get_name() or "anthropic" in provider.get_name()

    def test_repr(self, switcher):
        switcher.switch("openai", "gpt-4o")
        assert "openai" in repr(switcher)
        assert "gpt-4o" in repr(switcher)


# ---------------------------------------------------------------------------
# CLI argument parser tests
# ---------------------------------------------------------------------------

class TestCLIParser:
    def test_model_list(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["model", "list"])
        assert args.command == "model"
        assert args.model_command == "list"

    def test_model_switch(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["model", "switch", "anthropic", "--model", "claude-opus-4-7"])
        assert args.command == "model"
        assert args.model_command == "switch"
        assert args.provider == "anthropic"
        assert args.model == "claude-opus-4-7"

    def test_query(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["query", "What is Python?"])
        assert args.command == "query"
        assert args.query == "What is Python?"

    def test_search(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["search", "Python"])
        assert args.command == "search"

    def test_serve(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["serve", "--port", "9000"])
        assert args.command == "serve"
        assert args.port == 9000

    def test_gui(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["gui"])
        assert args.command == "gui"

    def test_status(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_eval(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["eval"])
        assert args.command == "eval"

    def test_run(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "Build auth module"])
        assert args.command == "run"
        assert args.requirement == "Build auth module"

    def test_no_command(self):
        from tools.cc_cli import build_parser
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None


# ---------------------------------------------------------------------------
# CLI command integration tests
# ---------------------------------------------------------------------------

class TestCLICommands:
    def test_cmd_model_list(self, capsys):
        from tools.cc_cli import _cmd_model_list
        args = argparse.Namespace()
        _cmd_model_list(args)
        captured = capsys.readouterr()
        assert "CC Switch" in captured.out
        assert "anthropic" in captured.out

    def test_cmd_status(self, capsys):
        from tools.cc_cli import _cmd_status
        args = argparse.Namespace()
        _cmd_status(args)
        captured = capsys.readouterr()
        assert "CC Status" in captured.out

    def test_cmd_model_switch(self, capsys):
        from tools.cc_cli import _cmd_model_switch
        args = argparse.Namespace(provider="anthropic", model="claude-sonnet-4-6")
        _cmd_model_switch(args)
        captured = capsys.readouterr()
        assert "Switched" in captured.out

    def test_cmd_model_switch_unknown(self, capsys):
        from tools.cc_cli import _cmd_model_switch
        args = argparse.Namespace(provider="nonexistent", model=None)
        _cmd_model_switch(args)
        captured = capsys.readouterr()
        assert "Unknown" in captured.out

    def test_cmd_model_test(self, capsys):
        from tools.cc_cli import _cmd_model_test
        args = argparse.Namespace(provider=None)
        _cmd_model_test(args)
        captured = capsys.readouterr()
        assert "CC Switch" in captured.out

    def test_cmd_query(self, capsys):
        from tools.cc_cli import _cmd_query
        args = argparse.Namespace(query="What is Python?", top_k=3, docs=None)
        _cmd_query(args)
        captured = capsys.readouterr()
        assert "Query:" in captured.out
        assert "Intent:" in captured.out

    def test_cmd_search(self, capsys):
        from tools.cc_cli import _cmd_search
        args = argparse.Namespace(query="Python", top_k=3)
        _cmd_search(args)
        captured = capsys.readouterr()
        assert "Search:" in captured.out

    def test_cmd_run(self, capsys):
        from tools.cc_cli import _cmd_run
        args = argparse.Namespace(requirement="Build auth module")
        _cmd_run(args)
        captured = capsys.readouterr()
        assert "CC Pipeline" in captured.out


# ---------------------------------------------------------------------------
# ProviderConfig tests
# ---------------------------------------------------------------------------

class TestProviderConfig:
    def test_default_models(self):
        cfg = DEFAULT_PROVIDERS["anthropic"]
        assert "claude-sonnet-4-6" in cfg.models
        assert cfg.default_model == "claude-sonnet-4-6"

    def test_all_providers_have_api_key_env(self):
        for name, cfg in DEFAULT_PROVIDERS.items():
            # mock provider 不需要 API Key，api_key_env 可以为空
            if name == "mock":
                continue
            assert cfg.api_key_env, f"{name} missing api_key_env"

    def test_all_providers_have_models(self):
        for name, cfg in DEFAULT_PROVIDERS.items():
            assert len(cfg.models) > 0, f"{name} has no models"

    def test_custom_provider(self):
        cfg = ProviderConfig(
            name="test", display_name="Test", default_model="m1",
            api_key_env="TEST_KEY", models=["m1", "m2"],
        )
        assert cfg.name == "test"
        assert cfg.supports_json  # default is True
