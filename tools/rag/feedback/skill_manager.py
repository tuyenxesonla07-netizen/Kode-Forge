"""Skill 自学习管理器 — 从成功轨迹中提炼可复用技能。

灵感来源: NousResearch/hermes-agent 的 Skill 自学习循环。
概念: Agent 执行复杂任务成功后，自动提炼为 SKILL.md 文件，
      下次遇到类似任务直接加载，而非从头推理。

Usage:
    manager = SkillLearner(skills_dir=".skills")

    # 从成功执行中提炼 Skill
    skill = manager.extract_skill(
        task="实现用户认证模块",
        trajectory=[{"action": "write_file", "result": "success"}, ...],
    )

    # 匹配已有 Skill
    matched = manager.match_skill("实现订单管理模块")
    if matched:
        print(matched.content)  # 加载 Skill 内容

    # 根据反馈改进 Skill
    manager.improve_skill(skill, feedback={"rating": 0.9, "note": "缺少错误处理"})
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill data structure
# ---------------------------------------------------------------------------

@dataclass
class LearnedSkill:
    """A reusable skill extracted from a successful task execution."""

    name: str
    content: str                     # SKILL.md content
    task_type: str                   # category label
    keywords: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    usage_count: int = 0
    success_count: int = 0
    avg_rating: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "task_type": self.task_type,
            "keywords": self.keywords,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "avg_rating": self.avg_rating,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnedSkill:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def __repr__(self) -> str:
        return (
            f"LearnedSkill(name={self.name!r}, type={self.task_type!r}, "
            f"uses={self.usage_count}, rate={self.success_rate:.1%})"
        )


# ---------------------------------------------------------------------------
# Skill Learner
# ---------------------------------------------------------------------------

class SkillLearner:
    """Manages the skill lifecycle: extract → store → match → improve.

    Skills are persisted as JSON files in a directory, one file per skill.
    An index.json provides fast lookup without scanning all files.
    """

    def __init__(self, skills_dir: str = ".skills") -> None:
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.skills_dir / "index.json"
        self._skills: dict[str, LearnedSkill] = {}
        self._load_index()

    # ---- public API --------------------------------------------------------

    def extract_skill(
        self,
        task: str,
        trajectory: list[dict[str, Any]],
        task_type: str = "general",
    ) -> LearnedSkill | None:
        """Extract a skill from a successful task execution trajectory."""
        if not trajectory or not task:
            return None

        # Only extract from successful trajectories
        if not all(step.get("result") in ("success", "ok", True) for step in trajectory):
            return None

        # Generate skill content from trajectory patterns
        content = self._generate_skill_content(task, trajectory, task_type)
        keywords = self._extract_keywords(task, trajectory)
        name = self._generate_skill_name(task, task_type)

        skill = LearnedSkill(
            name=name,
            content=content,
            task_type=task_type,
            keywords=keywords,
            metadata={
                "source_task": task,
                "trajectory_length": len(trajectory),
                "actions_used": list(set(
                    step.get("action", "unknown") for step in trajectory
                )),
            },
        )

        self._save_skill(skill)
        logger.info("Extracted skill: %s (type=%s, keywords=%s)", name, task_type, keywords)
        return skill

    def match_skill(
        self,
        task: str,
        task_type: str | None = None,
        min_score: float = 0.15,
    ) -> LearnedSkill | None:
        """Find the best matching skill using multi-signal scoring."""
        task_tokens = set(self._tokenize(task))
        task_bigram_set = _bigrams(task)

        best_skill: LearnedSkill | None = None
        best_score = 0.0

        for skill in self._skills.values():
            if task_type and skill.task_type != task_type:
                continue

            # Build skill token set from keywords + source task
            skill_tokens = set(skill.keywords)
            source = skill.metadata.get("source_task", "")
            if source:
                skill_tokens.update(self._tokenize(source))

            if not task_tokens or not skill_tokens:
                continue

            # 1) Jaccard coefficient
            union = task_tokens | skill_tokens
            jaccard = len(task_tokens & skill_tokens) / max(1, len(union))

            # 2) Character bigram similarity
            skill_text = " ".join(skill.keywords) + " " + source
            skill_bigram_set = _bigrams(skill_text)
            all_bigrams = task_bigram_set | skill_bigram_set
            bigram_sim = 0.0
            if all_bigrams:
                bigram_sim = len(task_bigram_set & skill_bigram_set) / len(all_bigrams)

            # 3) Type match
            type_match = 1.0 if task_type and skill.task_type == task_type else 0.3

            # 4) Quality bonus
            quality_bonus = 0.7 + 0.3 * skill.success_rate

            score = (jaccard * 0.5 + bigram_sim * 0.3 + type_match * 0.2) * quality_bonus

            if score > best_score:
                best_score = score
                best_skill = skill

        if best_skill and best_score >= min_score:
            best_skill.usage_count += 1
            self._save_skill(best_skill)
            return best_skill

        return None

    def improve_skill(
        self,
        skill: LearnedSkill,
        feedback: dict[str, Any],
    ) -> LearnedSkill:
        """Improve a skill based on usage feedback."""
        # Update rating
        rating = feedback.get("rating")
        if rating is not None:
            # Running average
            total = skill.avg_rating * skill.usage_count + rating
            skill.avg_rating = total / max(1, skill.usage_count + 1)

        # Track success/failure
        if feedback.get("success", False):
            skill.success_count += 1

        # Append improvement note
        note = feedback.get("note")
        if note:
            timestamp = datetime.now().isoformat(timespec="seconds")
            improvement_entry = f"\n\n## Improvement Note ({timestamp})\n{note}"
            skill.content += improvement_entry

        # Append missing actions
        missing = feedback.get("missing_actions", [])
        if missing:
            actions_str = "\n".join(f"- {a}" for a in missing)
            skill.content += f"\n\n## Missing Actions to Add\n{actions_str}"

        skill.updated_at = datetime.now().isoformat(timespec="seconds")
        self._save_skill(skill)
        logger.info("Improved skill: %s (rating=%.2f)", skill.name, skill.avg_rating)
        return skill

    def record_usage(self, skill: LearnedSkill, success: bool) -> None:
        """Record a usage outcome for a skill."""
        skill.usage_count += 1
        if success:
            skill.success_count += 1
        self._save_skill(skill)

    def list_skills(self, task_type: str | None = None) -> list[LearnedSkill]:
        """List all skills, optionally filtered by type."""
        skills = list(self._skills.values())
        if task_type:
            skills = [s for s in skills if s.task_type == task_type]
        return sorted(skills, key=lambda s: s.success_rate, reverse=True)

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the skill library."""
        skills = list(self._skills.values())
        if not skills:
            return {"total": 0, "types": {}, "avg_rating": 0.0, "avg_usage": 0.0}

        types: dict[str, int] = {}
        for s in skills:
            types[s.task_type] = types.get(s.task_type, 0) + 1

        return {
            "total": len(skills),
            "types": types,
            "avg_rating": sum(s.avg_rating for s in skills) / len(skills),
            "avg_usage": sum(s.usage_count for s in skills) / len(skills),
            "avg_success_rate": sum(s.success_rate for s in skills) / len(skills),
        }

    # ---- persistence -------------------------------------------------------

    def _load_index(self) -> None:
        """Load all skills from the skills directory."""
        if not self._index_path.exists():
            return

        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                index = json.load(f)

            for name in index.get("skills", []):
                skill_path = self.skills_dir / f"{name}.json"
                if skill_path.exists():
                    with open(skill_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._skills[name] = LearnedSkill.from_dict(data)

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load skill index: %s", e)

    def _save_skill(self, skill: LearnedSkill) -> None:
        """Save a skill to disk and update the index."""
        self._skills[skill.name] = skill

        # Write individual skill file
        skill_path = self.skills_dir / f"{skill.name}.json"
        with open(skill_path, "w", encoding="utf-8") as f:
            json.dump(skill.to_dict(), f, ensure_ascii=False, indent=2)

        # Update index
        index = {
            "skills": list(self._skills.keys()),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    # ---- content generation -----------------------------------------------

    def _generate_skill_content(
        self,
        task: str,
        trajectory: list[dict[str, Any]],
        task_type: str,
    ) -> str:
        """Generate SKILL.md content from a trajectory."""
        lines: list[str] = []
        lines.append(f"# Skill: {self._generate_skill_name(task, task_type)}")
        lines.append("")
        lines.append(f"## Task Type: {task_type}")
        lines.append("")
        lines.append("## Description")
        lines.append(f"This skill was extracted from the successful execution of: {task}")
        lines.append("")
        lines.append("## Steps")

        for i, step in enumerate(trajectory, 1):
            action = step.get("action", "unknown")
            detail = step.get("detail", "")
            lines.append(f"{i}. {action}" + (f" — {detail}" if detail else ""))

        lines.append("")
        lines.append("## Key Patterns")
        actions = [step.get("action", "") for step in trajectory]
        unique_actions = list(dict.fromkeys(actions))  # preserve order, deduplicate
        for action in unique_actions:
            if action:
                lines.append(f"- {action}")

        lines.append("")
        lines.append("## Usage")
        lines.append("Apply this skill when encountering similar tasks. Adapt the steps to the specific context.")
        lines.append("")

        return "\n".join(lines)

    def _generate_skill_name(self, task: str, task_type: str) -> str:
        """Generate a filesystem-safe skill name from a task."""
        # Take first 5 meaningful words
        words = re.findall(r"\w+", task.lower())[:5]
        base = "_".join(words) if words else task_type
        # Add type prefix for namesafety
        name = f"{task_type}_{base}" if task_type != "general" else base
        # Sanitize
        name = re.sub(r"[^a-z0-9_]", "_", name)
        return name[:60]  # cap length

    def _extract_keywords(self, task: str, trajectory: list[dict[str, Any]]) -> list[str]:
        """Extract keywords from task description and trajectory."""
        # From task description
        tokens = set(self._tokenize(task))

        # From trajectory actions
        for step in trajectory:
            action = step.get("action", "")
            tokens.update(self._tokenize(action))
            detail = step.get("detail", "")
            if detail:
                tokens.update(self._tokenize(detail))

        # Filter: keep tokens with >1 char (Chinese) or >2 chars (English)
        return sorted(t for t in tokens if len(t) > 1)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Language-aware tokenization with jieba for Chinese + English fallback."""
        try:
            import jieba

            tokens = list(jieba.cut(text, cut_all=False))
            # Also extract English words from mixed tokens
            expanded: list[str] = []
            for tok in tokens:
                expanded.extend(w for w in tok.lower().split() if w)
            return expanded if expanded else text.lower().split()
        except ImportError:
            # Fallback: split on non-alphanumeric
            return re.findall(r"[a-z0-9]+", text.lower())

        # Update index
        index = {
            "skills": list(self._skills.keys()),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    # ---- content generation -----------------------------------------------

    def _generate_skill_content(
        self,
        task: str,
        trajectory: list[dict[str, Any]],
        task_type: str,
    ) -> str:
        """Generate SKILL.md content from a trajectory."""
        lines: list[str] = []
        lines.append(f"# Skill: {self._generate_skill_name(task, task_type)}")
        lines.append("")
        lines.append(f"## Task Type: {task_type}")
        lines.append("")
        lines.append("## Description")
        lines.append(f"This skill was extracted from the successful execution of: {task}")
        lines.append("")
        lines.append("## Steps")

        for i, step in enumerate(trajectory, 1):
            action = step.get("action", "unknown")
            detail = step.get("detail", "")
            lines.append(f"{i}. {action}" + (f" — {detail}" if detail else ""))

        lines.append("")
        lines.append("## Key Patterns")
        actions = [step.get("action", "") for step in trajectory]
        unique_actions = list(dict.fromkeys(actions))  # preserve order, deduplicate
        for action in unique_actions:
            if action:
                lines.append(f"- {action}")

        lines.append("")
        lines.append("## Usage")
        lines.append("Apply this skill when encountering similar tasks. Adapt the steps to the specific context.")
        lines.append("")

        return "\n".join(lines)

    def _generate_skill_name(self, task: str, task_type: str) -> str:
        """Generate a filesystem-safe skill name from a task."""
        # Take first 5 meaningful words
        words = re.findall(r"\w+", task.lower())[:5]
        base = "_".join(words) if words else task_type
        # Add type prefix for namesafety
        name = f"{task_type}_{base}" if task_type != "general" else base
        # Sanitize
        name = re.sub(r"[^a-z0-9_]", "_", name)
        return name[:60]  # cap length

    def _extract_keywords(self, task: str, trajectory: list[dict[str, Any]]) -> list[str]:
        """Extract keywords from task description and trajectory."""
        # From task description
        tokens = set(self._tokenize(task))

        # From trajectory actions
        for step in trajectory:
            action = step.get("action", "")
            tokens.update(self._tokenize(action))
            detail = step.get("detail", "")
            if detail:
                tokens.update(self._tokenize(detail))

        # Filter: keep tokens with >1 char (Chinese) or >2 chars (English)
        return sorted(t for t in tokens if len(t) > 1)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Language-aware tokenization with jieba for Chinese + English fallback."""
        try:
            import jieba

            tokens = list(jieba.cut(text, cut_all=False))
            # Also extract English words from mixed tokens
            expanded: list[str] = []
            for tok in tokens:
                expanded.extend(w for w in tok.lower().split() if w)
            return expanded if expanded else text.lower().split()
        except ImportError:
            # Fallback: split on non-alphanumeric
            return re.findall(r"[a-z0-9]+", text.lower())


def _bigrams(text: str) -> set[str]:
    """Character-level bigrams for fuzzy matching (works for Chinese + English)."""
    # Remove spaces and generate character bigrams
    chars = text.replace(" ", "").lower()
    if len(chars) < 2:
        return set()
    return {f"{chars[i]}_{chars[i + 1]}" for i in range(len(chars) - 1)}
