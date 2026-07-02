# tests/plugins/test_workflow_runner.py

"""
tests/plugins/test_workflow_runner.py — WorkflowRunner 单元测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.plugins.workflow_runner import WorkflowRunner, WorkflowDefinition
from tools.plugins.skill_registry import PluginSkillEntry
from tools.plugins.manifest import SkillManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_entry(name: str, workflow_path: str = "") -> PluginSkillEntry:
    """创建测试用 PluginSkillEntry。"""
    manifest = SkillManifest(
        name=name,
        display_name=f"Skill {name}",
        description=f"Description for {name}",
        version="1.0.0",
        intents=("code_generation",),
        tools=("compile",),
        entry_agent=f"expert_{name}",
        risk_level="low",
        prompt_paths={},
        workflow_path=workflow_path,
    )
    return PluginSkillEntry(manifest=manifest, prompts={})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWorkflowRunner:
    def test_init_no_engine(self):
        """无 engine 时初始化正常。"""
        runner = WorkflowRunner(engine=None)
        assert runner._engine is None

    def test_load_workflow_no_path(self):
        """Skill 无 workflow_path 时 load 返回 None。"""
        runner = WorkflowRunner(engine=None)
        entry = _make_skill_entry("no_workflow", workflow_path="")
        result = runner.load(entry)
        assert result is None

    def test_load_workflow_from_skill(self, tmp_path: Path):
        """从 Skill entry 加载 YAML 工作流。"""
        # 创建简单 YAML 工作流文件
        workflow_data = {
            "name": "test_workflow",
            "nodes": ["step1", "step2", "step3"],
        }
        workflow_file = tmp_path / "workflow.yaml"
        workflow_file.write_text(json.dumps(workflow_data), encoding="utf-8")

        runner = WorkflowRunner(engine=None)
        entry = _make_skill_entry("with_workflow", workflow_path=str(workflow_file))
        result = runner.load(entry)

        assert result is not None
        assert isinstance(result, WorkflowDefinition)
        assert result.name == "test_workflow"
        assert result.nodes == ["step1", "step2", "step3"]

    def test_load_workflow_missing_file(self):
        """工作流文件不存在时返回 None。"""
        runner = WorkflowRunner(engine=None)
        entry = _make_skill_entry(
            "missing_file",
            workflow_path="/nonexistent/path/workflow.yaml",
        )
        result = runner.load(entry)
        assert result is None

    def test_execute_no_engine(self):
        """无 engine 时 execute 返回错误信息。"""
        runner = WorkflowRunner(engine=None)

        # 创建 mock state
        class MockState:
            message = "test"
            conversation_id = "conv-1"
            intent = "code_generation"

        result = runner.execute("test_skill", state=MockState())
        assert result["success"] is False
        assert "No WorkflowEngine" in result["error"]

    def test_execute_with_engine(self):
        """有 engine 时 execute 返回执行结果。"""
        mock_engine = object()
        runner = WorkflowRunner(engine=mock_engine)

        class MockState:
            message = "build auth module"
            conversation_id = "conv-1"
            intent = "code_generation"

        result = runner.execute("test_skill", state=MockState())
        assert result["success"] is True
        assert result["skill_name"] == "test_skill"
        assert result["input"]["message"] == "build auth module"

    def test_execute_with_start_node(self):
        """指定 start_node 时传递给 execute。"""
        runner = WorkflowRunner(engine=object())

        class MockState:
            message = "test"
            conversation_id = "c1"
            intent = "code_fix"

        result = runner.execute("skill_x", state=MockState(), start_node="step2")
        assert result["start_node"] == "step2"

    def test_workflow_definition_dataclass(self):
        """WorkflowDefinition dataclass 字段正确。"""
        wf = WorkflowDefinition(name="test", nodes=["a", "b", "c"])
        assert wf.name == "test"
        assert wf.nodes == ["a", "b", "c"]
        assert wf.edges == []
        assert wf.raw == {}
