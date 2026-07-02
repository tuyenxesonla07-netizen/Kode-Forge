# tools/memory/long_term.py

"""
长期记忆 — 跨会话的用户画像、事实和交互记录。

参考 customer-service-agent 的 LongTermMemory：
- 用户画像 (profile): 偏好语言、技术栈、角色等
- 事实 (facts): 去重的事实列表（如"订单 ORD-2024-0001 已退款"）
- 交互记录 (interactions): 每次对话的时间戳和元数据

持久化: JSON 文件（生产可换为 Postgres）。
进入长期记忆的内容必须已脱敏 — 上游 InputGuard 保证这一点。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class LongTermMemory:
    """
    长期记忆存储。

    每个用户一个条目，包含 profile、facts、interactions。
    数据持久化到 JSON 文件，支持热加载。

    用法:
        mem = LongTermMemory("data/memory_store.json")
        mem.update_profile("user_1", preferred_language="Python")
        mem.add_fact("user_1", "Uses FastAPI for all APIs")
        mem.add_interaction("user_1", {"intent": "code_gen", "modules": ["auth"]})
        context = mem.context_for("user_1")
    """

    def __init__(self, persist_path: str = "data/memory_store.json") -> None:
        self.persist_path = Path(persist_path) if persist_path else None
        self.store: dict[str, dict] = {}
        if self.persist_path and self.persist_path.exists():
            self._load()

    def _user(self, session_id: str) -> dict:
        """获取或创建用户条目"""
        if session_id not in self.store:
            self.store[session_id] = {
                "profile": {},
                "facts": [],
                "interactions": [],
            }
        return self.store[session_id]

    def update_profile(self, session_id: str, **fields) -> None:
        """更新用户画像（合并而非覆盖）"""
        self._user(session_id)["profile"].update(fields)
        self._save()

    def add_fact(self, session_id: str, fact: str) -> None:
        """添加事实（去重）"""
        facts = self._user(session_id)["facts"]
        if fact not in facts:
            facts.append(fact)
            self._save()

    def add_interaction(self, session_id: str, record: dict) -> None:
        """添加交互记录（带时间戳）"""
        record.setdefault("time", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self._user(session_id)["interactions"].append(record)
        self._save()

    def add_code_pattern(self, session_id: str, pattern: str) -> None:
        """添加代码模式（V3 特定：记录用户的代码风格偏好）"""
        user = self._user(session_id)
        patterns = user.setdefault("code_patterns", [])
        if pattern not in patterns:
            patterns.append(pattern)
            self._save()

    def context_for(self, session_id: str) -> str:
        """
        生成注入 system prompt 的用户上下文。

        只取摘要级信息（不注入原始交互内容），保护隐私。
        """
        user = self.store.get(session_id)
        if not user:
            return ""

        parts: list[str] = []

        # 用户画像
        if user.get("profile"):
            profile_str = ", ".join(f"{k}: {v}" for k, v in user["profile"].items())
            parts.append(f"User Profile: {profile_str}")

        # 最近 3 条事实
        facts = user.get("facts", [])
        if facts:
            parts.append("Known Facts: " + "; ".join(facts[-3:]))

        # 代码模式
        patterns = user.get("code_patterns", [])
        if patterns:
            parts.append("Code Patterns: " + ", ".join(patterns[-5:]))

        # 上次交互
        interactions = user.get("interactions", [])
        if interactions:
            last = interactions[-1]
            parts.append(
                f"Last Visit: {last.get('time', '')} — "
                f"{last.get('intent', last.get('type', 'unknown'))}"
            )

        return "\n".join(parts)

    def get_profile(self, session_id: str) -> dict:
        """获取用户画像"""
        return self._user(session_id).get("profile", {})

    def get_facts(self, session_id: str) -> list[str]:
        """获取所有事实"""
        return self._user(session_id).get("facts", [])

    def get_interactions(self, session_id: str, limit: int = 10) -> list[dict]:
        """获取最近交互记录"""
        interactions = self._user(session_id).get("interactions", [])
        return interactions[-limit:]

    def delete_session(self, session_id: str) -> bool:
        """删除会话的所有长期记忆"""
        if session_id in self.store:
            del self.store[session_id]
            self._save()
            return True
        return False

    def _save(self) -> None:
        """持久化到 JSON"""
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(
                json.dumps(self.store, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[LongTermMemory] Save failed: %s", e)

    def _load(self) -> None:
        """从 JSON 加载"""
        try:
            self.store = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            self.store = {}

    def __len__(self) -> int:
        return len(self.store)
