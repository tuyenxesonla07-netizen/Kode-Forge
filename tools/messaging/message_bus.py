"""
tools/messaging/message_bus.py

消息总线 — 事件驱动的 Agent 间通信枢纽

设计决策: 采用消息队列 + 事件驱动模型（与 v1.0 一致），不引入 REST API。
Python 增强模块通过事件订阅接入，不改变通信范式。
"""

import threading
import time
from collections import defaultdict, deque
from typing import Dict, List, Callable, Optional, Any

from tools.messaging.message import Message, Topic


class MessageBus:
    """消息总线 — Agent 间通信的唯一通道"""

    def __init__(self, max_history: int = 1000):
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
            # 用法 1: 直接传 Message 对象
            message = topic_or_message
            target = message.to_agent
            with self._lock:
                self._queues[target].append(message)
                self._history.append(message)
        else:
            # 用法 2: topic + message
            topic = topic_or_message
            with self._lock:
                self._history.append(message)
                # 通知该 topic 的所有订阅者
                for callback in self._subscribers.get(topic, []):
                    try:
                        callback(message)
                    except Exception as e:
                        # 记录但不中断其他订阅者
                        print(f"Subscriber error on {topic}: {e}")

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> None:
        """订阅 topic"""
        self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        """取消订阅"""
        if callback in self._subscribers.get(topic, []):
            self._subscribers[topic].remove(callback)

    def receive(self, agent_id: str, timeout_ms: int = 5000) -> Optional[Message]:
        """
        同步接收消息（带超时）
        用于 Agent 等待任务或结果
        """
        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            with self._lock:
                if self._queues[agent_id]:
                    return self._queues[agent_id].popleft()
            time.sleep(0.01)  # 短暂等待
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

    def clear(self):
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
