"""Tests for SessionManager."""

import json
import pytest
import tempfile
from tools.server.pipeline_orchestrator import SessionManager


class TestSessionManager:
    @pytest.fixture
    def tmp_dir(self, tmp_path):
        return str(tmp_path / "sessions")

    @pytest.fixture
    def manager(self, tmp_dir):
        return SessionManager(session_dir=tmp_dir)

    def test_init_creates_directory(self, tmp_dir):
        import os
        assert not os.path.exists(tmp_dir)
        mgr = SessionManager(session_dir=tmp_dir)
        assert os.path.isdir(tmp_dir)

    def test_save_and_get_run(self, manager):
        result = {"status": "success", "run_id": "r1", "outputs": {}}
        manager.save_run("r1", result)

        loaded = manager.get_run("r1")
        assert loaded is not None
        assert loaded["status"] == "success"
        assert loaded["run_id"] == "r1"
        assert "saved_at" in loaded

    def test_get_run_not_found(self, manager):
        assert manager.get_run("nonexistent") is None

    def test_list_runs(self, manager):
        for i in range(5):
            manager.save_run(f"r{i}", {"status": "success", "run_id": f"r{i}"})

        runs = manager.list_runs()
        assert len(runs) == 5
        # All should have run_id
        for r in runs:
            assert "run_id" in r

    def test_list_runs_with_limit(self, manager):
        for i in range(10):
            manager.save_run(f"r{i}", {"status": "success"})

        runs = manager.list_runs(limit=3)
        assert len(runs) == 3

    def test_delete_run(self, manager):
        manager.save_run("r1", {"status": "success"})
        assert manager.get_run("r1") is not None

        deleted = manager.delete_run("r1")
        assert deleted is True
        assert manager.get_run("r1") is None

    def test_delete_nonexistent(self, manager):
        deleted = manager.delete_run("nonexistent")
        assert deleted is False

    def test_clear_all(self, manager):
        for i in range(3):
            manager.save_run(f"r{i}", {"status": "success"})

        count = manager.clear_all()
        assert count == 3
        assert manager.list_runs() == []

    def test_save_run_adds_timestamp(self, manager):
        result = {"status": "success"}
        manager.save_run("r1", result)

        loaded = manager.get_run("r1")
        assert "saved_at" in loaded

    def test_index_persistence(self, tmp_dir):
        """Index should survive manager restart."""
        manager1 = SessionManager(session_dir=tmp_dir)
        manager1.save_run("r1", {"status": "success"})

        # Create new manager instance (simulates restart)
        manager2 = SessionManager(session_dir=tmp_dir)
        runs = manager2.list_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "r1"

    def test_save_run_with_complex_result(self, manager):
        result = {
            "status": "success",
            "outputs": {
                "module_a": "class Foo:\n    pass",
                "module_b": "class Bar:\n    pass",
            },
            "logs": [
                {"node_id": "n1", "status": "success", "duration_ms": 100},
                {"node_id": "n2", "status": "success", "duration_ms": 200},
            ],
            "elapsed_seconds": 5.5,
        }
        manager.save_run("complex", result)

        loaded = manager.get_run("complex")
        assert loaded is not None
        assert len(loaded["outputs"]) == 2
        assert len(loaded["logs"]) == 2
