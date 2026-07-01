# tools/messaging/channels/webhook_adapter.py

"""
Webhook 渠道适配器 — 通过 HTTP POST 发送消息到指定 URL。

依赖: aiohttp>=3.9 (可选)
安装: pip install "aiohttp>=3.9"
"""

from __future__ import annotations

import logging
from typing import Optional

from tools.messaging.channel import ChannelAdapter, MessageEnvelope, ChannelStatus

logger = logging.getLogger(__name__)


class WebhookAdapter(ChannelAdapter):
    """Webhook 消息渠道适配器 — 发送 HTTP POST 到指定 URL。"""

    channel_name = "webhook"

    def __init__(self, url: str = "", headers: dict | None = None, timeout: int = 30, **kwargs) -> None:
        self._url = url
        self._headers = headers or {"Content-Type": "application/json"}
        self._timeout = timeout
        self._status = ChannelStatus.STOPPED

    async def send(self, message: MessageEnvelope) -> bool:
        if not self._url:
            logger.warning("[Webhook] No URL configured, skipping send")
            return False
        try:
            import aiohttp
            payload = message.payload
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._url,
                    json=payload,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=self._timeout),
                ) as resp:
                    return 200 <= resp.status < 300
        except ImportError:
            logger.error("[Webhook] aiohttp not installed. pip install aiohttp")
            return False
        except Exception as e:
            logger.error("[Webhook] Send failed: %s", e)
            return False

    async def receive(self) -> Optional[MessageEnvelope]:
        # Webhook 接收通过 HTTP 入口（webhook_ingress.py），不在 adapter 中轮询
        return None

    async def start(self) -> None:
        self._status = ChannelStatus.RUNNING
        logger.info("[Webhook] Adapter started (url=%s)", self._url[:80])

    async def stop(self) -> None:
        self._status = ChannelStatus.STOPPED
        logger.info("[Webhook] Adapter stopped")

    async def health_check(self) -> dict:
        if not self._url:
            return {"status": "error", "reason": "no_url"}
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(self._url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return {"status": "ok" if resp.status < 500 else "error", "code": resp.status}
        except ImportError:
            return {"status": "error", "reason": "aiohttp_not_installed"}
        except Exception as e:
            # health_check GET 失败不一定意味着发送失败
            return {"status": "degraded", "reason": str(e)[:100]}
