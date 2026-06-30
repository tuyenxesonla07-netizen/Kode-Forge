# tests/hitl/test_audit_chain.py

"""
Tests for tools.hitl.audit_chain — HashChainedAuditLog, ChainedRecord, _compute_hash.
"""

import json
import pytest

from tools.hitl.audit_chain import (
    GENESIS_HASH,
    ChainedRecord,
    HashChainedAuditLog,
    _compute_hash,
)


# ── _compute_hash ───────────────────────────────────────────────

class TestComputeHash:

    def test_returns_64_char_hex(self):
        h = _compute_hash(GENESIS_HASH, {"tool": "test", "ok": True})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_events_produce_different_hashes(self):
        h1 = _compute_hash(GENESIS_HASH, {"tool": "test1"})
        h2 = _compute_hash(GENESIS_HASH, {"tool": "test2"})
        assert h1 != h2

    def test_same_input_produces_same_hash(self):
        h1 = _compute_hash(GENESIS_HASH, {"tool": "test", "ok": True})
        h2 = _compute_hash(GENESIS_HASH, {"tool": "test", "ok": True})
        assert h1 == h2

    def test_prev_hash_affects_result(self):
        h1 = _compute_hash(GENESIS_HASH, {"tool": "test"})
        h2 = _compute_hash("a" * 64, {"tool": "test"})
        assert h1 != h2

    def test_key_order_does_not_matter(self):
        """canonical JSON 使用 sort_keys=True，键顺序不影响哈希。"""
        h1 = _compute_hash(GENESIS_HASH, {"a": 1, "b": 2})
        h2 = _compute_hash(GENESIS_HASH, {"b": 2, "a": 1})
        assert h1 == h2


# ── ChainedRecord ──────────────────────────────────────────────

class TestChainedRecord:

    def test_creation(self):
        rec = ChainedRecord(
            event={"tool": "test"},
            prev_hash=GENESIS_HASH,
            hash="abc123",
            timestamp="2026-06-30T00:00:00+00:00",
        )
        assert rec.event == {"tool": "test"}
        assert rec.prev_hash == GENESIS_HASH
        assert rec.hash == "abc123"


# ── HashChainedAuditLog ────────────────────────────────────────

class TestHashChainedAuditLogInit:

    def test_empty_on_creation(self):
        log = HashChainedAuditLog()
        assert len(log) == 0
        assert log.last_hash == GENESIS_HASH

    def test_verify_empty_chain(self):
        log = HashChainedAuditLog()
        is_valid, last_idx = log.verify_chain()
        assert is_valid
        assert last_idx == -1


class TestHashChainedAuditLogRecord:

    def test_first_record_has_genesis_prev_hash(self):
        log = HashChainedAuditLog()
        h = log.record({"tool": "test"})
        assert len(log) == 1
        rec = log[0]
        assert rec.prev_hash == GENESIS_HASH
        assert rec.hash == h

    def test_second_record_links_to_first(self):
        log = HashChainedAuditLog()
        h1 = log.record({"tool": "first"})
        h2 = log.record({"tool": "second"})
        assert log[1].prev_hash == h1
        assert log[1].hash == h2

    def test_chain_links(self):
        log = HashChainedAuditLog()
        hashes = []
        for i in range(5):
            h = log.record({"step": i})
            hashes.append(h)
        for i in range(1, 5):
            assert log[i].prev_hash == hashes[i - 1]

    def test_record_hash_matches_computed(self):
        log = HashChainedAuditLog()
        event = {"tool": "generate_code", "module": "auth"}
        h = log.record(event)
        expected = _compute_hash(GENESIS_HASH, event)
        assert h == expected

    def test_record_ignores_hash_field_in_event(self):
        """即使 event 中包含 'hash' 键，计算时应排除。"""
        log = HashChainedAuditLog()
        h = log.record({"tool": "test", "hash": "should_be_ignored"})
        # 实际计算用的是去掉 hash 字段后的事件
        expected = _compute_hash(GENESIS_HASH, {"tool": "test"})
        assert h == expected

    def test_last_hash_updates(self):
        log = HashChainedAuditLog()
        assert log.last_hash == GENESIS_HASH
        h1 = log.record({"step": 1})
        assert log.last_hash == h1
        h2 = log.record({"step": 2})
        assert log.last_hash == h2

    def test_timestamp_is_set(self):
        log = HashChainedAuditLog()
        log.record({"tool": "test"})
        rec = log[0]
        assert rec.timestamp is not None
        assert "T" in rec.timestamp  # ISO format


class TestHashChainedAuditLogVerify:

    def test_valid_chain(self):
        log = HashChainedAuditLog()
        for i in range(5):
            log.record({"step": i})
        is_valid, last_idx = log.verify_chain()
        assert is_valid
        assert last_idx == 4

    def test_tampered_event_detected(self):
        """篡改事件内容会被检测。"""
        log = HashChainedAuditLog()
        log.record({"step": 1})
        log.record({"step": 2})
        # 篡改第一条记录
        log._records[0].event["step"] = 999
        is_valid, last_idx = log.verify_chain()
        assert not is_valid
        assert last_idx == -1  # 第一条就失败了

    def test_tampered_hash_detected(self):
        """篡改哈希值会被检测。"""
        log = HashChainedAuditLog()
        log.record({"step": 1})
        log.record({"step": 2})
        log._records[0].hash = "f" * 64
        is_valid, last_idx = log.verify_chain()
        assert not is_valid

    def test_tampered_prev_hash_detected(self):
        """篡改 prev_hash 会被检测。"""
        log = HashChainedAuditLog()
        log.record({"step": 1})
        log.record({"step": 2})
        log._records[1].prev_hash = "f" * 64
        is_valid, last_idx = log.verify_chain()
        assert not is_valid
        assert last_idx == 0  # 第一条有效，第二条失败

    def test_genesis_mismatch_detected(self):
        """第一条记录的 prev_hash 不是 GENESIS_HASH 会被检测。"""
        log = HashChainedAuditLog()
        log.record({"step": 1})
        log._records[0].prev_hash = "f" * 64
        is_valid, last_idx = log.verify_chain()
        assert not is_valid
        assert last_idx == -1

    def test_single_record_valid(self):
        log = HashChainedAuditLog()
        log.record({"step": 1})
        is_valid, last_idx = log.verify_chain()
        assert is_valid
        assert last_idx == 0


class TestHashChainedAuditLogFind:

    def test_get_record(self):
        log = HashChainedAuditLog()
        log.record({"step": 1})
        rec = log.get_record(0)
        assert rec is not None
        rec = log.get_record(1)
        assert rec is None

    def test_find_by_hash(self):
        log = HashChainedAuditLog()
        h1 = log.record({"step": 1})
        h2 = log.record({"step": 2})
        assert log.find_by_hash(h1) == 0
        assert log.find_by_hash(h2) == 1
        assert log.find_by_hash("nonexistent") is None

    def test_getitem(self):
        log = HashChainedAuditLog()
        log.record({"step": 1})
        assert log[0].event == {"step": 1}


class TestHashChainedAuditLogLen:

    def test_len_empty(self):
        log = HashChainedAuditLog()
        assert len(log) == 0

    def test_len_after_records(self):
        log = HashChainedAuditLog()
        log.record({"step": 1})
        log.record({"step": 2})
        log.record({"step": 3})
        assert len(log) == 3
