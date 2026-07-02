# tools/memory/__init__.py

"""
Memory System — 短期记忆 + 长期记忆 + 会话状态。

参考 customer-service-agent 的 Memory 设计：
- ShortTermMemory: 滑动窗口 + 自动压缩（Compress 策略）
- LongTermMemory: 跨会话用户画像 + 事实 + 交互记录（JSON 持久化）
- SessionState: 会话状态 + checkpoint/resume

用法:
    from tools.memory import Memory, SessionState

    mem = Memory(session_id="user_123", persist_path="data/memory.json")
    mem.short.add("user", "Build auth module")
    mem.short.add("assistant", "Done")
    mem.long.add_fact("user_123", "Prefers FastAPI")

    state = SessionState(user_id="user_123")
    state.checkpoint("phase1_done")
"""

from tools.memory.short_term import ShortTermMemory, Message
from tools.memory.long_term import LongTermMemory
from tools.memory.session_state import SessionState
from tools.memory.store import MemoryStore, InMemoryStore, JSONFileStore
from typing import Any

__all__ = [
    "ShortTermMemory",
    "LongTermMemory",
    "SessionState",
    "MemoryStore",
    "InMemoryStore",
    "JSONFileStore",
    "Message",
]


class Memory:
    """短期 + 长期记忆的统一门面。"""

    def __init__(self, session_id: str = "default", window: int = 12,
                 persist_path: str = "data/memory_store.json") -> None:
        self.session_id = session_id
        self.short = ShortTermMemory(window=window)
        self.long = LongTermMemory(persist_path=persist_path)
        self._loaded = False

    def load(self) -> Any:
        """从长期记忆中加载历史到短期记忆上下文"""
        context = self.long.context_for(self.session_id)
        self._loaded = True
        return context

    def save_interaction(self, role: str, content: str, metadata: dict = None) -> None:
        """保存一条交互记录"""
        self.short.add(role, content, metadata)
        self.long.add_interaction(self.session_id, {
            "role": role,
            "content": content[:200],
            **(metadata or {}),
        })

    def add_fact(self, fact: str) -> None:
        """添加用户事实（去重）"""
        self.long.add_fact(self.session_id, fact)

    def update_profile(self, **fields) -> None:
        """更新用户画像"""
        self.long.update_profile(self.session_id, **fields)

    def context_for_prompt(self) -> str:
        """生成注入 system prompt 的上下文文本"""
        return self.long.context_for(self.session_id)

    def status(self) -> dict:
        return {
            "session_id": self.session_id,
            "short_term_messages": len(self.short.messages),
            "short_term_summary": self.short.summary or "(none)",
            "long_term_users": len(self.long.store),
            "loaded": self._loaded,
        }
