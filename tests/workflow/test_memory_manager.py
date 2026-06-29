# tests/workflow/test_memory_manager.py
"""Tests for MemoryManager — memory context building."""

import json

import pytest

from tools.rag.cognitive.memory_manager import MemoryManager


class TestMemoryManagerContext:
    def test_build_context(self, tmp_path):
        persist = tmp_path / "mem.json"
        data = {"memories": [
            {"content": "Use JWT for authentication", "source": "conversation",
             "importance": 0.8, "keywords": ["JWT", "auth"],
             "created_at": "2024-01-01T00:00:00", "last_accessed": "2024-01-01T00:00:00",
             "access_count": 0, "metadata": {}}
        ]}
        persist.write_text(json.dumps(data), encoding="utf-8")
        mm = MemoryManager(persist_path=str(persist))
        context = mm.build_context("auth module", token_budget=4000)
        assert isinstance(context, str)
        assert "JWT" in context or "Memory" in context

    def test_build_context_empty(self, tmp_path):
        persist = tmp_path / "mem.json"
        persist.write_text('{"memories": []}', encoding="utf-8")
        mm = MemoryManager(persist_path=str(persist))
        context = mm.build_context("test", token_budget=4000)
        assert context == ""
