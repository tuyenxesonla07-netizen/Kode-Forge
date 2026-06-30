# tools/messaging/channels/telegram_adapter.py

"""
Telegram 渠道适配器 — 通过 python-telegram-bot 或 HTTP API 发送消息。

依赖: python-telegram-bot>=21 (可选)
安装: pip install "python-telegram-bot>=21"
"""

from __future__ import annotations

import logging
from typing import Optional

from tools.messaging.channel import ChannelAdapter, MessageEnvelope, ChannelStatus

logger = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """Telegram 消息渠道适配器。"""

    channel_name = "telegram"

    def __init__(self, token: str = "", chat_id: str = "", **kwargs) -> None:
        self._token = token
        self._chat_id = chat_id
        self._status = ChannelStatus.STOPPED

    async def send(self, message: MessageEnvelope) -> bool:
        if not self._token:
            logger.warning("[Telegram] No token configured, skipping send")
            return False
        try:
            text = message.payload.get("text", str(message.payload))
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            payload = {"chat_id": self._chat_id, "text": text}
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    return resp.status == 200
        except ImportError:
            logger.error("[Telegram] aiohttp not installed. pip install aiohttp")
            return False
        except Exception as e:
            logger.error("[Telegram] Send failed: %s", e)
            return False

    async def receive(self) -> Optional[MessageEnvelope]:
        # Telegram webhook 通过 HTTP 推送，不在 adapter 中轮询
        return None

    async def start(self) -> None:
        self._status = ChannelStatus.RUNNING
        logger.info("[Telegram] Adapter started (chat=%s)", self._chat_id)

    async def stop(self) -> None:
        self._status = ChannelStatus.STOPPED
        logger.info("[Telegram] Adapter stopped")

    async def health_check(self) -> dict:
        if not self._token:
            return {"status": "error", "reason": "no_token"}
        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{self._token}/getMe"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json() if resp.status == 200 else {}
                    return {"status": "ok" if data.get("ok") else "error", "bot": data.get("result", {}).get("username", "")}
        except ImportError:
            return {"status": "error", "reason": "aiohttp_not_installed"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
