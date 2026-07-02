# agents/experts/__init__.py
"""
专家子 Agent 包。

动态发现机制:
  1. 扫描 config/schemas/ 目录，自动发现所有模块（*_input.json / *_output.json）
  2. 从 agents.yaml 读取每个模块的能力声明（capabilities）
  3. 无需为每个模块编写独立 Python 类 — 一个通用 ExpertAgent 类即可

添加新模块:
  1. 在 config/schemas/ 添加 xxx_input.json + xxx_output.json
  2. 在 agents.yaml 添加 expert_xxx 配置（capabilities 等）
  3. 零 Python 代码改动
"""

from agents.experts.agent import (
    ExpertInput,
    ExpertOutput,
    ReviewInput,
    ReviewOutput,
    ExpertAgent,
    create_expert_agents,
)

__all__ = [
    "ExpertInput",
    "ExpertOutput",
    "ReviewInput",
    "ReviewOutput",
    "ExpertAgent",
    "create_expert_agents",
]
