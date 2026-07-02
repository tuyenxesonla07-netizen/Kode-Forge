# tools/plugins/tool_registry.py

"""
PluginToolRegistry — 基于 manifest.json 的 Tool 动态加载。

借鉴 codex 的 ToolRegistry 设计，从 plugins/tools/*/tool.json 扫描加载。

用法:
    from tools.plugins.tool_registry import PluginToolRegistry

    registry = PluginToolRegistry(plugins_dir=Path("plugins"))
    registry.load()
    result = registry.call("ast_validator", context={}, params={"code": "..."})
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.plugins.manifest import ToolManifest, load_manifest, ManifestError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plugin Tool Entry
# ---------------------------------------------------------------------------

@dataclass
class PluginToolEntry:
    """已加载的 Tool 插件条目。"""
    manifest: ToolManifest
    handler: Callable[..., Any] | None = None
    load_error: str = ""

# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class PluginToolRegistry:
    """Tool 插件注册器 — 从 plugins/tools/ 目录扫描加载。"""

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._plugins_dir = plugins_dir
        self._tools: dict[str, PluginToolEntry] = {}
        self._load_errors: dict[str, str] = {}

    def load(self) -> None:
        """扫描 plugins/tools/ 目录，加载所有 tool.json manifest。"""
        if self._plugins_dir is None:
            return

        tools_dir = self._plugins_dir / "tools"
        if not tools_dir.exists():
            logger.warning("[PluginToolRegistry] Tools directory not found: %s", tools_dir)
            return

        for tool_dir in sorted(tools_dir.iterdir()):
            if not tool_dir.is_dir():
                continue

            manifest_path = tool_dir / "tool.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = load_manifest(manifest_path, "tool")
                handler = self._load_handler(manifest)
                entry = PluginToolEntry(manifest=manifest, handler=handler)
                self._tools[manifest.name] = entry
                logger.info("[PluginToolRegistry] Loaded tool: %s", manifest.name)

            except ManifestError as e:
                error_msg = str(e)
                self._load_errors[str(tool_dir)] = error_msg
                logger.warning("[PluginToolRegistry] Failed to load tool at %s: %s",
                               tool_dir, error_msg)

    def _load_handler(self, manifest: ToolManifest) -> Callable[..., Any] | None:
        """动态加载 Tool handler 函数。

        handler 字段格式: "module:function"
        例如: "plugins.tools.ast_validator.handler:validate"
        """
        if not manifest.handler:
            return None

        module_path, _, func_name = manifest.handler.rpartition(":")
        if not module_path or not func_name:
            logger.warning(
                "[PluginToolRegistry] Invalid handler format for tool '%s': %s",
                manifest.name, manifest.handler
            )
            return None

        try:
            module = importlib.import_module(module_path)
            handler = getattr(module, func_name, None)
            if handler is None:
                logger.warning(
                    "[PluginToolRegistry] Handler function '%s' not found in module '%s'",
                    func_name, module_path
                )
            return handler
        except ImportError as e:
            logger.warning(
                "[PluginToolRegistry] Failed to import handler module '%s' for tool '%s': %s",
                module_path, manifest.name, e
            )
            return None

    def get(self, name: str) -> PluginToolEntry | None:
        """根据名称获取 Tool。"""
        return self._tools.get(name)

    def call(self, name: str, context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """调用指定 Tool。

        Args:
            name: Tool 名称
            context: 执行上下文（AgentState 等）
            params: Tool 参数

        Returns:
            执行结果字典 {"success": bool, "result": Any, "error": str}

        Raises:
            KeyError: Tool 不存在
        """
        entry = self._tools.get(name)
        if entry is None:
            raise KeyError(f"Tool not found: {name!r}")

        if entry.handler is None:
            return {"success": False, "result": None,
                    "error": f"Tool '{name}' has no callable handler"}

        try:
            result = entry.handler(context=context, **params)
            return {"success": True, "result": result, "error": ""}
        except Exception as e:
            logger.error("[PluginToolRegistry] Tool '%s' execution error: %s", name, e)
            return {"success": False, "result": None, "error": str(e)}

    def list(self) -> list[dict[str, Any]]:
        """列出所有已加载的 Tool。"""
        return [
            {
                "name": entry.manifest.name,
                "namespace": entry.manifest.namespace,
                "version": entry.manifest.version,
                "risk_level": entry.manifest.risk_level,
                "requires_approval": entry.manifest.requires_approval,
                "has_handler": entry.handler is not None,
            }
            for entry in self._tools.values()
        ]

    @property
    def load_errors(self) -> dict[str, str]:
        """返回加载失败的 Tool 及其错误信息。"""
        return dict(self._load_errors)

    def __len__(self) -> int:
        return len(self._tools)
