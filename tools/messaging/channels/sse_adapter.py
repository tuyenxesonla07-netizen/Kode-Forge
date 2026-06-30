# tools/messaging/channels/sse_adapter.py

"""
SSE 渠道适配器 — 通过 Server-Sent Events 推送消息。

零新依赖 — 使用 asyncio.Queue 实现发布/订阅，
由 webhook_ingress.py 或 FastAPI SSE 端点消费。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from tools.messaging.channel import ChannelAdapter, MessageEnvelope, ChannelStatus

logger = logging.getLogger(__name__)


class SSEAdapter(ChannelAdapter):
    """
    SSE 消息渠道适配器。

    使用 asyncio.Queue 作为消息缓冲区，
    外部消费者（如 FastAPI SSE 端点）通过 receive() 获取消息。

    用法:
        adapter = SSEAdapter(max_queue_size=1000)
        await adapter.start()

        # 生产者
        await adapter.send(MessageEnvelope(channel="sse", payload={"event": "update"}))

        # 消费者（在 FastAPI 路由中）
        msg = await adapter.receive()
    """

    channel_name = "sse"

    def __init__(self, max_queue_size: int = 1000, **kwargs) -> None:
        self._queue: asyncio.Queue[MessageEnvelope] = asyncio.Queue(maxsize=max_queue_size)
        self._status = ChannelStatus.STOPPED

    async def send(self, message: MessageEnvelope) -> bool:
        try:
            self._queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            logger.warning("[SSE] Queue full, dropping message")
            return False

    async def receive(self) -> Optional[MessageEnvelope]:
        """非阻塞接收，无消息返回 None。"""
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def receive_wait(self, timeout: float = 30.0) -> Optional[MessageEnvelope]:
        """阻塞接收（带超时）。"""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def start(self) -> None:
        self._status = ChannelStatus.RUNNING
        logger.info("[SSE] Adapter started (queue_size=%d)", self._queue.maxsize)

    async def stop(self) -> None:
        self._status = ChannelStatus.STOPPED
        logger.info("[SSE] Adapter stopped")

    async def health_check(self) -> dict:
        return {
            "status": "ok",
            "queue_size": self._queue.qsize(),
            "max_queue_size": self._queue.maxsize,
            "channel": self.channel_name,
        }

    @property
    def queue_size(self) -> int:
        """当前队列大小。"""
        return self._queue.qsize()
