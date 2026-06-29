# tools/skills/manager.py

"""
Skill 选择器 — 按相关性选择技能并注入 prompt。

参考 langgraph-agent-starter 的 Skills 设计：
- 根据用户输入文本匹配 triggers
- 按相关性排序，选择 top-N skills
- 注入 system prompt 和 context

用法:
    mgr = SkillSelector(SkillLoader("tools/skills/builtin"))
    skills = mgr.select_for("review authentication module", "code_review")
    enhanced = mgr.inject(skills, system_prompt)
"""

from __future__ import annotations

import logging
from typing import List

from tools.skills.loader import Skill, SkillLoader

logger = logging.getLogger(__name__)


class SkillSelector:
    """
    Skill 选择器 + 注入器。

    根据输入文本和模块类型选择最相关的技能，
    将技能内容注入 system prompt。
    """

    def __init__(self, loader: SkillLoader, max_skills: int = 3):
        self.loader = loader
        self.max_skills = max_skills
        self._skills: List[Skill] = []
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self._skills = self.loader.load_all()
            self._loaded = True

    def select_for(self, input_text: str, module_type: str = "") -> List[Skill]:
        """
        根据输入文本选择最相关的技能。

        匹配策略:
        1. 精确匹配 triggers 关键词
        2. 模糊匹配 description 中的关键词
        3. 模块类型匹配 (triggers 中包含模块名)

        Args:
            input_text: 用户输入文本
            module_type: 模块类型（如 "code_review", "api_design"）

        Returns:
            匹配的技能列表（按相关性排序，最多 max_skills 个）
        """
        self._ensure_loaded()
        input_lower = input_text.lower()
        scored: list[tuple[float, Skill]] = []

        for skill in self._skills:
            score = self._score_skill(skill, input_lower, module_type)
            if score > 0:
                scored.append((score, skill))

        # 按分数降序排列
        scored.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored[:self.max_skills]]

    def _score_skill(self, skill: Skill, input_lower: str, module_type: str) -> float:
        """计算技能与输入的相关性分数"""
        score = 0.0

        # 1. Triggers 精确匹配（最高权重）
        for trigger in skill.triggers:
            if trigger.lower() in input_lower:
                score += 10.0

        # 2. 模块类型匹配
        if module_type and module_type.lower() in [t.lower() for t in skill.triggers]:
            score += 5.0

        # 3. Description 关键词匹配
        if skill.description:
            desc_words = skill.description.lower().split()
            for word in desc_words:
                if len(word) > 3 and word in input_lower:
                    score += 2.0

        # 4. Name 匹配
        if skill.name.lower().replace("-", " ") in input_lower:
            score += 3.0

        return score

    def inject(self, skills: List[Skill], system_prompt: str) -> str:
        """
        将技能内容注入 system prompt。

        注入位置: system prompt 末尾，作为附加指令。

        Args:
            skills: 要注入的技能列表
            system_prompt: 原始 system prompt

        Returns:
            增强后的 system prompt
        """
        if not skills:
            return system_prompt

        skill_blocks = []
        for skill in skills:
            block = f"## Skill: {skill.name}\n"
            if skill.description:
                block += f"_{skill.description}_\n\n"
            block += skill.system_snippet
            skill_blocks.append(block)

        injection = "\n\n---\n\n" + "\n\n".join(skill_blocks)
        return system_prompt + injection

    def list_skills(self) -> List[dict]:
        """列出所有可用技能（供 API 使用）"""
        self._ensure_loaded()
        return [
            {
                "name": s.name,
                "description": s.description,
                "triggers": s.triggers,
            }
            for s in self._skills
        ]

    def reload(self):
        """重新加载所有技能"""
        self._skills = self.loader.load_all()
        self._loaded = True
