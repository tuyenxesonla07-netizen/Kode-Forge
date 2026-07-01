# tools/messaging/multichannel_bus.py

"""
多渠道总线 — 包装 MessageBus，按路由规则分发到各渠道适配器。

MessageBus API 保持不变，MultiChannelBus 通过组合包装。
路由规则基于 topic 模式匹配（支持通配符 *）。

用法:
    inner = MessageBus()
    registry = ChannelRegistry()
    registry.register("slack", SlackAdapter(token="xoxb-...", channel_id="C123"))
    registry.register("sse", SSEAdapter())

    rules = {
        "results.*": ["slack", "webhook"],
        "events.pipeline": ["sse"],
        "escalation.*": ["slack", "email"],
    }

    bus = MultiChannelBus(inner=inner, registry=registry, routing_rules=rules)
    bus.publish("escalation.sla_timeout", {"approval_id": "abc"})
    # 自动路由到 slack + email
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from typing import Any, Callable

from tools.messaging.channel import ChannelAdapter, MessageEnvelope, ChannelRegistry
from tools.workflow.messaging import MessageBus, Message

logger = logging.getLogger(__name__)

class MultiChannelBus:
    """
    多渠道消息总线。

    组合包装 MessageBus，增加按 topic 路由到外部渠道的能力。
    所有通过 publish(topic, message) 发布的消息，除了正常写入 MessageBus 外，
    还会根据 routing_rules 匹配并分发到对应渠道适配器。
    """

    def __init__(
        self,
        inner: MessageBus,
        registry: ChannelRegistry,
        routing_rules: dict[str, list[str]] | None = None,
    ) -> None:
        """
        Args:
            inner: 内部 MessageBus 实例
            registry: 渠道注册表
            routing_rules: 路由规则 {topic_pattern: [channel_name, ...]}
        """
        self._inner = inner
        self._registry = registry
        self._routing_rules = routing_rules or {}
        self._started = False

    @property
    def inner(self) -> MessageBus:
        """获取内部 MessageBus。"""
        return self._inner

    @property
    def registry(self) -> ChannelRegistry:
        """获取渠道注册表。"""
        return self._registry

    def publish(self, topic: str, message=None) -> None:
        """
        发布消息到内部总线 + 匹配的外部渠道。

        用法 1: publish(message) — 发布到内部总线
        用法 2: publish(topic, message) — 发布到内部总线 + 外部渠道路由
        """

        if message is None:
            # 用法 1: 只有 message
            msg = topic
            self._inner.publish(msg)
            return

        # 用法 2: topic + message
        self._inner.publish(topic, message)

        # 路由到外部渠道
        matched_channels = self._match_routes(topic)
        if matched_channels:
            self._dispatch_to_channels(topic, message, matched_channels)

    def subscribe(self, topic: str, callback: Callable) -> Callable:
        """订阅（透传到内部总线）。"""
        return self._inner.subscribe(topic, callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        """取消订阅（透传到内部总线）。"""
        self._inner.unsubscribe(topic, callback)

    def receive(self, agent_id: str, timeout_ms: int = 5000) -> Any:
        """同步接收（透传到内部总线）。"""
        return self._inner.receive(agent_id, timeout_ms)

    def get_history(self, agent_id: str = None, limit: int = 100) -> Any:
        """获取历史（透传到内部总线）。"""
        return self._inner.get_history(agent_id, limit)

    def _match_routes(self, topic: str) -> list[str]:
        """
        根据 topic 匹配路由规则。

        使用 fnmatch 支持通配符：
            "results.*" 匹配 "results.auth", "results.db"
            "events.#" 匹配 "events.pipeline", "events.review"
            "*" 匹配所有

        Returns:
            匹配到的渠道名称列表（去重）
        """
        matched: list[str] = []
        for pattern, channels in self._routing_rules.items():
            if fnmatch.fnmatch(topic, pattern):
                for ch in channels:
                    if ch not in matched:
                        matched.append(ch)
        return matched

    def _dispatch_to_channels(
        self,
        topic: str,
        message: Any,
        channel_names: list[str],
    ) -> None:
        """
        将消息分发到指定渠道。

        每个渠道异步发送，失败不影响其他渠道。
        """
        for ch_name in channel_names:
            adapter = self._registry.get(ch_name)
            if adapter is None:
                logger.warning("[MultiChannelBus] Channel '%s' not registered", ch_name)
                continue

            envelope = MessageEnvelope(
                channel=ch_name,
                payload=self._message_to_payload(message, topic),
                metadata={"topic": topic},
            )

            try:
                # 创建异步任务发送
                asyncio.create_task(self._safe_send(adapter, envelope, ch_name))
            except RuntimeError:
                # 无事件循环时跳过（同步上下文）
                logger.debug("[MultiChannelBus] No event loop, skipping dispatch to %s", ch_name)

    async def _safe_send(
        self,
        adapter: ChannelAdapter,
        envelope: MessageEnvelope,
        ch_name: str,
    ) -> None:
        """安全发送，捕获异常避免影响其他渠道。"""
        try:
            success = await adapter.send(envelope)
            if not success:
                logger.warning("[MultiChannelBus] Failed to send to '%s'", ch_name)
        except Exception as e:
            logger.error("[MultiChannelBus] Error sending to '%s': %s", ch_name, e)

    @staticmethod
    def _message_to_payload(message: Any, topic: str) -> dict:
        """将 Message 对象或字典转换为渠道 payload。"""
        if isinstance(message, dict):
            return message
        if hasattr(message, "to_dict"):
            return message.to_dict()
        if hasattr(message, "payload"):
            return message.payload
        return {"text": str(message), "topic": topic}

    def add_route(self, pattern: str, channels: list[str]) -> None:
        """动态添加路由规则。"""
        self._routing_rules[pattern] = channels

    def remove_route(self, pattern: str) -> bool:
        """移除路由规则。返回是否成功。"""
        if pattern in self._routing_rules:
            del self._routing_rules[pattern]
            return True
        return False

    @property
    def routes(self) -> dict[str, list[str]]:
        """获取所有路由规则。"""
        return dict(self._routing_rules)
