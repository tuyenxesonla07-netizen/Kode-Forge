# tests/plugins/test_tool_registry.py

"""
tests/plugins/test_tool_registry.py — PluginToolRegistry 单元测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.plugins.tool_registry import PluginToolRegistry, PluginToolEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_tool(dir_path: Path, manifest: dict) -> None:
    """写入 tool.json 到指定目录。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "tool.json").write_text(json.dumps(manifest), encoding="utf-8")


def _make_valid_tool(name: str, handler: str = "some.module:func") -> dict:
    return {
        "name": name,
        "namespace": "test",
        "description": f"Tool {name}",
        "version": "1.0.0",
        "risk_level": "low",
        "requires_auth": False,
        "requires_approval": False,
        "idempotent": True,
        "handler": handler,
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPluginToolRegistry:
    def test_load_tools_from_directory(self, tmp_path: Path):
        """从目录扫描加载多个 Tool。"""
        _write_tool(tmp_path / "tools" / "tool_a", _make_valid_tool("tool_a"))
        _write_tool(tmp_path / "tools" / "tool_b", _make_valid_tool("tool_b"))

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        assert len(registry) == 2
        assert registry.get("tool_a") is not None
        assert registry.get("tool_b") is not None

    def test_get_tool_found(self, tmp_path: Path):
        """名称命中时返回 Tool entry。"""
        _write_tool(tmp_path / "tools" / "my_tool", _make_valid_tool("my_tool"))

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        entry = registry.get("my_tool")
        assert entry is not None
        assert entry.manifest.name == "my_tool"
        assert entry.manifest.risk_level == "low"

    def test_get_tool_not_found(self, tmp_path: Path):
        """名称未命中时返回 None。"""
        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()
        assert registry.get("nonexistent") is None

    def test_call_tool_success(self, tmp_path: Path):
        """调用已加载 Tool 的 handler 成功。"""
        _write_tool(
            tmp_path / "tools" / "working_tool",
            _make_valid_tool(
                "working_tool",
                handler="tests.plugins.fixtures.tools.ast_validator.handler:validate_ast",
            ),
        )

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        result = registry.call("working_tool", context={}, params={"code": "x = 1"})
        assert result["success"] is True
        assert result["result"]["valid"] is True

    def test_call_tool_not_found(self, tmp_path: Path):
        """调用不存在的 Tool 抛出 KeyError。"""
        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        with pytest.raises(KeyError, match="nonexistent"):
            registry.call("nonexistent", context={}, params={})

    def test_call_tool_handler_error(self, tmp_path: Path):
        """handler 执行异常时返回错误结果而非崩溃。"""
        _write_tool(
            tmp_path / "tools" / "error_tool",
            _make_valid_tool(
                "error_tool",
                handler="tests.plugins.fixtures.tools.ast_validator.handler:validate_ast",
            ),
        )

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        # 传入无效参数导致 handler 异常
        result = registry.call("error_tool", context={}, params={})
        # handler 会因缺少 code 参数而抛出 TypeError
        assert result["success"] is False
        assert result["error"] != ""

    def test_list_tools(self, tmp_path: Path):
        """list() 返回所有已加载 Tool 的摘要信息。"""
        _write_tool(tmp_path / "tools" / "tool_a", _make_valid_tool("tool_a"))

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        tools = registry.list()
        assert len(tools) == 1
        assert tools[0]["name"] == "tool_a"
        assert "namespace" in tools[0]
        assert "risk_level" in tools[0]

    def test_load_error_graceful(self, tmp_path: Path):
        """损坏的 tool.json 不崩溃，记录到 load_errors。"""
        broken_dir = tmp_path / "tools" / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "tool.json").write_text("{invalid", encoding="utf-8")

        _write_tool(tmp_path / "tools" / "good_tool", _make_valid_tool("good_tool"))

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        assert registry.get("good_tool") is not None
        assert len(registry.load_errors) == 1

    def test_empty_directory(self, tmp_path: Path):
        """空目录不报错。"""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        assert len(registry) == 0

    def test_no_plugins_dir(self):
        """plugins_dir 为 None 时不报错。"""
        registry = PluginToolRegistry(plugins_dir=None)
        registry.load()
        assert len(registry) == 0

    def test_tool_requires_approval(self, tmp_path: Path):
        """Tool manifest 的 requires_approval 字段正确读取。"""
        tool_manifest = _make_valid_tool("approval_tool")
        tool_manifest["requires_approval"] = True
        tool_manifest["risk_level"] = "high"
        _write_tool(tmp_path / "tools" / "approval_tool", tool_manifest)

        registry = PluginToolRegistry(plugins_dir=tmp_path)
        registry.load()

        entry = registry.get("approval_tool")
        assert entry is not None
        assert entry.manifest.requires_approval is True
        assert entry.manifest.risk_level == "high"
