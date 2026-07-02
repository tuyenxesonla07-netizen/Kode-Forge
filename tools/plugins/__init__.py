# tools/plugins/__init__.py

"""
tools/plugins — 插件注册系统。

提供 Skill/Tool 动态加载、manifest 解析、声明式工作流执行。

用法:
    from tools.plugins import PluginSkillRegistry, PluginToolRegistry, WorkflowRunner

    skill_registry = PluginSkillRegistry(plugins_dir=Path("plugins"))
    skill_registry.load()

    tool_registry = PluginToolRegistry(plugins_dir=Path("plugins"))
    tool_registry.load()
"""

from __future__ import annotations

from tools.plugins.manifest import (
    SkillManifest,
    ToolManifest,
    ManifestError,
    load_manifest,
)
from tools.plugins.skill_registry import PluginSkillRegistry, PluginSkillEntry
from tools.plugins.tool_registry import PluginToolRegistry, PluginToolEntry
from tools.plugins.workflow_runner import WorkflowRunner, WorkflowDefinition

__all__ = [
    # Manifest
    "SkillManifest",
    "ToolManifest",
    "ManifestError",
    "load_manifest",
    # Skill Registry
    "PluginSkillRegistry",
    "PluginSkillEntry",
    # Tool Registry
    "PluginToolRegistry",
    "PluginToolEntry",
    # Workflow Runner
    "WorkflowRunner",
    "WorkflowDefinition",
]
