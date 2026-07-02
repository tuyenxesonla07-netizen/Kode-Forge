# tools/messaging/channels/discord_adapter.py

"""
Discord 渠道适配器 — 通过 discord.py 发送/接收消息。

依赖: discord.py>=2.3 (可选)
安装: pip install "discord.py>=2.3"
"""

from __future__ import annotations

import logging
from typing import Optional

from tools.messaging.channel import ChannelAdapter, MessageEnvelope, ChannelStatus

logger = logging.getLogger(__name__)


class DiscordAdapter(ChannelAdapter):
    """Discord 消息渠道适配器。"""

    channel_name = "discord"

    def __init__(self, token: str = "", channel_id: str = "", **kwargs) -> None:
        self._token = token
        self._channel_id = channel_id
        self._status = ChannelStatus.STOPPED

    async def send(self, message: MessageEnvelope) -> bool:
        if not self._token:
            logger.warning("[Discord] No token configured, skipping send")
            return False
        try:
            # discord.py 通过 bot client 发送，这里简化为 HTTP API
            import aiohttp
            text = message.payload.get("text", str(message.payload))
            headers = {"Authorization": f"Bot {self._token}", "Content-Type": "application/json"}
            url = f"https://discord.com/api/v10/channels/{self._channel_id}/messages"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"content": text}, headers=headers) as resp:
                    return resp.status == 200
        except ImportError:
            logger.error("[Discord] discord.py or aiohttp not installed")
            return False
        except Exception as e:
            logger.error("[Discord] Send failed: %s", e)
            return False

    async def receive(self) -> Optional[MessageEnvelope]:
        return None

    async def start(self) -> None:
        self._status = ChannelStatus.RUNNING
        logger.info("[Discord] Adapter started (channel=%s)", self._channel_id)

    async def stop(self) -> None:
        self._status = ChannelStatus.STOPPED
        logger.info("[Discord] Adapter stopped")

    async def health_check(self) -> dict:
        if not self._token:
            return {"status": "error", "reason": "no_token"}
        try:
            import aiohttp
            headers = {"Authorization": f"Bot {self._token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get("https://discord.com/api/v10/users/@me", headers=headers) as resp:
                    return {"status": "ok" if resp.status == 200 else "error", "code": resp.status}
        except ImportError:
            return {"status": "error", "reason": "aiohttp_not_installed"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
