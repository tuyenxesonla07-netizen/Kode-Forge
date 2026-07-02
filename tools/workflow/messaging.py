# tools/workflow/messaging.py

"""
消息总线 — Agent 间通信的唯一通道。

从 engine.py 中拆出，使核心引擎文件更聚焦。

本模块包含:
  - Topic    — 消息 Topic 常量与工厂方法
  - Message  — 统一消息信封（含工厂方法）
  - MessageBus — 发布/订阅消息总线
"""

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

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
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
        """检查消息是否过期（基于 ttl_ms）"""
        ttl_ms = self.meta.get("ttl_ms")
        if ttl_ms is None:
            return False
        try:
            ts = datetime.fromisoformat(self.meta["timestamp"].replace("Z", "+00:00"))
            elapsed_ms = (datetime.now(timezone.utc) - ts).total_seconds() * 1000
            return elapsed_ms > ttl_ms
        except (ValueError, KeyError):
            return False

    def to_dict(self) -> Dict:
        return {"meta": self.meta, "payload": self.payload}

    def __repr__(self) -> str:
        return f"Message(from={self.from_agent}, to={self.to_agent}, type={self.payload.get('type')})"


# ---------------------------------------------------------------------------
# MessageBus
# ---------------------------------------------------------------------------

class MessageBus:
    """消息总线 — Agent 间通信的唯一通道"""

    def __init__(self, max_history: int = 1000) -> None:
        self._queues: Dict[str, deque] = defaultdict(deque)
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: deque = deque(maxlen=max_history)
        self._lock = threading.Lock()

    def publish(self, topic_or_message, message: Optional[Message] = None) -> None:
        """
        发布消息

        用法 1: publish(message)  — 发布到消息的 to_agent 队列
        用法 2: publish(topic, message) — 发布到指定 topic（广播）
        """
        if message is None:
            message = topic_or_message
            target = message.to_agent
            with self._lock:
                self._queues[target].append(message)
                self._history.append(message)
        else:
            topic = topic_or_message
            with self._lock:
                self._history.append(message)
                for callback in self._subscribers.get(topic, []):
                    try:
                        callback(message)
                    except Exception as e:
                        logger.warning("Subscriber error on %s: %s", topic, e)

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> Callable[[], None]:
        """订阅 topic，返回取消订阅函数。

        用法:
            unsub = bus.subscribe("topic", handler)
            unsub()  # 取消订阅
        """
        self._subscribers[topic].append(callback)
        return lambda: self.unsubscribe(topic, callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        """取消订阅"""
        if callback in self._subscribers.get(topic, []):
            self._subscribers[topic].remove(callback)

    def receive(self, agent_id: str, timeout_ms: int = 5000) -> Optional[Message]:
        """同步接收消息（带超时）"""
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            with self._lock:
                if self._queues[agent_id]:
                    return self._queues[agent_id].popleft()
            time.sleep(0.01)
        return None

    def peek(self, agent_id: str) -> Optional[Message]:
        """查看队列头部消息（不取出）"""
        with self._lock:
            if self._queues[agent_id]:
                return self._queues[agent_id][0]
        return None

    def get_queue_size(self, agent_id: str) -> int:
        """获取队列大小"""
        return len(self._queues.get(agent_id, []))

    def get_history(self, agent_id: str = None, limit: int = 100) -> List[Message]:
        """获取通信历史"""
        with self._lock:
            if agent_id:
                return [
                    m for m in self._history
                    if m.from_agent == agent_id or m.to_agent == agent_id
                ][-limit:]
            return list(self._history)[-limit:]

    def get_all_topics(self) -> List[str]:
        """获取所有活跃 topic"""
        return list(self._subscribers.keys())

    def clear(self) -> None:
        """清空所有队列和历史"""
        with self._lock:
            self._queues.clear()
            self._history.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取总线统计信息"""
        return {
            "active_queues": len(self._queues),
            "total_messages": len(self._history),
            "active_topics": len(self._subscribers),
            "queue_sizes": {k: len(v) for k, v in self._queues.items()},
        }
