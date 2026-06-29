"""Tests for SkillRegistry."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tools.skills import SkillRegistry, SkillMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_dir(tmp_path: Path, name: str, description: str = "Test skill",
                     triggers: list[str] | None = None) -> Path:
    """Create a temporary skill directory with a SKILL.md file."""
    skill_dir = tmp_path / name
    skill_dir.mkdir()

    triggers_str = ", ".join(triggers or ["test", "example"])
    content = f"""---
name: {name}
description: {description}
triggers: [{triggers_str}]
version: 1.0.0
author: test-author
---

# {name}

This is a test skill.
"""
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


# ---------------------------------------------------------------------------
# SkillMetadata
# ---------------------------------------------------------------------------

class TestSkillMetadata:
    def test_defaults(self):
        m = SkillMetadata(name="test", description="A test skill")
        assert m.name == "test"
        assert m.version == "1.0.0"
        assert m.author == "unknown"
        assert m.triggers == []

    def test_all_fields(self):
        m = SkillMetadata(
            name="my-skill",
            description="Does things",
            triggers=["do", "thing"],
            version="2.0.0",
            author="alice",
            tags=["utility"],
        )
        assert m.triggers == ["do", "thing"]
        assert m.version == "2.0.0"
        assert m.author == "alice"
        assert m.tags == ["utility"]


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------

class TestSkillRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        return SkillRegistry(
            skills_dir=str(tmp_path / "skills"),
            registry_path=str(tmp_path / "registry.json"),
        )

    def test_init_empty(self, registry):
        assert registry.size == 0

    def test_discover_from_builtin(self):
        """Test discovering skills from the actual builtin directory."""
        registry = SkillRegistry()
        entries = registry.discover()
        assert len(entries) >= 3  # We have at least 3 builtin skills
        names = {e.name for e in entries}
        assert "code-review" in names or "api-design" in names

    def test_discover_empty_dir(self, registry, tmp_path):
        entries = registry.discover()
        assert entries == []

    def test_discover_with_skills(self, registry, tmp_path):
        # Create skill directly in the registry's skills dir
        skill_dir = Path(registry.skills_dir) / "my-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\ntriggers: [test]\n---\n\n# Content\n",
            encoding="utf-8",
        )
        entries = registry.discover()
        assert len(entries) == 1
        assert entries[0].name == "my-skill"

    def test_publish(self, registry, tmp_path):
        skill_dir = _make_skill_dir(tmp_path, "new-skill", "A new skill")
        meta = registry.publish(str(skill_dir))
        assert meta.name == "new-skill"
        assert meta.description == "A new skill"
        assert registry.size == 1

    def test_publish_overwrite(self, registry, tmp_path):
        skill_dir1 = _make_skill_dir(tmp_path, "overwrite-skill", "Version 1")
        registry.publish(str(skill_dir1))

        # Create another source dir with the same skill name (different content)
        skill_dir2 = tmp_path / "overwrite-skill-v2"
        skill_dir2.mkdir()
        (skill_dir2 / "SKILL.md").write_text(
            "---\nname: overwrite-skill\ndescription: Version 2\ntriggers: [new]\n---\n\n# V2\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="already exists"):
            registry.publish(str(skill_dir2))

        # Now overwrite
        meta = registry.publish(str(skill_dir2), overwrite=True)
        assert meta.description == "Version 2"

    def test_publish_no_skill_md(self, registry, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="No SKILL.md"):
            registry.publish(str(empty_dir))

    def test_unpublish(self, registry, tmp_path):
        skill_dir = _make_skill_dir(tmp_path, "to-remove", "Will be removed")
        registry.publish(str(skill_dir))
        assert registry.size == 1

        result = registry.unpublish("to-remove")
        assert result is True
        assert registry.size == 0

    def test_unpublish_nonexistent(self, registry):
        result = registry.unpublish("nonexistent")
        assert result is False

    def test_get(self, registry, tmp_path):
        skill_dir = _make_skill_dir(tmp_path, "find-me", "Findable skill")
        registry.publish(str(skill_dir))

        meta = registry.get("find-me")
        assert meta is not None
        assert meta.name == "find-me"
        assert meta.description == "Findable skill"

    def test_get_missing(self, registry):
        assert registry.get("nonexistent") is None

    def test_list_skills(self, registry, tmp_path):
        for name in ["alpha", "beta", "gamma"]:
            skill_dir = _make_skill_dir(tmp_path, name, f"Skill {name}")
            registry.publish(str(skill_dir))

        skills = registry.list_skills()
        assert len(skills) == 3
        names = {s.name for s in skills}
        assert names == {"alpha", "beta", "gamma"}

    def test_search_by_name(self, registry, tmp_path):
        # Create skills directly in the registry skills dir
        for name, desc in [("data-validation", "Validate data formats"),
                           ("api-design", "Design REST APIs")]:
            skill_dir = Path(registry.skills_dir) / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {desc}\ntriggers: [{name.split('-')[0]}]\n---\n\n# {name}\n",
                encoding="utf-8",
            )

        registry.discover()
        results = registry.search("data")
        assert len(results) >= 1
        assert any("data" in r.name.lower() for r in results)

    def test_search_by_trigger(self, registry, tmp_path):
        skill_dir = _make_skill_dir(tmp_path, "auth-helper", "Help with authentication",
                                     triggers=["auth", "jwt", "security"])
        registry.publish(str(skill_dir))

        results = registry.search("jwt")
        assert len(results) >= 1

    def test_persistence(self, tmp_path):
        reg_path = str(tmp_path / "persist_registry.json")
        skills_dir = str(tmp_path / "persist_skills")

        # Create and publish
        r1 = SkillRegistry(skills_dir=skills_dir, registry_path=reg_path)
        skill_dir = _make_skill_dir(tmp_path, "persist-skill")
        # Copy to skills dir
        dest = Path(skills_dir) / "persist-skill"
        if not dest.exists():
            import shutil
            shutil.copytree(skill_dir, dest)
        r1.discover()

        # Create new registry from same file
        r2 = SkillRegistry(skills_dir=skills_dir, registry_path=reg_path)
        assert r2.size == r1.size

    def test_corrupted_registry(self, tmp_path):
        reg_path = tmp_path / "corrupt.json"
        reg_path.write_text("{invalid", encoding="utf-8")
        registry = SkillRegistry(
            skills_dir=str(tmp_path / "skills"),
            registry_path=str(reg_path),
        )
        assert registry.size == 0

    def test_len(self, registry, tmp_path):
        assert len(registry) == 0
        skill_dir = _make_skill_dir(tmp_path, "len-test")
        registry.publish(str(skill_dir))
        assert len(registry) == 1

    def test_repr(self, registry):
        r = repr(registry)
        assert "SkillRegistry" in r


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestSkillRegistryIntegration:
    def test_full_lifecycle(self, tmp_path):
        """Create → publish → discover → search → unpublish."""
        registry = SkillRegistry(
            skills_dir=str(tmp_path / "skills"),
            registry_path=str(tmp_path / "reg.json"),
        )

        # Create skill
        skill_dir = _make_skill_dir(tmp_path, "lifecycle", "Lifecycle test",
                                     triggers=["lifecycle", "test"])

        # Publish
        meta = registry.publish(str(skill_dir))
        assert meta.name == "lifecycle"
        assert registry.size == 1

        # Discover
        entries = registry.discover()
        assert any(e.name == "lifecycle" for e in entries)

        # Search
        results = registry.search("lifecycle")
        assert len(results) == 1

        # Unpublish
        assert registry.unpublish("lifecycle") is True
        assert registry.size == 0

    def test_publish_copies_files(self, tmp_path):
        """Publishing should copy skill files to the skills directory."""
        registry = SkillRegistry(
            skills_dir=str(tmp_path / "skills"),
            registry_path=str(tmp_path / "reg.json"),
        )

        skill_dir = _make_skill_dir(tmp_path, "file-skill")
        registry.publish(str(skill_dir))

        dest = Path(registry.skills_dir) / "file-skill" / "SKILL.md"
        assert dest.exists()
        content = dest.read_text(encoding="utf-8")
        assert "file-skill" in content
