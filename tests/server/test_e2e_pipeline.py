"""E2E test for schema-first pipeline demo."""

import pytest
import os
import sys
import tempfile
import json
import asyncio


class TestSchemaLoading:
    """Test schema loading from config/schemas/."""

    def test_schemas_directory_exists(self):
        """Config schemas directory should exist."""
        schema_dir = os.path.join("config", "schemas")
        assert os.path.isdir(schema_dir), f"Schema directory not found: {schema_dir}"

    def test_at_least_one_input_schema(self):
        """Should have at least one input schema."""
        import glob
        schemas = glob.glob(os.path.join("config", "schemas", "*_input.json"))
        assert len(schemas) >= 1, "No input schemas found"

    def test_schemas_are_valid_json(self):
        """All schema files should be valid JSON."""
        import glob
        for schema_file in glob.glob(os.path.join("config", "schemas", "*.json")):
            with open(schema_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, dict), f"Schema {schema_file} is not a dict"

    def test_input_output_pairs(self):
        """Each input schema should have a corresponding output schema."""
        import glob
        input_schemas = glob.glob(os.path.join("config", "schemas", "*_input.json"))
        for input_file in input_schemas:
            module_name = os.path.basename(input_file).replace("_input.json", "")
            output_file = os.path.join("config", "schemas", f"{module_name}_output.json")
            assert os.path.exists(output_file), f"Missing output schema for {module_name}"


class TestPipelineCompilation:
    """Test pipeline compilation."""

    def test_compiler_import(self):
        """PipelineCompiler should be importable."""
        from tools.compiler import PipelineCompiler
        assert PipelineCompiler is not None

    def test_compile_from_config(self):
        """Should compile schemas from config directory."""
        from tools.compiler import PipelineCompiler
        compiler = PipelineCompiler()
        compiled = compiler.compile_from_config(config_dir="config")
        assert compiled is not None
        assert compiled.implementation_order is not None
        assert len(compiled.implementation_order) >= 1

    def test_compiled_has_quality_gates(self):
        """Compiled pipeline should have quality gates."""
        from tools.compiler import PipelineCompiler
        compiler = PipelineCompiler()
        compiled = compiler.compile_from_config(config_dir="config")
        assert compiled.quality_gates is not None
        assert len(compiled.quality_gates.gates) >= 0


class TestWorkflowExecution:
    """Test workflow execution with mock LLM."""

    @pytest.mark.asyncio
    async def test_engine_creation(self):
        """WorkflowEngine should be created without errors."""
        from tools.workflow.engine import WorkflowEngine
        engine = WorkflowEngine()
        assert engine is not None

    @pytest.mark.asyncio
    async def test_load_and_execute_workflow(self):
        """Should load and execute a simple workflow."""
        from tools.workflow.engine import WorkflowEngine
        from tools.llm.mock import MockLLMProvider

        engine = WorkflowEngine()
        provider = MockLLMProvider()

        # Create a simple single-node workflow
        workflow_def = {
            "id": "test_workflow",
            "name": "Test Workflow",
            "nodes": [
                {
                    "id": "node_1",
                    "type": "llm",
                    "name": "Generate Code",
                    "config": {
                        "prompt_template": "Generate code for authentication",
                        "temperature": 0.3,
                    },
                    "inputs": [],
                }
            ],
            "edges": [],
            "metadata": {},
        }

        engine.load_workflow(workflow_def)
        run_id = await engine.execute_async(
            "test_workflow",
            {"input": "test requirement"},
            context={"llm_provider": provider},
        )

        assert run_id is not None

        # Wait for completion
        import time
        for _ in range(100):  # Max 10 seconds
            result = engine.get_run_result(run_id)
            if result and result.status != "running":
                break
            await asyncio.sleep(0.1)

        final = engine.get_run_result(run_id)
        assert final is not None
        assert final.status == "success"
        assert "node_1" in final.outputs

    @pytest.mark.asyncio
    async def test_multi_node_workflow(self):
        """Should execute multi-node workflow with dependencies."""
        from tools.workflow.engine import WorkflowEngine
        from tools.llm.mock import MockLLMProvider

        engine = WorkflowEngine()
        provider = MockLLMProvider()

        workflow_def = {
            "id": "multi_node_workflow",
            "name": "Multi-Node Workflow",
            "nodes": [
                {
                    "id": "node_a",
                    "type": "llm",
                    "name": "Generate Module A",
                    "config": {"prompt_template": "Generate module A", "temperature": 0.2},
                    "inputs": [],
                },
                {
                    "id": "node_b",
                    "type": "llm",
                    "name": "Generate Module B",
                    "config": {"prompt_template": "Generate module B", "temperature": 0.2},
                    "inputs": ["node_a"],
                },
            ],
            "edges": [
                {"from": "node_a", "to": "node_b"},
            ],
            "metadata": {},
        }

        engine.load_workflow(workflow_def)
        run_id = await engine.execute_async(
            "multi_node_workflow",
            {"input": "test multi-node requirement"},
            context={"llm_provider": provider},
        )

        # Wait for completion
        for _ in range(100):
            result = engine.get_run_result(run_id)
            if result and result.status != "running":
                break
            await asyncio.sleep(0.1)

        final = engine.get_run_result(run_id)
        assert final is not None
        assert final.status == "success"
        assert "node_a" in final.outputs
        assert "node_b" in final.outputs


class TestSessionManager:
    """Test session persistence."""

    def test_session_manager_creation(self, tmp_path):
        """SessionManager should be created with custom dir."""
        from tools.server.pipeline_orchestrator import SessionManager
        session_dir = str(tmp_path / "sessions")
        manager = SessionManager(session_dir=session_dir)
        assert os.path.isdir(session_dir)

    def test_save_and_load(self, tmp_path):
        """Should save and load run results."""
        from tools.server.pipeline_orchestrator import SessionManager
        manager = SessionManager(session_dir=str(tmp_path / "sessions"))

        result = {"status": "success", "outputs": {"module_a": "code"}}
        manager.save_run("test_run", result)

        loaded = manager.get_run("test_run")
        assert loaded is not None
        assert loaded["status"] == "success"

    def test_list_runs(self, tmp_path):
        """Should list saved runs."""
        from tools.server.pipeline_orchestrator import SessionManager
        manager = SessionManager(session_dir=str(tmp_path / "sessions"))

        for i in range(3):
            manager.save_run(f"run_{i}", {"status": "success"})

        runs = manager.list_runs()
        assert len(runs) == 3


class TestOrchestratorIntegration:
    """Test full orchestrator integration."""

    @pytest.mark.asyncio
    async def test_orchestrator_with_session(self, tmp_path):
        """Orchestrator should auto-save results when session_dir is set."""
        from tools.server.pipeline_orchestrator import PipelineOrchestrator
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        session_dir = str(tmp_path / "sessions")
        orchestrator = PipelineOrchestrator(
            llm_provider=provider,
            session_dir=session_dir,
        )

        result = await orchestrator.run_pipeline("构建用户登录模块")
        assert result is not None
        assert "status" in result

        # Check that session was saved
        runs = orchestrator.list_runs()
        assert len(runs) >= 1

    @pytest.mark.asyncio
    async def test_orchestrator_without_session(self):
        """Orchestrator should work without session manager."""
        from tools.server.pipeline_orchestrator import PipelineOrchestrator
        from tools.llm.mock import MockLLMProvider

        provider = MockLLMProvider()
        orchestrator = PipelineOrchestrator(llm_provider=provider)

        result = await orchestrator.run_pipeline("构建用户登录模块")
        assert result is not None
        assert "status" in result
        assert orchestrator.session_manager is None
