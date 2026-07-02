# tools/hitl/audit_chain.py

"""
防篡改审计日志 — SHA256 hash chain。

每条记录包含前一条记录的哈希，形成链式结构，确保：
- 任何历史记录的篡改都会被检测
- 插入或删除记录会破坏链完整性
- 可通过 verify_chain() 验证整个链条
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# 创世哈希（链首记录的 prev_hash 值）
GENESIS_HASH = "0" * 64


def _compute_hash(prev_hash: str, event: dict) -> str:
    """
    计算记录的 SHA256 哈希。

    哈希 = SHA256(prev_hash + canonical_json(event))

    Args:
        prev_hash: 前一条记录的哈希
        event: 事件字典（不含 hash 字段）

    Returns:
        64 字符十六进制哈希字符串
    """
    canonical = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    data = prev_hash + canonical
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass
class ChainedRecord:
    """带哈希链的审计记录。"""
    event: dict
    prev_hash: str
    hash: str
    timestamp: str


class HashChainedAuditLog:
    """
    防篡改的 hash-chained 审计日志。

    用法:
        log = HashChainedAuditLog()
        h1 = log.record({"tool": "generate_code", "ok": True})
        h2 = log.record({"tool": "run_tests", "ok": True})
        is_valid, last_idx = log.verify_chain()
        assert is_valid
    """

    def __init__(self) -> None:
        self._records: list[ChainedRecord] = []

    def record(self, event: dict) -> str:
        """
        记录一条审计事件并返回其哈希。

        Args:
            event: 事件字典（不应包含 "hash" 字段）

        Returns:
            记录的 SHA256 哈希（64 字符十六进制）
        """
        # 移除可能存在的 hash 字段（防止调用者误传）
        event = {k: v for k, v in event.items() if k != "hash"}

        prev_hash = self._records[-1].hash if self._records else GENESIS_HASH
        record_hash = _compute_hash(prev_hash, event)

        record = ChainedRecord(
            event=event,
            prev_hash=prev_hash,
            hash=record_hash,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._records.append(record)
        return record_hash

    def verify_chain(self) -> tuple[bool, int]:
        """
        验证整个哈希链的完整性。

        Returns:
            (is_valid, last_valid_index)
            - is_valid: 链是否完整
            - last_valid_index: 最后有效记录的索引（-1 表示空链）
        """
        if not self._records:
            return True, -1

        # 验证创世链接
        if self._records[0].prev_hash != GENESIS_HASH:
            return False, -1

        # 逐条验证后续记录
        for i in range(len(self._records)):
            rec = self._records[i]

            # 重新计算哈希
            expected_hash = _compute_hash(rec.prev_hash, rec.event)
            if rec.hash != expected_hash:
                return False, i - 1

            # 验证链式连接（第一条除外）
            if i > 0:
                if rec.prev_hash != self._records[i - 1].hash:
                    return False, i - 1

        return True, len(self._records) - 1

    def get_record(self, index: int) -> Optional[ChainedRecord]:
        """获取指定索引的记录。"""
        if 0 <= index < len(self._records):
            return self._records[index]
        return None

    def find_by_hash(self, record_hash: str) -> Optional[int]:
        """通过哈希查找记录索引。"""
        for i, rec in enumerate(self._records):
            if rec.hash == record_hash:
                return i
        return None

    @property
    def last_hash(self) -> str:
        """返回最后一条记录的哈希（用于外部引用）。"""
        if not self._records:
            return GENESIS_HASH
        return self._records[-1].hash

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, index: int) -> ChainedRecord:
        return self._records[index]
