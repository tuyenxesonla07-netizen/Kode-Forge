"""Phase 3 tests: CodeNode safe_mode — reject dangerous code before exec()."""

import asyncio
import pytest
from tools.workflow.nodes import CodeNode


class TestCodeNodeSafeMode:
    """Gap 9: CodeNode in safe_mode rejects dangerous code."""

    def test_dangerous_code_blocked_in_safe_mode(self):
        node = CodeNode(code_template="import os\nos.system('ls')", safe_mode=True)
        result = asyncio.run(node.execute({}))
        assert "error" in result
        assert "safety" in result["error"].lower() or "dangerous" in result["error"].lower() or "not allowed" in result["error"].lower()

    def test_subprocess_blocked_in_safe_mode(self):
        node = CodeNode(code_template="import subprocess\nsubprocess.call(['ls'])", safe_mode=True)
        result = asyncio.run(node.execute({}))
        assert "error" in result

    def test_socket_blocked_in_safe_mode(self):
        node = CodeNode(code_template="import socket\nsocket.gethostname()", safe_mode=True)
        result = asyncio.run(node.execute({}))
        assert "error" in result

    def test_safe_code_executes_in_safe_mode(self):
        node = CodeNode(code_template="result = 2 + 2", safe_mode=True)
        result = asyncio.run(node.execute({}))
        assert "output" in result
        assert result["output"] == "4"

    def test_safe_builtins_work_in_safe_mode(self):
        node = CodeNode(code_template="result = list(range(5))", safe_mode=True)
        result = asyncio.run(node.execute({}))
        assert "output" in result
        assert "[0, 1, 2, 3, 4]" in result["output"]

    def test_unsafe_mode_allows_dangerous_code(self):
        """Without safe_mode, dangerous code is NOT blocked (backward compat)."""
        node = CodeNode(code_template="import os", safe_mode=False)
        result = asyncio.run(node.execute({}))
        # Should NOT have safety error (might have exec error due to restricted builtins)
        assert "safety" not in result.get("error", "").lower()

    def test_default_safe_mode_is_false(self):
        """Default safe_mode is False for backward compatibility."""
        node = CodeNode(code_template="x = 1")
        assert node.safe_mode is False

    def test_from_import_dangerous_blocked(self):
        node = CodeNode(code_template="from os import system\nsystem('ls')", safe_mode=True)
        result = asyncio.run(node.execute({}))
        assert "error" in result


class TestCodeNodeInputReplacement:
    """Ensure input template replacement still works with safe_mode."""

    def test_input_replacement_in_safe_mode(self):
        node = CodeNode(code_template="result = {{name}}", safe_mode=True)
        result = asyncio.run(node.execute({"name": "hello"}))
        assert "output" in result
        assert "hello" in result["output"]

    def test_input_replacement_in_unsafe_mode(self):
        node = CodeNode(code_template="result = {{value}} + ' world'", safe_mode=False)
        result = asyncio.run(node.execute({"value": "hello"}))
        assert "output" in result
        assert result["output"] == "hello world"
