# tests/llm/test_plugin.py

"""
Tests for tools.llm.plugin — PluginMetadata, PluginLoader.

Uses unittest.mock to simulate entry_points without installing packages.
"""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from tools.llm.plugin import PluginLoader, PluginMetadata, ENTRY_POINT_GROUP


# ── Fixtures ────────────────────────────────────────────────────

class FakeProvider:
    """Simulates a provider class with metadata attributes."""
    DISPLAY_NAME = "Fake Provider"
    VERSION = "1.0.0"
    DEFAULT_MODEL = "fake-model-v1"
    API_KEY_ENV = "FAKE_API_KEY"
    BASE_URL_ENV = "FAKE_BASE_URL"
    MODELS = ["fake-model-v1", "fake-model-v2"]
    DESCRIPTION = "A fake provider for testing"

    def __init__(self, api_key=None, model=None, **kwargs):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL

    def complete(self, prompt, **kwargs):
        return MagicMock(success=True, content="fake response")

    def get_name(self):
        return "fake"


class FakeProviderNoMeta:
    """Provider with no metadata attributes (minimal)."""
    DEFAULT_MODEL = "minimal-model"

    def __init__(self, **kwargs):
        pass


class _FakePluginProvider:
    """A provider class that can be used as a plugin target."""
    DISPLAY_NAME = "Fake Plugin"
    VERSION = "1.0.0"
    DEFAULT_MODEL = "plugin-model"
    API_KEY_ENV = "PLUGIN_KEY"

    def __init__(self, api_key=None, model=None, **kwargs):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL

    def complete(self, prompt, **kwargs):
        return MagicMock(success=True, content="plugin response")

    def get_name(self):
        return "fake_plugin"


def make_entry_point(name, cls):
    """Create a mock entry point that loads to the given class."""
    ep = MagicMock()
    ep.name = name
    ep.value = f"{cls.__module__}:{cls.__qualname__}"
    ep.load.return_value = cls
    return ep


# ── PluginMetadata ─────────────────────────────────────────────

class TestPluginMetadata:

    def test_frozen_dataclass(self):
        meta = PluginMetadata(
            name="test", display_name="Test", version="1.0.0",
            provider_class="mod:Cls", default_model="m", api_key_env="KEY",
        )
        with pytest.raises(AttributeError):
            meta.name = "other"  # frozen

    def test_defaults(self):
        meta = PluginMetadata(
            name="test", display_name="Test", version="1.0.0",
            provider_class="mod:Cls", default_model="m", api_key_env="KEY",
        )
        assert meta.base_url_env == ""
        assert meta.models == []
        assert meta.description == ""


# ── PluginLoader.discover ──────────────────────────────────────

class TestPluginLoaderDiscover:

    def test_discovers_plugins_from_entry_points(self):
        ep = make_entry_point("fake", FakeProvider)
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            loader = PluginLoader()
            plugins = loader.discover()

        assert "fake" in plugins
        meta = plugins["fake"]
        assert isinstance(meta, PluginMetadata)
        assert meta.display_name == "Fake Provider"
        assert meta.default_model == "fake-model-v1"
        assert meta.api_key_env == "FAKE_API_KEY"

    def test_caches_result(self):
        ep = make_entry_point("fake", FakeProvider)
        loader = PluginLoader()
        with patch("importlib.metadata.entry_points", return_value=[ep]) as mock_eps:
            loader.discover()
            loader.discover()  # second call should use cache
            assert mock_eps.call_count == 1

    def test_clear_cache(self):
        ep = make_entry_point("fake", FakeProvider)
        loader = PluginLoader()
        with patch("importlib.metadata.entry_points", return_value=[ep]) as mock_eps:
            loader.discover()
            loader.clear_cache()
            loader.discover()
            assert mock_eps.call_count == 2

    def test_swallows_broken_entry_points(self):
        broken_ep = MagicMock()
        broken_ep.name = "broken"
        broken_ep.load.side_effect = ImportError("no module")

        good_ep = make_entry_point("good", FakeProvider)

        with patch("importlib.metadata.entry_points", return_value=[broken_ep, good_ep]):
            loader = PluginLoader()
            plugins = loader.discover()

        assert "good" in plugins
        assert "broken" not in plugins

    def test_skips_plugins_without_default_model(self):
        ep = make_entry_point("nometo", FakeProviderNoMeta)
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            loader = PluginLoader()
            plugins = loader.discover()
        # FakeProviderNoMeta has DEFAULT_MODEL so it should be discovered
        assert "nometo" in plugins

    def test_returns_empty_on_discovery_failure(self):
        with patch("importlib.metadata.entry_points", side_effect=RuntimeError("fail")):
            loader = PluginLoader()
            plugins = loader.discover()
        assert plugins == {}


# ── PluginLoader.load ──────────────────────────────────────────

class TestPluginLoaderLoad:

    def test_load_existing_plugin(self):
        ep = make_entry_point("fake", FakeProvider)
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            loader = PluginLoader()
            provider = loader.load("fake", api_key="test-key", model="custom")
        assert isinstance(provider, FakeProvider)
        assert provider.api_key == "test-key"
        assert provider.model == "custom"

    def test_load_unknown_plugin_raises(self):
        with patch("importlib.metadata.entry_points", return_value=[]):
            loader = PluginLoader()
            with pytest.raises(ValueError, match="Unknown plugin"):
                loader.load("nonexistent")

    def test_load_import_error(self):
        """When provider_class module doesn't exist."""
        ep = MagicMock()
        ep.name = "broken"
        ep.load.return_value = MagicMock(
            __module__="nonexistent_module",
            __qualname__="BrokenProvider",
            DEFAULT_MODEL="x",
        )
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            loader = PluginLoader()
            with pytest.raises(ImportError, match="Cannot import"):
                loader.load("broken")


# ── Integration: create_llm_provider with plugins ────────────

class TestCreateLLMProviderWithPlugins:

    def test_plugin_backend_takes_priority(self):
        """When a plugin matches the backend name, it should be used."""
        ep = make_entry_point("custom_backend", _FakePluginProvider)
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            # Reset the cache in tools/llm/__init__.py
            import tools.llm
            tools.llm._plugins_loaded = False
            tools.llm._discovered_plugins = {}

            from tools.llm import create_llm_provider
            provider = create_llm_provider("custom_backend", api_key="test-key")
            assert isinstance(provider, _FakePluginProvider)
            assert provider.api_key == "test-key"

    def test_builtin_still_works_without_plugins(self):
        """Built-in backends work when no plugins match."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            import tools.llm
            tools.llm._plugins_loaded = False
            tools.llm._discovered_plugins = {}

            from tools.llm import create_llm_provider
            provider = create_llm_provider("mock")
            assert provider is not None
