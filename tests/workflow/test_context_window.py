# tests/workflow/test_context_window.py
"""Tests for ContextWindow — dynamic context management."""

import pytest

from tools.workflow.engine import ContextWindow


class TestContextWindow:
    def test_add_and_build(self):
        cw = ContextWindow(max_tokens=4000)
        cw.add_system("You are a helpful agent")
        cw.add_user_message("Build auth module")
        prompt = cw.build()
        assert "[SYSTEM]" in prompt
        assert "[USER]" in prompt
        assert "helpful agent" in prompt

    def test_priority_eviction(self):
        """Low-priority items are evicted when max_items is exceeded."""
        cw = ContextWindow(max_items=5)
        cw.add_system("System prompt", priority=10)
        for i in range(10):
            cw.add_tool_result(f"Tool result {i}", priority=1)
        # System prompt (priority=10) should survive eviction
        prompt = cw.build()
        assert "System prompt" in prompt
        # Total items should not exceed max_items
        assert len(cw) <= 5

    def test_max_items_default(self):
        cw = ContextWindow()
        assert cw.max_items == 50
        assert cw.max_tokens == 8000

    def test_get_items_by_role(self):
        cw = ContextWindow()
        cw.add_system("System msg")
        cw.add_user_message("User msg")
        cw.add_tool_result("Tool result", tool_name="search")
        system_items = cw.get_items(role="system")
        assert len(system_items) == 1
        assert system_items[0].role == "system"

    def test_clear(self):
        cw = ContextWindow()
        cw.add_system("System")
        cw.add_tool_result("Tool result")
        cw.clear()
        assert len(cw) == 0

    def test_tool_name_in_output(self):
        cw = ContextWindow()
        cw.add_tool_result("Search results", tool_name="search")
        prompt = cw.build()
        assert "[SEARCH]" in prompt
