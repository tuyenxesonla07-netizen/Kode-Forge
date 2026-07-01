# tools/messaging/channels/slack_adapter.py

"""
Slack 渠道适配器 — 通过 Slack SDK 发送/接收消息。

依赖: slack_sdk>=3.27 (可选)
安装: pip install "slack_sdk>=3.27"
"""

from __future__ import annotations

import logging
from typing import Optional

from tools.messaging.channel import ChannelAdapter, MessageEnvelope, ChannelStatus

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Slack 消息渠道适配器。"""

    channel_name = "slack"

    def __init__(self, token: str = "", channel_id: str = "", **kwargs) -> None:
        self._token = token
        self._channel_id = channel_id
        self._status = ChannelStatus.STOPPED
        self._client = None

    async def send(self, message: MessageEnvelope) -> bool:
        if not self._token:
            logger.warning("[Slack] No token configured, skipping send")
            return False
        try:
            from slack_sdk.web.async_client import AsyncWebClient
            client = AsyncWebClient(token=self._token)
            text = message.payload.get("text", str(message.payload))
            await client.chat_postMessage(channel=self._channel_id, text=text)
            return True
        except ImportError:
            logger.error("[Slack] slack_sdk not installed. pip install slack_sdk")
            return False
        except Exception as e:
            logger.error("[Slack] Send failed: %s", e)
            return False

    async def receive(self) -> Optional[MessageEnvelope]:
        # Slack 通过 webhook/事件推送接收，不在 adapter 中轮询
        return None

    async def start(self) -> None:
        self._status = ChannelStatus.RUNNING
        logger.info("[Slack] Adapter started (channel=%s)", self._channel_id)

    async def stop(self) -> None:
        self._status = ChannelStatus.STOPPED
        logger.info("[Slack] Adapter stopped")

    async def health_check(self) -> dict:
        if not self._token:
            return {"status": "error", "reason": "no_token"}
        try:
            from slack_sdk.web.async_client import AsyncWebClient
            client = AsyncWebClient(token=self._token)
            result = await client.auth_test()
            return {"status": "ok" if result["ok"] else "error", "bot": result.get("bot_id", "")}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
