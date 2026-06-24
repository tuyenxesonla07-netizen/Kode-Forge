"""
tools/messaging/message.py

统一消息信封 — 所有 Agent 间通信的消息格式
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
import uuid


class Topic:
    """消息 Topic 定义"""
    TASK_PREFIX = "tasks."
    RESULT_PREFIX = "results."
    EVENTS_PIPELINE = "events.pipeline"
    EVENTS_REVIEW = "events.review"
    COMMANDS_FIX = "commands.fix"

    @classmethod
    def task_for(cls, module: str) -> str:
        return f"{cls.TASK_PREFIX}{module}"

    @classmethod
    def result_for(cls, module: str) -> str:
        return f"{cls.RESULT_PREFIX}{module}"


@dataclass
class Message:
    """统一消息信封"""
    meta: Dict[str, Any]
    payload: Dict[str, Any]

    @classmethod
    def create(
        cls,
        from_agent: str,
        to_agent: str,
        phase: str,
        payload_type: str,
        payload: Dict,
        priority: str = "medium",
        correlation_id: Optional[str] = None,
    ) -> "Message":
        """工厂方法：创建消息"""
        meta = {
            "msg_id": str(uuid.uuid4()),
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "from": from_agent,
            "to": to_agent,
            "phase": phase,
            "priority": priority,
            "ttl_ms": 30000,
            "protocol_version": "1.0",
        }
        payload["type"] = payload_type
        return cls(meta=meta, payload=payload)

    @property
    def from_agent(self) -> str:
        return self.meta.get("from", "")

    @property
    def to_agent(self) -> str:
        return self.meta.get("to", "")

    @property
    def msg_id(self) -> str:
        return self.meta.get("msg_id", "")

    @property
    def correlation_id(self) -> str:
        return self.meta.get("correlation_id", "")

    def is_expired(self) -> bool:
        """检查消息是否过期"""
        ttl = self.meta.get("ttl_ms", 30000)
        # 简化：实际应该比较 timestamp + ttl
        return False

    def to_dict(self) -> Dict:
        return {"meta": self.meta, "payload": self.payload}

    def __repr__(self) -> str:
        return f"Message(from={self.from_agent}, to={self.to_agent}, type={self.payload.get('type')})"
