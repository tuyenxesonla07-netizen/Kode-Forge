"""Tests for examples/demo_showcase.py — end-to-end demo."""

import subprocess
import sys


class TestDemoShowcase:
    """Verify the demo runs without errors."""

    def test_demo_default_mode(self):
        """Demo runs in default mode with exit code 0."""
        result = subprocess.run(
            [sys.executable, "examples/demo_showcase.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Demo Summary" in result.stdout
        assert "Modules compiled:" in result.stdout

    def test_demo_with_schema_detail(self):
        """Demo runs with --schema flag."""
        result = subprocess.run(
            [sys.executable, "examples/demo_showcase.py", "--schema"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0
        assert "Context Strategies" in result.stdout

    def test_demo_with_security_detail(self):
        """Demo runs with --security flag."""
        result = subprocess.run(
            [sys.executable, "examples/demo_showcase.py", "--security"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0

    def test_demo_output_contains_key_steps(self):
        """Demo output shows all 6 pipeline steps."""
        result = subprocess.run(
            [sys.executable, "examples/demo_showcase.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0
        assert "[1]" in result.stdout  # Step 1
        assert "[2]" in result.stdout  # Step 2
        assert "[3]" in result.stdout  # Step 3
        assert "[4]" in result.stdout  # Step 4
        assert "[5]" in result.stdout  # Step 5
        assert "[6]" in result.stdout  # Step 6

    def test_demo_output_contains_architecture_points(self):
        """Demo summary lists architecture points."""
        result = subprocess.run(
            [sys.executable, "examples/demo_showcase.py"],
            capture_output=True, text=True, timeout=60,
        )
        assert "Schema-driven" in result.stdout
        assert "Multi-agent" in result.stdout
        assert "Security" in result.stdout
