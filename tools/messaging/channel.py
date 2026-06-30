# tools/messaging/channel.py

"""
渠道适配器抽象基类 + 消息信封 + 渠道注册表。

所有渠道适配器继承 ChannelAdapter ABC，实现 send/receive/start/stop/health_check。
可选依赖通过 lazy import 实现；缺少 SDK 时 ImportError 附带安装提示。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ChannelStatus(str, Enum):
    """渠道状态。"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass(frozen=True)
class MessageEnvelope:
    """
    统一消息信封 — 跨渠道传输的标准格式。

    Attributes:
        channel: 渠道名称（如 "slack", "telegram"）
        payload: 消息内容字典
        reply_to: 回复目标（可选，渠道相关）
        metadata: 额外元数据（headers, retry_count 等）
    """
    channel: str
    payload: dict
    reply_to: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class ChannelAdapter(ABC):
    """
    渠道适配器抽象基类。

    每个适配器负责一个消息渠道的双向通信。
    所有可选依赖使用 lazy import。

    用法:
        class MyChannel(ChannelAdapter):
            channel_name = "my_channel"

            async def send(self, message: MessageEnvelope) -> bool: ...
            async def receive(self) -> MessageEnvelope | None: ...
            async def start(self) -> None: ...
            async def stop(self) -> None: ...
            async def health_check(self) -> dict: ...
    """

    channel_name: str = "abstract"

    @abstractmethod
    async def send(self, message: MessageEnvelope) -> bool:
        """
        发送消息到该渠道。

        Args:
            message: 消息信封

        Returns:
            是否发送成功
        """
        ...

    @abstractmethod
    async def receive(self) -> Optional[MessageEnvelope]:
        """
        从渠道接收一条消息（非阻塞）。

        Returns:
            消息Envelope，或 None（无新消息）
        """
        ...

    @abstractmethod
    async def start(self) -> None:
        """启动渠道连接（建立 WebSocket/HTTP 监听等）。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止渠道连接。"""
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        """
        健康检查。

        Returns:
            健康状态字典，至少包含 {"status": "ok"|"error", ...}
        """
        ...

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


class ChannelRegistry:
    """
    渠道注册表 — 管理所有已注册的渠道适配器。

    支持从 YAML 配置批量注册，支持按名称查找。

    用法:
        registry = ChannelRegistry()
        registry.register("slack", SlackAdapter(token="xoxb-...", channel_id="C123"))
        registry.register("telegram", TelegramAdapter(token="...", chat_id="-100"))

        adapter = registry.get("slack")
        all_adapters = registry.list_adapters()
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, name: str, adapter: ChannelAdapter) -> None:
        """注册一个渠道适配器。"""
        if name in self._adapters:
            logger.warning("[ChannelRegistry] Overwriting adapter for '%s'", name)
        self._adapters[name] = adapter

    def unregister(self, name: str) -> bool:
        """注销渠道适配器。返回是否成功。"""
        if name in self._adapters:
            del self._adapters[name]
            return True
        return False

    def get(self, name: str) -> Optional[ChannelAdapter]:
        """获取指定名称的适配器。"""
        return self._adapters.get(name)

    def list_adapters(self) -> list[tuple[str, ChannelAdapter]]:
        """列出所有已注册的适配器。"""
        return list(self._adapters.items())

    def list_names(self) -> list[str]:
        """列出所有已注册的渠道名称。"""
        return list(self._adapters.keys())

    def register_from_config(self, channels_config: dict) -> None:
        """
        从配置字典批量注册适配器。

        Args:
            channels_config: 来自 YAML 的 channels 部分
                格式: {"slack": {"token": "...", "channel_id": "..."}, ...}
        """
        for channel_name, channel_conf in channels_config.items():
            adapter = self._create_adapter(channel_name, channel_conf)
            if adapter is not None:
                self.register(channel_name, adapter)

    @staticmethod
    def _create_adapter(name: str, config: dict) -> Optional[ChannelAdapter]:
        """
        根据渠道名称和配置创建适配器实例。

        使用 lazy import 加载各渠道 SDK。
        """
        try:
            if name == "slack":
                from tools.messaging.channels.slack_adapter import SlackAdapter
                return SlackAdapter(**config)
            elif name == "discord":
                from tools.messaging.channels.discord_adapter import DiscordAdapter
                return DiscordAdapter(**config)
            elif name == "telegram":
                from tools.messaging.channels.telegram_adapter import TelegramAdapter
                return TelegramAdapter(**config)
            elif name == "email":
                from tools.messaging.channels.email_adapter import EmailAdapter
                return EmailAdapter(**config)
            elif name == "webhook":
                from tools.messaging.channels.webhook_adapter import WebhookAdapter
                return WebhookAdapter(**config)
            elif name == "sse":
                from tools.messaging.channels.sse_adapter import SSEAdapter
                return SSEAdapter(**config)
            else:
                logger.warning("[ChannelRegistry] Unknown channel: %s", name)
                return None
        except ImportError as e:
            logger.error(
                "[ChannelRegistry] Cannot create '%s' adapter: %s. "
                "Install the required SDK.",
                name, e,
            )
            return None

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters
