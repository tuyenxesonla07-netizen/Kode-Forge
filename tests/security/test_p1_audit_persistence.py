"""P1-3 security tests: HashChainedAuditLog SQLite persistence.

Previously the audit log was purely in-memory and lost all records on restart.
Tests below verify that records survive process restart via SQLite WAL storage.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from tools.hitl.audit_chain import HashChainedAuditLog, GENESIS_HASH


# ---------------------------------------------------------------------------
# In-memory mode must remain unchanged (backward compat)
# ---------------------------------------------------------------------------

class TestInMemoryMode:
    def test_basic_record_and_verify(self):
        log = HashChainedAuditLog()
        log.record({"event": "test", "a": 1})
        log.record({"event": "test2", "b": 2})
        valid, idx = log.verify_chain()
        assert valid
        assert idx == 1

    def test_no_persistence_by_default(self):
        """Default constructor must NOT create any files."""
        log = HashChainedAuditLog()
        assert log._conn is None


# ---------------------------------------------------------------------------
# Persistence mode
# ---------------------------------------------------------------------------

class TestPersistentMode:
    @pytest.fixture
    def tmp_path(self, tmp_path_factory):
        return tmp_path_factory.mktemp("audit")

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "audit.db")

    def test_records_written_to_disk(self, db_path):
        """Records must appear in the SQLite file."""
        log = HashChainedAuditLog(persist_path=db_path)
        log.record({"event": "login", "user": "alice"})
        log.record({"event": "logout", "user": "alice"})
        log.close()

        # Directly inspect the DB
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM audit_chain").fetchone()
        conn.close()
        assert rows[0] == 2

    def test_survives_restart(self, db_path):
        """Records from a previous process must be loaded on restart."""
        # Process 1: record events
        log1 = HashChainedAuditLog(persist_path=db_path)
        h1 = log1.record({"event": "deploy", "target": "production"})
        h2 = log1.record({"event": "verify", "status": "ok"})
        assert len(log1) == 2
        log1.close()

        # Process 2: new instance, should load 2 records
        log2 = HashChainedAuditLog(persist_path=db_path)
        assert len(log2) == 2
        # Hashes must match (same chain)
        assert log2[0].hash == h1
        assert log2[1].hash == h2
        # verify_chain still works after reload
        valid, idx = log2.verify_chain()
        assert valid
        assert idx == 1
        log2.close()

    def test_chain_integrity_after_restart(self, db_path):
        """Tamper detection must work on records loaded from disk."""
        log = HashChainedAuditLog(persist_path=db_path)
        for i in range(5):
            log.record({"event": f"action-{i}", "idx": i})
        log.close()

        # Reload — chain must still verify
        log2 = HashChainedAuditLog(persist_path=db_path)
        valid, idx = log2.verify_chain()
        assert valid
        assert idx == 4
        log2.close()

    def test_tampered_disk_record_detected(self, db_path):
        """Direct DB tampering must be detected on next load."""
        log = HashChainedAuditLog(persist_path=db_path)
        log.record({"event": "legit", "ok": True})
        log.record({"event": "legit2", "ok": True})
        log.close()

        # Tamper: modify the first event in the DB
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE audit_chain SET event_json = ? WHERE idx = 0",
            ('{"event": "HACKED", "ok": false}',),
        )
        conn.commit()
        conn.close()

        # Reload and verify — must detect tampering
        log2 = HashChainedAuditLog(persist_path=db_path)
        valid, idx = log2.verify_chain()
        assert not valid
        assert idx == -1  # first record's hash won't match
        log2.close()

    def test_records_loaded_in_order(self, db_path):
        """Records must be loaded in insertion order."""
        log = HashChainedAuditLog(persist_path=db_path)
        log.record({"seq": 0})
        log.record({"seq": 1})
        log.record({"seq": 2})
        log.close()

        log2 = HashChainedAuditLog(persist_path=db_path)
        assert [r.event["seq"] for r in log2._records] == [0, 1, 2]
        log2.close()

    def test_empty_db_starts_fresh(self, db_path):
        """First run with empty DB should start cleanly."""
        log = HashChainedAuditLog(persist_path=db_path)
        assert len(log) == 0
        valid, idx = log.verify_chain()
        assert valid
        assert idx == -1
        log.close()
