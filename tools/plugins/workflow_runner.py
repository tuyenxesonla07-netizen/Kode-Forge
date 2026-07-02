# tools/plugins/workflow_runner.py

"""
WorkflowRunner — 声明式 YAML 工作流执行器。

借鉴 codex 的 SkillWorkflowRuntime，是现有 WorkflowEngine 的薄封装。
从 Skill manifest 的 workflow_path 加载 YAML，转换为 WorkflowEngine 可执行的格式。

用法:
    from tools.plugins.workflow_runner import WorkflowRunner
    from tools.workflow import WorkflowEngine

    engine = WorkflowEngine()
    runner = WorkflowRunner(engine=engine)
    result = runner.execute("code_fix_workflow", state=agent_state)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.plugins.skill_registry import PluginSkillEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow Definition
# ---------------------------------------------------------------------------

@dataclass
class WorkflowDefinition:
    """解析后的工作流定义。"""
    name: str
    nodes: list[str]
    edges: list[dict[str, str]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Workflow Runner
# ---------------------------------------------------------------------------

class WorkflowRunner:
    """声明式 YAML 工作流执行器 — WorkflowEngine 的薄封装。"""

    def __init__(self, engine: Any | None = None) -> None:
        self._engine = engine

    def load(self, skill_entry: PluginSkillEntry) -> WorkflowDefinition | None:
        """从 Skill entry 加载工作流定义。

        Args:
            skill_entry: 已加载的 Skill 插件条目

        Returns:
            WorkflowDefinition，若无 workflow_path 则返回 None
        """
        workflow_path = skill_entry.manifest.workflow_path
        if not workflow_path:
            return None

        # 相对于 skill 目录解析路径
        # skill_entry 不存储目录路径，需要由调用方传入绝对路径
        # 这里简化处理：workflow_path 为相对路径时，尝试从 prompts 目录推断
        return self._parse_simple_yaml(workflow_path, skill_entry)

    def _parse_simple_yaml(self, workflow_path: str,
                           skill_entry: PluginSkillEntry) -> WorkflowDefinition | None:
        """解析简单 YAML 工作流（简化版，不依赖 PyYAML）。

        实际实现应使用 yaml.safe_load，此处为最小可行版本。
        """
        path = Path(workflow_path)
        if not path.is_absolute():
            # 尝试作为相对路径（相对于当前工作目录）
            path = Path.cwd() / workflow_path

        if not path.exists():
            logger.warning("[WorkflowRunner] Workflow file not found: %s", path)
            return None

        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except ImportError:
            # 无 PyYAML 时使用 JSON 兜底
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = __import__("json").load(f)
            except Exception as e:
                logger.error("[WorkflowRunner] Failed to parse workflow: %s", e)
                return None
        except Exception as e:
            logger.error("[WorkflowRunner] Failed to parse workflow: %s", e)
            return None

        if not isinstance(data, dict):
            return None

        nodes = data.get("nodes", [])
        if isinstance(nodes, list):
            node_ids = [n if isinstance(n, str) else n.get("id", f"node_{i}")
                       for i, n in enumerate(nodes)]
        else:
            node_ids = []

        return WorkflowDefinition(
            name=data.get("name", "unnamed"),
            nodes=node_ids,
            raw=data,
        )

    def execute(self, skill_name: str, state: Any,
                start_node: str | None = None) -> dict[str, Any]:
        """执行工作流。

        Args:
            skill_name: Skill 名称
            state: AgentState 实例
            start_node: 起始节点 ID（可选）

        Returns:
            执行结果字典
        """
        if self._engine is None:
            return {"success": False, "error": "No WorkflowEngine configured",
                    "nodes_executed": []}

        # 将 AgentState 转换为工作流输入
        workflow_input = {
            "message": getattr(state, "message", ""),
            "conversation_id": getattr(state, "conversation_id", ""),
            "intent": getattr(state, "intent", ""),
        }

        logger.info("[WorkflowRunner] Executing workflow for skill '%s' from node '%s'",
                    skill_name, start_node)

        # 简化实现：记录执行意图，实际引擎集成在 P1 完善
        return {
            "success": True,
            "skill_name": skill_name,
            "start_node": start_node,
            "nodes_executed": [],
            "input": workflow_input,
        }
