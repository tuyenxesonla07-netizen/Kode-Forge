# tools/plugins/manifest.py

"""
Plugin manifest data classes and loader.

借鉴 codex 的 skill.json / tool.json 模式，用 frozen dataclass 表达不可变 manifest。

用法:
    from tools.plugins.manifest import SkillManifest, ToolManifest, load_manifest

    skill = load_manifest(Path("plugins/skills/code_generator/skill.json"), "skill")
    tool = load_manifest(Path("plugins/tools/ast_validator/tool.json"), "tool")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ManifestError(Exception):
    """Manifest 加载或解析错误。"""


# ---------------------------------------------------------------------------
# Skill Manifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillManifest:
    """Skill 插件 manifest — 描述一个 Skill 的元数据。"""
    name: str
    display_name: str
    description: str
    version: str
    intents: tuple[str, ...]
    tools: tuple[str, ...]
    entry_agent: str
    risk_level: str                    # "low" | "medium" | "high"
    prompt_paths: dict[str, str]
    workflow_path: str = ""


# ---------------------------------------------------------------------------
# Tool Manifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolManifest:
    """Tool 插件 manifest — 描述一个 Tool 的元数据。"""
    name: str
    namespace: str
    description: str
    version: str
    risk_level: str                    # "low" | "medium" | "high"
    requires_auth: bool
    requires_approval: bool
    idempotent: bool
    handler: str                       # "module:function"
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_SKILL_REQUIRED_FIELDS = {"name", "display_name", "description", "version",
                          "intents", "tools", "entry_agent", "risk_level"}

_TOOL_REQUIRED_FIELDS = {"name", "namespace", "description", "version",
                         "risk_level", "requires_auth", "requires_approval",
                         "idempotent", "handler", "input_schema", "output_schema"}


def load_manifest(path: Path, manifest_type: str) -> SkillManifest | ToolManifest:
    """从 JSON 文件加载 manifest。

    Args:
        path: manifest 文件路径 (skill.json 或 tool.json)
        manifest_type: "skill" 或 "tool"

    Returns:
        SkillManifest 或 ToolManifest 实例

    Raises:
        ManifestError: 文件不存在、JSON 解析失败、缺少必填字段
    """
    if not path.exists():
        raise ManifestError(f"Manifest file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ManifestError(f"Invalid JSON in {path}: {e}") from e

    if manifest_type == "skill":
        return _parse_skill_manifest(data, path)
    elif manifest_type == "tool":
        return _parse_tool_manifest(data, path)
    else:
        raise ManifestError(f"Unknown manifest type: {manifest_type!r}")


def _parse_skill_manifest(data: dict, path: Path) -> SkillManifest:
    """解析 Skill manifest JSON。"""
    missing = _SKILL_REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ManifestError(
            f"Skill manifest {path} missing required fields: {sorted(missing)}"
        )

    return SkillManifest(
        name=data["name"],
        display_name=data["display_name"],
        description=data["description"],
        version=data["version"],
        intents=tuple(data.get("intents", [])),
        tools=tuple(data.get("tools", [])),
        entry_agent=data["entry_agent"],
        risk_level=data["risk_level"],
        prompt_paths=dict(data.get("prompt_paths", {})),
        workflow_path=data.get("workflow_path", ""),
    )


def _parse_tool_manifest(data: dict, path: Path) -> ToolManifest:
    """解析 Tool manifest JSON。"""
    missing = _TOOL_REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ManifestError(
            f"Tool manifest {path} missing required fields: {sorted(missing)}"
        )

    return ToolManifest(
        name=data["name"],
        namespace=data["namespace"],
        description=data["description"],
        version=data["version"],
        risk_level=data["risk_level"],
        requires_auth=data["requires_auth"],
        requires_approval=data["requires_approval"],
        idempotent=data["idempotent"],
        handler=data["handler"],
        input_schema=dict(data.get("input_schema", {})),
        output_schema=dict(data.get("output_schema", {})),
    )
