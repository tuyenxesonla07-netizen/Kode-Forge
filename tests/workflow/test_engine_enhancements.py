# tests/workflow/test_engine_enhancements.py
"""Tests for WorkflowEngine enhancements: checkpoint, node versioning, permissions, idempotent skip."""

import asyncio
import os

import pytest

from tools.workflow.engine import WorkflowEngine
from tools.workflow.nodes import WorkflowNode, NodeType


class TestWorkflowEngineEnhancements:
    @pytest.mark.asyncio
    async def test_checkpoint_save_load(self, tmp_path):
        engine = WorkflowEngine(checkpoint_dir=str(tmp_path))
        engine.load_workflow({
            "id": "wf-ckpt",
            "name": "Checkpoint Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step1",
                 "config": {"prompt_template": "test"}},
            ],
            "edges": [],
        })
        run_id = await engine.execute_async("wf-ckpt", {"input": "test"})
        await asyncio.sleep(0.1)

        path = engine.save_checkpoint(run_id)
        assert os.path.exists(path)

        data = engine.load_checkpoint(run_id)
        assert data is not None
        assert data["workflow_id"] == "wf-ckpt"

    @pytest.mark.asyncio
    async def test_node_version_and_permissions(self):
        node = WorkflowNode(
            id="n1", type=NodeType.TOOL, name="test",
            version="2.0.0",
            permissions=["read", "write"],
            side_effect=True,
            idempotent=True,
        )
        assert node.version == "2.0.0"
        assert node.permissions == ["read", "write"]
        assert node.side_effect is True
        assert node.idempotent is True

    @pytest.mark.asyncio
    async def test_permission_check_passes(self, tmp_path):
        engine = WorkflowEngine(checkpoint_dir=str(tmp_path))
        engine.load_workflow({
            "id": "wf-perm",
            "name": "Perm Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Safe",
                 "config": {"prompt_template": "test"}},
            ],
            "edges": [],
        })
        run_id = await engine.execute_async("wf-perm", {"input": "test"},
                                             context={"allowed_permissions": ["read", "write"]})
        await asyncio.sleep(0.1)
        result = engine.get_run_result(run_id)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_idempotent_skip(self, tmp_path):
        engine = WorkflowEngine(checkpoint_dir=str(tmp_path))
        engine.load_workflow({
            "id": "wf-idem",
            "name": "Idempotent Test",
            "nodes": [
                {"id": "n1", "type": "llm", "name": "Step",
                 "config": {"prompt_template": "test"}, "idempotent": True},
            ],
            "edges": [],
        })
        run_id = await engine.execute_async("wf-idem", {"input": "test"})
        await asyncio.sleep(0.1)
        result = engine.get_run_result(run_id)
        assert result.status == "success"
