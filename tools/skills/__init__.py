# tools/skills/__init__.py

"""
Skills 能力包 — 通过 Markdown 文件扩展 Agent 能力。

参考 langgraph-agent-starter 的 Skills 设计：
- SKILL.md 格式：YAML frontmatter + Markdown body
- 按相关性选择：根据用户输入/模块类型匹配 triggers
- Prompt 注入：将技能内容注入 system prompt

用法:
    from tools.skills import SkillSelector, SkillLoader

    loader = SkillLoader("tools/skills/builtin")
    mgr = SkillSelector(loader)
    skills = mgr.select_for("review the authentication module")
    enhanced_prompt = mgr.inject(skills, system_prompt)
"""

from tools.skills.loader import Skill, SkillLoader
from tools.skills.manager import SkillSelector
from tools.skills.registry import SkillMetadata, SkillRegistry

__all__ = ["Skill", "SkillLoader", "SkillSelector", "SkillMetadata", "SkillRegistry"]
