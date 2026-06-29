"""Skill Registry — publish, discover, and share skills.

Provides a registry for managing skill metadata and a CLI command for
publishing new skills to the builtin directory or a custom path.

Usage:
    registry = SkillRegistry("tools/skills/builtin")
    registry.discover()
    registry.publish("path/to/my-skill/")
    registry.unpublish("my-skill")
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class SkillMetadata:
    """Metadata for a registered skill."""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    author: str = "unknown"
    created_at: float = field(default_factory=time.time)
    source_path: str = ""
    tags: list[str] = field(default_factory=list)


class SkillRegistry:
    """Registry for managing skill metadata and files.

    The registry maintains a JSON index of all discovered skills and
    provides methods to publish new skills and discover existing ones.
    """

    def __init__(self, skills_dir: str = "tools/skills/builtin",
                 registry_path: str = ".skill_registry.json") -> None:
        self.skills_dir = Path(skills_dir)
        self.registry_path = Path(registry_path)
        self._entries: dict[str, SkillMetadata] = {}
        self._load()

    def _load(self) -> None:
        """Load the registry index from disk."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._entries = {
                    name: SkillMetadata(**meta)
                    for name, meta in data.items()
                }
            except (json.JSONDecodeError, TypeError):
                self._entries = {}

    def _save(self) -> None:
        """Persist the registry index to disk."""
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(
                {name: asdict(meta) for name, meta in self._entries.items()},
                f, ensure_ascii=False, indent=2,
            )

    def discover(self) -> List[SkillMetadata]:
        """Scan the skills directory and register all SKILL.md files.

        Returns:
            List of all discovered skill metadata.
        """
        if not self.skills_dir.exists():
            return []

        found = []
        for skill_file in sorted(self.skills_dir.rglob("SKILL.md")):
            try:
                content = skill_file.read_text(encoding="utf-8")
                meta, _ = self._parse_frontmatter(content)

                name = meta.get("name", skill_file.parent.name)
                skill_meta = SkillMetadata(
                    name=name,
                    description=meta.get("description", ""),
                    triggers=meta.get("triggers", []),
                    version=meta.get("version", "1.0.0"),
                    author=meta.get("author", "unknown"),
                    source_path=str(skill_file.parent.relative_to(self.skills_dir)),
                    tags=meta.get("tags", []),
                )
                # Preserve created_at if already registered
                if name in self._entries:
                    skill_meta.created_at = self._entries[name].created_at

                self._entries[name] = skill_meta
                found.append(skill_meta)
            except Exception:
                pass

        self._save()
        return found

    def publish(self, source_path: str, overwrite: bool = False) -> SkillMetadata:
        """Publish a skill from a source directory to the skills registry.

        The source directory must contain a SKILL.md file.

        Args:
            source_path: Path to the directory containing SKILL.md.
            overwrite: If True, overwrite an existing skill with the same name.

        Returns:
            The published SkillMetadata.

        Raises:
            FileNotFoundError: If source_path doesn't contain SKILL.md.
            ValueError: If skill already exists and overwrite is False.
        """
        source = Path(source_path).resolve()
        skill_file = source / "SKILL.md"

        if not skill_file.exists():
            raise FileNotFoundError(
                f"No SKILL.md found in {source_path}. "
                "Create a SKILL.md file with YAML frontmatter."
            )

        # Security: ensure source is not a symlink and is a real directory
        if source.is_symlink():
            raise ValueError(f"Source path must not be a symlink: {source_path}")
        if not source.is_dir():
            raise ValueError(f"Source path must be a directory: {source_path}")

        content = skill_file.read_text(encoding="utf-8")
        meta, _ = self._parse_frontmatter(content)
        name = meta.get("name", source.name)

        # Security: validate skill name to prevent path traversal
        if not name or name != Path(name).name:
            raise ValueError(
                f"Invalid skill name '{name}'. "
                "Name must be a simple directory name without path separators."
            )

        if name in self._entries and not overwrite:
            raise ValueError(
                f"Skill '{name}' already exists. Use --overwrite to replace."
            )

        # Copy to skills directory
        dest = (self.skills_dir / name).resolve()
        # Security: ensure dest is inside skills_dir
        if not str(dest).startswith(str(self.skills_dir.resolve())):
            raise ValueError(
                f"Destination {dest} escapes skills directory {self.skills_dir}"
            )
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest, symlinks=False)

        # Register
        skill_meta = SkillMetadata(
            name=name,
            description=meta.get("description", ""),
            triggers=meta.get("triggers", []),
            version=meta.get("version", "1.0.0"),
            author=meta.get("author", "unknown"),
            source_path=name,
            tags=meta.get("tags", []),
        )
        self._entries[name] = skill_meta
        self._save()
        return skill_meta

    def unpublish(self, name: str) -> bool:
        """Remove a skill from the registry and delete its files.

        Returns:
            True if the skill was found and removed, False otherwise.
        """
        if name not in self._entries:
            return False

        # Remove files
        skill_dir = self.skills_dir / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        # Remove from registry
        del self._entries[name]
        self._save()
        return True

    def get(self, name: str) -> Optional[SkillMetadata]:
        """Get metadata for a specific skill."""
        return self._entries.get(name)

    def list_skills(self) -> List[SkillMetadata]:
        """List all registered skills."""
        return list(self._entries.values())

    def search(self, query: str) -> List[SkillMetadata]:
        """Search skills by name, description, or triggers."""
        query_lower = query.lower()
        results = []
        for meta in self._entries.values():
            if (query_lower in meta.name.lower()
                    or query_lower in meta.description.lower()
                    or any(query_lower in t.lower() for t in meta.triggers)):
                results.append(meta)
        return results

    @property
    def size(self) -> int:
        return len(self._entries)

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple:
        """Parse YAML frontmatter from SKILL.md content."""
        import re

        meta = {}
        body = text

        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if match:
            frontmatter = match.group(1)
            body = text[match.end():]

            for line in frontmatter.strip().split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")

                    if value.startswith("[") and value.endswith("]"):
                        value = [v.strip().strip('"').strip("'")
                                 for v in value[1:-1].split(",") if v.strip()]

                    meta[key] = value

        return meta, body

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"SkillRegistry(skills={len(self._entries)}, dir={self.skills_dir})"
