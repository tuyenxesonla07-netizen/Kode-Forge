# tests/plugins/test_skill_registry.py

"""
tests/plugins/test_skill_registry.py — PluginSkillRegistry 单元测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.plugins.skill_registry import PluginSkillRegistry, PluginSkillEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_skill(dir_path: Path, manifest: dict) -> None:
    """写入 skill.json 到指定目录。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")


def _make_valid_skill(name: str, intents: list[str]) -> dict:
    return {
        "name": name,
        "display_name": f"Skill {name}",
        "description": f"Description for {name}",
        "version": "1.0.0",
        "intents": intents,
        "tools": [],
        "entry_agent": f"expert_{name}",
        "risk_level": "low",
        "prompt_paths": {},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPluginSkillRegistry:
    def test_load_skills_from_directory(self, tmp_path: Path):
        """从目录扫描加载多个 Skill。"""
        _write_skill(tmp_path / "skills" / "skill_a", _make_valid_skill("skill_a", ["intent_a"]))
        _write_skill(tmp_path / "skills" / "skill_b", _make_valid_skill("skill_b", ["intent_b"]))

        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()

        assert len(registry) == 2
        assert registry.get("skill_a") is not None
        assert registry.get("skill_b") is not None

    def test_get_by_intent_found(self, tmp_path: Path):
        """意图命中时返回正确 Skill。"""
        _write_skill(tmp_path / "skills" / "code_gen",
                     _make_valid_skill("code_gen", ["code_generation"]))

        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()

        entry = registry.get_by_intent("code_generation")
        assert entry is not None
        assert entry.manifest.name == "code_gen"

    def test_get_by_intent_not_found(self, tmp_path: Path):
        """意图未命中时返回 None。"""
        _write_skill(tmp_path / "skills" / "skill_a", _make_valid_skill("skill_a", ["intent_a"]))

        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()

        assert registry.get_by_intent("nonexistent") is None

    def test_list_skills(self, tmp_path: Path):
        """list() 返回所有已加载 Skill 的摘要信息。"""
        _write_skill(tmp_path / "skills" / "skill_a", _make_valid_skill("skill_a", ["intent_a"]))

        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()

        skills = registry.list()
        assert len(skills) == 1
        assert skills[0]["name"] == "skill_a"
        assert "version" in skills[0]
        assert "intents" in skills[0]

    def test_load_error_graceful(self, tmp_path: Path):
        """损坏的 skill.json 不崩溃，记录到 load_errors。"""
        # 写入损坏的 JSON
        broken_dir = tmp_path / "skills" / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "skill.json").write_text("{invalid", encoding="utf-8")

        _write_skill(tmp_path / "skills" / "good_skill",
                     _make_valid_skill("good_skill", ["intent_good"]))

        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()

        # 好的 skill 仍然加载成功
        assert registry.get("good_skill") is not None
        # 损坏的 skill 记录在 errors 中
        assert len(registry.load_errors) == 1

    def test_empty_directory(self, tmp_path: Path):
        """空目录不报错。"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()

        assert len(registry) == 0
        assert registry.list() == []

    def test_no_plugins_dir(self):
        """plugins_dir 为 None 时不报错。"""
        registry = PluginSkillRegistry(plugins_dir=None)
        registry.load()
        assert len(registry) == 0

    def test_missing_skills_directory(self, tmp_path: Path):
        """skills 子目录不存在时不报错。"""
        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()
        assert len(registry) == 0

    def test_load_prompts(self, tmp_path: Path):
        """Skill prompts 文件被加载。"""
        skill_dir = tmp_path / "skills" / "with_prompts"
        skill_dir.mkdir(parents=True)
        prompts_dir = skill_dir / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "system.md").write_text("You are a helpful agent.", encoding="utf-8")

        manifest = _make_valid_skill("with_prompts", ["intent_x"])
        manifest["prompt_paths"] = {"system": "prompts/system.md"}
        (skill_dir / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")

        registry = PluginSkillRegistry(plugins_dir=tmp_path)
        registry.load()

        entry = registry.get("with_prompts")
        assert entry is not None
        assert "system" in entry.prompts
        assert "helpful" in entry.prompts["system"]
