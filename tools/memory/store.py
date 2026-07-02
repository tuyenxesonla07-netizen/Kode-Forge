# tools/memory/store.py

"""
MemoryStore 接口 + 实现。

定义记忆存储的抽象接口，提供内存和 JSON 文件两种实现。
生产环境可扩展为 Postgres 实现。
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryStore(ABC):
    """记忆存储抽象接口"""

    @abstractmethod
    def get(self, session_id: str) -> Optional[dict]:
        """获取会话记忆数据"""
        ...

    @abstractmethod
    def put(self, session_id: str, data: dict) -> None:
        """保存会话记忆数据"""
        ...

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """删除会话记忆"""
        ...

    @abstractmethod
    def list_sessions(self) -> list[str]:
        """列出所有会话 ID"""
        ...


class InMemoryStore(MemoryStore):
    """内存存储（开发/测试用）"""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def get(self, session_id: str) -> Optional[dict]:
        return self._data.get(session_id)

    def put(self, session_id: str, data: dict) -> None:
        self._data[session_id] = data

    def delete(self, session_id: str) -> bool:
        if session_id in self._data:
            del self._data[session_id]
            return True
        return False

    def list_sessions(self) -> list[str]:
        return list(self._data.keys())


class JSONFileStore(MemoryStore):
    """JSON 文件存储（生产单机版）"""

    def __init__(self, persist_path: str = "data/memory_store.json") -> None:
        self.persist_path = Path(persist_path)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.persist_path.exists():
            try:
                self._data = json.loads(self.persist_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                self._data = {}

    def _save(self) -> None:
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[JSONFileStore] Save failed: %s", e)

    def get(self, session_id: str) -> Optional[dict]:
        return self._data.get(session_id)

    def put(self, session_id: str, data: dict) -> None:
        self._data[session_id] = data
        self._save()

    def delete(self, session_id: str) -> bool:
        if session_id in self._data:
            del self._data[session_id]
            self._save()
            return True
        return False

    def list_sessions(self) -> list[str]:
        return list(self._data.keys())
