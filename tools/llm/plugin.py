# tools/llm/plugin.py

"""
LLM Provider plugin discovery via Python entry_points.

Built-in providers register as [project.entry-points."cc.plugins.providers"]
in pyproject.toml. Third-party packages declare the same entry point group.
PluginLoader.discover() loads both uniformly — no hardcoded backend list.

Usage:
    from tools.llm.plugin import PluginLoader
    loader = PluginLoader()
    plugins = loader.discover()  # dict[str, PluginMetadata]
    provider = loader.load("anthropic", api_key="sk-...")
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "cc.plugins.providers"


@dataclass(frozen=True)
class PluginMetadata:
    """Metadata for a discovered LLM provider plugin."""

    name: str
    display_name: str
    version: str
    provider_class: str  # dotted path: "tools.llm.anthropic:AnthropicClaudeProvider"
    default_model: str
    api_key_env: str
    base_url_env: str = ""
    models: List[str] = field(default_factory=list)
    description: str = ""


class PluginLoader:
    """Discover and load LLM provider plugins via entry_points."""

    def __init__(self, group: str = ENTRY_POINT_GROUP) -> None:
        self._group = group
        self._cache: Optional[dict] = None

    def discover(self) -> dict:
        """Discover all registered plugins. Returns dict[str, PluginMetadata].

        Caches result after first call. Swallows exceptions so a broken
        third-party plugin never crashes provider creation.
        """
        if self._cache is not None:
            return self._cache

        plugins: dict[str, PluginMetadata] = {}
        try:
            eps = importlib.metadata.entry_points(group=self._group)
            for ep in eps:
                try:
                    cls = ep.load()
                    meta = self._extract_metadata(ep, cls)
                    if meta:
                        plugins[meta.name] = meta
                        logger.debug("[PluginLoader] Discovered plugin: %s (%s)", meta.name, meta.provider_class)
                except Exception as e:
                    logger.warning("[PluginLoader] Failed to load entry point '%s': %s", ep.name, e)
        except Exception as e:
            logger.warning("[PluginLoader] entry_points discovery failed: %s", e)

        self._cache = plugins
        return plugins

    def load(self, name: str, **kwargs) -> Any:
        """Load a provider instance by plugin name.

        Looks up the dotted provider_class path, imports the module,
        instantiates the class with provided kwargs.
        """
        plugins = self.discover()
        if name not in plugins:
            raise ValueError(
                f"Unknown plugin '{name}'. "
                f"Available: {list(plugins.keys())}"
            )

        meta = plugins[name]
        module_path, _, cls_name = meta.provider_class.rpartition(":")
        if not module_path:
            raise ValueError(
                f"Invalid provider_class '{meta.provider_class}' for plugin '{name}'. "
                f"Expected format: 'module.path:ClassName'"
            )

        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
        except (ImportError, AttributeError) as e:
            raise ImportError(
                f"Cannot import provider class for plugin '{name}': {e}. "
                f"Install required dependencies and try again."
            ) from e

        # If the class has a factory function, use it; else instantiate directly
        if hasattr(cls, "create_provider"):
            return cls.create_provider(**kwargs)
        return cls(**kwargs)

    def list_available(self) -> list:
        """List metadata for all discovered plugins."""
        return list(self.discover().values())

    def clear_cache(self) -> None:
        """Clear the discovery cache (useful for testing)."""
        self._cache = None

    @staticmethod
    def _extract_metadata(ep, cls) -> Optional[PluginMetadata]:
        """Extract PluginMetadata from an entry point and its loaded class."""
        name = ep.name

        # Try class-level metadata attributes first
        display_name = getattr(cls, "DISPLAY_NAME", name)
        version = getattr(cls, "VERSION", "0.0.0")
        default_model = getattr(cls, "DEFAULT_MODEL", "")
        api_key_env = getattr(cls, "API_KEY_ENV", "")
        base_url_env = getattr(cls, "BASE_URL_ENV", "")
        models = getattr(cls, "MODELS", [])
        description = getattr(cls, "DESCRIPTION", cls.__doc__ or "")

        # The entry point value is the dotted path to the class
        provider_class = f"{cls.__module__}:{cls.__qualname__}"

        if not default_model:
            logger.warning("[PluginLoader] Plugin '%s' has no DEFAULT_MODEL; skipping", name)
            return None

        return PluginMetadata(
            name=name,
            display_name=display_name,
            version=version,
            provider_class=provider_class,
            default_model=default_model,
            api_key_env=api_key_env,
            base_url_env=base_url_env,
            models=list(models),
            description=description[:200],
        )


__all__ = ["PluginMetadata", "PluginLoader", "ENTRY_POINT_GROUP"]
