# tools/plugins/skill_registry.py

"""
PluginSkillRegistry — 基于 manifest.json 的 Skill 动态加载。

借鉴 codex 的 SkillRegistry 设计，从 plugins/skills/*/skill.json 扫描加载。

用法:
    from tools.plugins.skill_registry import PluginSkillRegistry

    registry = PluginSkillRegistry(plugins_dir=Path("plugins"))
    registry.load()
    entry = registry.get_by_intent("code_generation")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.plugins.manifest import SkillManifest, load_manifest, ManifestError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plugin Skill Entry
# ---------------------------------------------------------------------------

@dataclass
class PluginSkillEntry:
    """已加载的 Skill 插件条目。"""
    manifest: SkillManifest
    prompts: dict[str, str] = field(default_factory=dict)
    load_error: str = ""


# ---------------------------------------------------------------------------
# Skill Registry
# ---------------------------------------------------------------------------

class PluginSkillRegistry:
    """Skill 插件注册器 — 从 plugins/skills/ 目录扫描加载。"""

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._plugins_dir = plugins_dir
        self._skills: dict[str, PluginSkillEntry] = {}
        self._intent_index: dict[str, str] = {}    # intent → skill name
        self._load_errors: dict[str, str] = {}

    def load(self) -> None:
        """扫描 plugins/skills/ 目录，加载所有 skill.json manifest。"""
        if self._plugins_dir is None:
            return

        skills_dir = self._plugins_dir / "skills"
        if not skills_dir.exists():
            logger.warning("[PluginSkillRegistry] Skills directory not found: %s", skills_dir)
            return

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            manifest_path = skill_dir / "skill.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = load_manifest(manifest_path, "skill")
                prompts = self._load_prompts(skill_dir, manifest)
                entry = PluginSkillEntry(manifest=manifest, prompts=prompts)
                self._skills[manifest.name] = entry

                # 构建意图索引
                for intent in manifest.intents:
                    self._intent_index[intent] = manifest.name

                logger.info("[PluginSkillRegistry] Loaded skill: %s", manifest.name)

            except ManifestError as e:
                error_msg = str(e)
                self._load_errors[str(skill_dir)] = error_msg
                logger.warning("[PluginSkillRegistry] Failed to load skill at %s: %s",
                               skill_dir, error_msg)

    def _load_prompts(self, skill_dir: Path, manifest: SkillManifest) -> dict[str, str]:
        """加载 Skill 的 prompt 文件。"""
        prompts: dict[str, str] = {}
        for key, rel_path in manifest.prompt_paths.items():
            prompt_path = skill_dir / rel_path
            if prompt_path.exists():
                try:
                    prompts[key] = prompt_path.read_text(encoding="utf-8")
                except OSError as e:
                    logger.warning("[PluginSkillRegistry] Failed to read prompt %s: %s",
                                   prompt_path, e)
        return prompts

    def get_by_intent(self, intent: str) -> PluginSkillEntry | None:
        """根据意图获取匹配的 Skill。

        Args:
            intent: 意图名称

        Returns:
            匹配的 PluginSkillEntry，未找到返回 None
        """
        skill_name = self._intent_index.get(intent)
        if skill_name is None:
            return None
        return self._skills.get(skill_name)

    def get(self, name: str) -> PluginSkillEntry | None:
        """根据名称获取 Skill。"""
        return self._skills.get(name)

    def list(self) -> list[dict[str, Any]]:
        """列出所有已加载的 Skill。"""
        return [
            {
                "name": entry.manifest.name,
                "display_name": entry.manifest.display_name,
                "version": entry.manifest.version,
                "intents": list(entry.manifest.intents),
                "risk_level": entry.manifest.risk_level,
                "has_workflow": bool(entry.manifest.workflow_path),
            }
            for entry in self._skills.values()
        ]

    @property
    def load_errors(self) -> dict[str, str]:
        """返回加载失败的 Skill 及其错误信息。"""
        return dict(self._load_errors)

    def __len__(self) -> int:
        return len(self._skills)
