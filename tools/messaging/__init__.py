# tools/messaging/__init__.py

"""
OpenClaw 多渠道消息集成 — 可插拔的消息渠道适配器系统。

通过 YAML 配置路由管道事件到 Slack、Discord、Telegram、Email、Webhook、SSE 等渠道。
MessageBus API 保持不变，MultiChannelBus 通过组合包装。

用法:
    from tools.messaging import MultiChannelBus, ChannelRegistry
    from tools.messaging.config import load_messaging_config

    config = load_messaging_config("config/messaging.yaml")
    registry = ChannelRegistry()
    registry.register_from_config(config.channels)

    bus = MultiChannelBus(inner=MessageBus(), registry=registry, routing_rules=config.routing)
    bus.publish("escalation.sla_timeout", {"approval_id": "abc123", "level": 2})

    # 自动路由到 slack + email（按 YAML 配置）
"""

from tools.messaging.channel import (
    ChannelAdapter,
    MessageEnvelope,
    ChannelRegistry,
    ChannelStatus,
)
from tools.messaging.multichannel_bus import MultiChannelBus

__all__ = [
    "ChannelAdapter",
    "MessageEnvelope",
    "ChannelRegistry",
    "ChannelStatus",
    "MultiChannelBus",
]
