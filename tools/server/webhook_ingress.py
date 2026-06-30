# tools/server/webhook_ingress.py

"""
Webhook 入口路由 — FastAPI 路由工厂。

为每个已注册的 webhook 渠道提供 HTTP POST 入口：
    POST /api/v1/webhook/{channel_name} — 接收外部 webhook 事件

与 MessageBus 集成：收到的消息通过 MultiChannelBus.publish() 广播。

用法:
    from tools.server.webhook_ingress import create_webhook_router
    app.include_router(create_webhook_router(multichannel_bus))
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def create_webhook_router(
    multichannel_bus: Any = None,
    path_prefix: str = "/api/v1/webhook",
):
    """
    创建 FastAPI webhook 入口路由器。

    Args:
        multichannel_bus: MultiChannelBus 实例（可选）
        path_prefix: URL 前缀

    Returns:
        FastAPI Router 实例
    """
    try:
        from fastapi import APIRouter, Request, HTTPException, status
    except ImportError:
        logger.error("FastAPI not installed. Cannot create webhook router.")
        return None

    router = APIRouter(prefix=path_prefix, tags=["webhook"])

    @router.post("/{channel_name}")
    async def receive_webhook(channel_name: str, request: Request):
        """
        接收 webhook 事件。

        Args:
            channel_name: 渠道名称（如 "slack", "github", "stripe"）
            request: FastAPI Request
        """
        try:
            payload = await request.json()
        except Exception:
            payload = {"raw": await request.body()}

        logger.info(
            "[Webhook] Received event from '%s': %s",
            channel_name,
            str(payload)[:200],
        )

        # 发布到消息总线
        if multichannel_bus is not None:
            topic = f"webhook.{channel_name}"
            multichannel_bus.publish(topic, payload)

        return {"status": "ok", "channel": channel_name}

    @router.get("/health")
    async def webhook_health():
        """Webhook 健康检查端点。"""
        return {"status": "ok", "endpoints": [f"{path_prefix}/{{channel_name}}"]}

    return router


async def handle_webhook(
    channel_name: str,
    payload: dict,
    multichannel_bus: Any = None,
) -> dict:
    """
    处理 webhook 事件（非 FastAPI 上下文可用）。

    Args:
        channel_name: 来源渠道
        payload: 事件数据
        multichannel_bus: MultiChannelBus 实例

    Returns:
        处理结果
    """
    logger.info("[Webhook] Handling event from '%s'", channel_name)

    if multichannel_bus is not None:
        topic = f"webhook.{channel_name}"
        multichannel_bus.publish(topic, payload)

    return {"status": "ok", "channel": channel_name}
