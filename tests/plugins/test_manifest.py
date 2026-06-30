# tests/plugins/test_manifest.py

"""
tests/plugins/test_manifest.py — Manifest 数据类和加载器单元测试。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from tools.plugins.manifest import (
    SkillManifest,
    ToolManifest,
    ManifestError,
    load_manifest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_skill_manifest_dict() -> dict:
    return {
        "name": "test_skill",
        "display_name": "Test Skill",
        "description": "A test skill",
        "version": "1.0.0",
        "intents": ["code_generation"],
        "tools": ["compile"],
        "entry_agent": "expert_test",
        "risk_level": "medium",
        "prompt_paths": {"system": "prompts/system.md"},
    }


@pytest.fixture
def valid_tool_manifest_dict() -> dict:
    return {
        "name": "test_tool",
        "namespace": "test",
        "description": "A test tool",
        "version": "1.0.0",
        "risk_level": "low",
        "requires_auth": False,
        "requires_approval": False,
        "idempotent": True,
        "handler": "some.module:func",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
    }


@pytest.fixture
def skill_json_file(tmp_path: Path, valid_skill_manifest_dict: dict) -> Path:
    path = tmp_path / "skill.json"
    path.write_text(json.dumps(valid_skill_manifest_dict), encoding="utf-8")
    return path


@pytest.fixture
def tool_json_file(tmp_path: Path, valid_tool_manifest_dict: dict) -> Path:
    path = tmp_path / "tool.json"
    path.write_text(json.dumps(valid_tool_manifest_dict), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Skill Manifest Loading
# ---------------------------------------------------------------------------

class TestLoadSkillManifest:
    def test_load_skill_manifest_valid(self, skill_json_file: Path):
        """正常 skill.json 解析为 SkillManifest。"""
        manifest = load_manifest(skill_json_file, "skill")
        assert isinstance(manifest, SkillManifest)
        assert manifest.name == "test_skill"
        assert manifest.display_name == "Test Skill"
        assert manifest.intents == ("code_generation",)
        assert manifest.risk_level == "medium"

    def test_load_skill_manifest_missing_file(self):
        """文件不存在时抛出 ManifestError。"""
        with pytest.raises(ManifestError, match="not found"):
            load_manifest(Path("/nonexistent/skill.json"), "skill")

    def test_load_skill_manifest_invalid_json(self, tmp_path: Path):
        """JSON 解析失败时抛出 ManifestError。"""
        path = tmp_path / "skill.json"
        path.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(ManifestError, match="Invalid JSON"):
            load_manifest(path, "skill")

    def test_load_skill_manifest_missing_required_field(self, tmp_path: Path):
        """缺少必填字段时抛出 ManifestError。"""
        incomplete = {"name": "test", "display_name": "Test"}
        path = tmp_path / "skill.json"
        path.write_text(json.dumps(incomplete), encoding="utf-8")
        with pytest.raises(ManifestError, match="missing required fields"):
            load_manifest(path, "skill")


# ---------------------------------------------------------------------------
# Tool Manifest Loading
# ---------------------------------------------------------------------------

class TestLoadToolManifest:
    def test_load_tool_manifest_valid(self, tool_json_file: Path):
        """正常 tool.json 解析为 ToolManifest。"""
        manifest = load_manifest(tool_json_file, "tool")
        assert isinstance(manifest, ToolManifest)
        assert manifest.name == "test_tool"
        assert manifest.namespace == "test"
        assert manifest.requires_approval is False
        assert manifest.idempotent is True

    def test_load_tool_manifest_missing_required_field(self, tmp_path: Path):
        """缺少必填字段时抛出 ManifestError。"""
        incomplete = {"name": "test_tool"}
        path = tmp_path / "tool.json"
        path.write_text(json.dumps(incomplete), encoding="utf-8")
        with pytest.raises(ManifestError, match="missing required fields"):
            load_manifest(path, "tool")


# ---------------------------------------------------------------------------
# Manifest Immutability
# ---------------------------------------------------------------------------

class TestManifestImmutability:
    def test_skill_manifest_immutable(self, skill_json_file: Path):
        """SkillManifest 是 frozen dataclass，不可变。"""
        manifest = load_manifest(skill_json_file, "skill")
        with pytest.raises(AttributeError):
            manifest.name = "new_name"

    def test_tool_manifest_immutable(self, tool_json_file: Path):
        """ToolManifest 是 frozen dataclass，不可变。"""
        manifest = load_manifest(tool_json_file, "tool")
        with pytest.raises(AttributeError):
            manifest.name = "new_name"


# ---------------------------------------------------------------------------
# Error Cases
# ---------------------------------------------------------------------------

class TestManifestErrors:
    def test_unknown_manifest_type(self, skill_json_file: Path):
        """未知 manifest 类型抛出 ManifestError。"""
        with pytest.raises(ManifestError, match="Unknown manifest type"):
            load_manifest(skill_json_file, "unknown")

    def test_manifest_error_is_exception(self):
        """ManifestError 是 Exception 子类。"""
        with pytest.raises(Exception):
            raise ManifestError("test")
