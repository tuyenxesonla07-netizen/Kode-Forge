"""
Test Runner handler — test fixture.
"""
from __future__ import annotations


def run_tests(context: dict, test_path: str) -> dict:
    """Run unit tests (mock implementation for testing)."""
    return {"passed": 10, "failed": 0, "test_path": test_path}
