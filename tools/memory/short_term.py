# tools/memory/short_term.py

"""
短期记忆 — 滑动窗口 + 自动压缩（Compress 策略）。

参考 customer-service-agent 的 ShortTermMemory：
- 窗口满时自动将最老的一半消息压缩为摘要
- 摘要提取：订单号、关键词、话题
- 保证多轮对话里"上文给过的关键信息"不丢失
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Message:
    """单条消息"""
    role: str               # "user" | "assistant" | "system"
    content: str
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class ShortTermMemory:
    """
    滑动窗口短期记忆。

    当消息数超过 window 时，最老的一半被压缩为摘要（而非直接丢弃）。
    摘要策略：提取订单号 ID 模式、业务关键词、话题。

    用法:
        mem = ShortTermMemory(window=12)
        mem.add("user", "Build auth module")
        mem.add("assistant", "Done")
        messages = mem.context()  # 返回摘要 + 当前窗口
    """

    # 从文本中提取的关键词（可扩展）
    COMPRESS_KEYWORDS = [
        "退款", "投诉", "订单", "政策", "物流", "商品", "优惠",
        "登录", "注册", "支付", "认证", "接口", "模块", "数据库",
        "auth", "api", "test", "deploy", "review", "fix",
    ]

    ID_PATTERNS = [
        r"ORD-\d{4}-\d{4}",       # 订单号
        r"MOD-\w+",              # 模块号
        r"API-\w+",              # 接口号
    ]

    def __init__(self, window: int = 12) -> None:
        self.window = window
        self.messages: list[Message] = []
        self.summary: str = ""

    def add(self, role: str, content: str, metadata: dict = None) -> None:
        """添加一条消息，超窗时自动压缩"""
        self.messages.append(Message(role=role, content=content, metadata=metadata or {}))
        if len(self.messages) > self.window:
            self._compress()

    def _compress(self) -> None:
        """将最老的一半消息压缩为摘要"""
        half = self.window // 2
        old_messages = self.messages[:half]
        self.messages = self.messages[half:]

        # 提取关键信息
        all_text = " ".join(m["content"] for m in old_messages) if isinstance(old_messages[0], dict) else " ".join(m.content for m in old_messages)

        # 提取 ID
        ids = set()
        for pattern in self.ID_PATTERNS:
            ids.update(re.findall(pattern, all_text))

        # 提取关键词
        found_keywords = [kw for kw in self.COMPRESS_KEYWORDS if kw in all_text]

        # 组装摘要
        parts = [f"earlier {len(old_messages)} messages"]
        if found_keywords:
            parts.append(f"topics: {', '.join(found_keywords[:5])}")
        if ids:
            parts.append(f"IDs: {', '.join(sorted(ids)[:5])}")

        new_summary = "; ".join(parts)
        self.summary = (self.summary + " | " + new_summary) if self.summary else new_summary

    def context(self) -> list[dict]:
        """
        组装进入 LLM 的消息列表。

        返回: [摘要消息(如有)] + 当前窗口消息
        """
        result = []
        if self.summary:
            result.append({"role": "system", "content": f"[Session Summary] {self.summary}"})
        result.extend(msg.to_dict() for msg in self.messages)
        return result

    def clear(self) -> None:
        """清空所有消息和摘要"""
        self.messages.clear()
        self.summary = ""

    def __len__(self) -> int:
        return len(self.messages)
