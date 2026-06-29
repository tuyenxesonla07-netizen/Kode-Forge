"""Tests for LongTermMemory and MemoryStore."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tools.memory.long_term import LongTermMemory
from tools.memory.store import InMemoryStore, JSONFileStore, MemoryStore


# ---------------------------------------------------------------------------
# LongTermMemory
# ---------------------------------------------------------------------------

class TestLongTermMemory:
    @pytest.fixture
    def mem(self, tmp_path):
        """Create LongTermMemory with temp path (no file I/O)."""
        return LongTermMemory(persist_path=str(tmp_path / "test_memory.json"))

    def test_update_profile(self, mem):
        mem.update_profile("user_1", preferred_language="Python", role="backend")
        profile = mem.get_profile("user_1")
        assert profile["preferred_language"] == "Python"
        assert profile["role"] == "backend"

    def test_add_fact(self, mem):
        mem.add_fact("user_1", "Uses FastAPI for all APIs")
        facts = mem.get_facts("user_1")
        assert "Uses FastAPI for all APIs" in facts

    def test_add_fact_dedup(self, mem):
        mem.add_fact("user_1", "Same fact")
        mem.add_fact("user_1", "Same fact")
        facts = mem.get_facts("user_1")
        assert len(facts) == 1

    def test_add_interaction(self, mem):
        mem.add_interaction("user_1", {"intent": "code_gen", "modules": ["auth"]})
        interactions = mem.get_interactions("user_1")
        assert len(interactions) == 1
        assert interactions[0]["intent"] == "code_gen"
        assert "time" in interactions[0]

    def test_add_code_pattern(self, mem):
        mem.add_code_pattern("user_1", "uses Pydantic v2 for validation")
        ctx = mem.context_for("user_1")
        assert "Pydantic" in ctx

    def test_context_for_new_user(self, mem):
        ctx = mem.context_for("nonexistent")
        assert ctx == ""

    def test_context_includes_profile(self, mem):
        mem.update_profile("user_1", language="Python")
        ctx = mem.context_for("user_1")
        assert "User Profile" in ctx
        assert "Python" in ctx

    def test_context_includes_facts(self, mem):
        mem.add_fact("user_1", "Fact A")
        mem.add_fact("user_1", "Fact B")
        ctx = mem.context_for("user_1")
        assert "Known Facts" in ctx
        assert "Fact A" in ctx

    def test_context_includes_last_interaction(self, mem):
        mem.add_interaction("user_1", {"intent": "test", "type": "query"})
        ctx = mem.context_for("user_1")
        assert "Last Visit" in ctx

    def test_context_limits_facts(self, mem):
        for i in range(10):
            mem.add_fact("user_1", f"Fact {i}")
        ctx = mem.context_for("user_1")
        # Should only show last 3 facts (fact 7, 8, 9)
        assert "Fact 7" in ctx
        assert "Fact 8" in ctx
        assert "Fact 9" in ctx
        assert "Fact 0" not in ctx
        assert "Fact 1" not in ctx

    def test_delete_session(self, mem):
        mem.update_profile("user_1", test="value")
        assert mem.delete_session("user_1") is True
        assert mem.get_profile("user_1") == {}

    def test_delete_nonexistent_session(self, mem):
        assert mem.delete_session("nonexistent") is False

    def test_len(self, mem):
        assert len(mem) == 0
        mem.update_profile("user_1", test="value")
        assert len(mem) == 1
        mem.update_profile("user_2", test="value")
        assert len(mem) == 2

    def test_multiple_users_isolated(self, mem):
        mem.update_profile("user_1", role="admin")
        mem.update_profile("user_2", role="dev")
        assert mem.get_profile("user_1")["role"] == "admin"
        assert mem.get_profile("user_2")["role"] == "dev"

    def test_persist_to_file(self, tmp_path):
        path = str(tmp_path / "persist_test.json")
        mem = LongTermMemory(persist_path=path)
        mem.update_profile("user_1", lang="Python")
        mem.add_fact("user_1", "Test fact")

        # Create new instance from same file
        mem2 = LongTermMemory(persist_path=path)
        assert mem2.get_profile("user_1") == {"lang": "Python"}
        assert "Test fact" in mem2.get_facts("user_1")

    def test_profile_merge(self, mem):
        mem.update_profile("user_1", key1="val1")
        mem.update_profile("user_1", key2="val2")
        profile = mem.get_profile("user_1")
        assert profile == {"key1": "val1", "key2": "val2"}


# ---------------------------------------------------------------------------
# InMemoryStore
# ---------------------------------------------------------------------------

class TestInMemoryStore:
    def test_put_and_get(self):
        store = InMemoryStore()
        store.put("session_1", {"key": "value"})
        assert store.get("session_1") == {"key": "value"}

    def test_get_missing(self):
        store = InMemoryStore()
        assert store.get("nonexistent") is None

    def test_delete(self):
        store = InMemoryStore()
        store.put("s1", {"data": 1})
        assert store.delete("s1") is True
        assert store.get("s1") is None

    def test_delete_missing(self):
        store = InMemoryStore()
        assert store.delete("nonexistent") is False

    def test_list_sessions(self):
        store = InMemoryStore()
        store.put("s1", {})
        store.put("s2", {})
        sessions = store.list_sessions()
        assert set(sessions) == {"s1", "s2"}

    def test_list_sessions_empty(self):
        store = InMemoryStore()
        assert store.list_sessions() == []

    def test_overwrite(self):
        store = InMemoryStore()
        store.put("s1", {"v": 1})
        store.put("s1", {"v": 2})
        assert store.get("s1") == {"v": 2}


# ---------------------------------------------------------------------------
# JSONFileStore
# ---------------------------------------------------------------------------

class TestJSONFileStore:
    def test_put_and_get(self, tmp_path):
        path = str(tmp_path / "store.json")
        store = JSONFileStore(persist_path=path)
        store.put("s1", {"key": "value"})
        assert store.get("s1") == {"key": "value"}

    def test_persist(self, tmp_path):
        path = str(tmp_path / "persist.json")
        store1 = JSONFileStore(persist_path=path)
        store1.put("s1", {"data": "test"})

        store2 = JSONFileStore(persist_path=path)
        assert store2.get("s1") == {"data": "test"}

    def test_get_missing(self, tmp_path):
        path = str(tmp_path / "store.json")
        store = JSONFileStore(persist_path=path)
        assert store.get("nonexistent") is None

    def test_delete(self, tmp_path):
        path = str(tmp_path / "store.json")
        store = JSONFileStore(persist_path=path)
        store.put("s1", {})
        assert store.delete("s1") is True
        assert store.get("s1") is None

    def test_list_sessions(self, tmp_path):
        path = str(tmp_path / "store.json")
        store = JSONFileStore(persist_path=path)
        store.put("a", {})
        store.put("b", {})
        assert set(store.list_sessions()) == {"a", "b"}

    def test_corrupted_file(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{invalid json", encoding="utf-8")
        store = JSONFileStore(persist_path=str(path))
        assert store.get("any") is None


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestMemoryIntegration:
    def test_short_term_to_long_term_flow(self):
        """Short-term memory can feed into long-term memory."""
        from tools.memory.short_term import ShortTermMemory

        short = ShortTermMemory(window=4)
        short.add("user", "Build auth module with JWT")
        short.add("assistant", "Done with auth using FastAPI")

        # Extract key info for long-term
        long = LongTermMemory(persist_path=":memory:")
        long.update_profile("user_1", preferred_framework="FastAPI")
        long.add_fact("user_1", "Uses JWT for authentication")

        ctx = long.context_for("user_1")
        assert "FastAPI" in ctx
        assert "JWT" in ctx

    def test_memory_store_with_session_state(self):
        """MemoryStore can back SessionState persistence."""
        from tools.memory.session_state import SessionState

        store = InMemoryStore()
        state = SessionState(user_id="test_user")
        state.update(step=3, intent="code_gen")
        store.put("test_user", state.to_dict())

        retrieved = store.get("test_user")
        assert retrieved["step"] == 3
        assert retrieved["intent"] == "code_gen"
