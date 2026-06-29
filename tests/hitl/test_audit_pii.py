# tests/hitl/test_audit_pii.py
"""Tests for AuditLog — PII masking in audit records."""

import pytest

from tools.hitl.audit import AuditLog


class TestAuditLogPIIMasking:
    def test_mask_phone_number(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "query", "args": {"phone": "13812345678"}})
        records = log.query()
        assert records[0]["args"]["phone"] == "[PHONE]"

    def test_mask_email(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "send", "args": {"to": "user@example.com"}})
        records = log.query()
        assert records[0]["args"]["to"] == "[EMAIL]"

    def test_mask_api_key(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "call", "args": {"key": "sk-abc123def456"}})
        records = log.query()
        assert records[0]["args"]["key"] == "[API_KEY]"

    def test_mask_id_card(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "verify", "args": {"id": "110101199003071234"}})
        records = log.query()
        assert records[0]["args"]["id"] == "[ID_CARD]"

    def test_no_pii_in_plain_args(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "search", "args": {"query": "hello world"}})
        records = log.query()
        assert records[0]["args"]["query"] == "hello world"

    def test_nested_dict_masking(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "complex", "args": {"user": {"phone": "13999999999", "name": "张三"}}})
        records = log.query()
        assert records[0]["args"]["user"]["phone"] == "[PHONE]"
        assert records[0]["args"]["user"]["name"] == "张三"

    def test_non_string_args_unchanged(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "calc", "args": {"count": 42, "active": True}})
        records = log.query()
        assert records[0]["args"]["count"] == 42
        assert records[0]["args"]["active"] is True

    def test_summary_works_with_masked_data(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.jsonl"))
        log.record({"tool": "query", "args": {"phone": "13812345678"}})
        log.record({"tool": "search", "args": {"query": "hello"}})
        s = log.summary()
        assert s["total_records"] == 2
