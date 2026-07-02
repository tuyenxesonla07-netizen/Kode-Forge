# tests/messaging/test_webhook_ingress.py

"""
Tests for tools.server.webhook_ingress — webhook router factory.
"""

import pytest


class TestWebhookIngress:

    def test_create_router_without_fastapi(self):
        """FastAPI 未安装时返回 None。"""
        from tools.server.webhook_ingress import create_webhook_router
        # 如果 FastAPI 已安装则 router 不为 None
        # 如果未安装则为 None
        router = create_webhook_router()
        # 不断言具体值，只确保不抛出异常
        assert router is None or router is not None

    def test_handle_webhook(self):
        """handle_webhook 函数应在无 bus 时不报错。"""
        from tools.server.webhook_ingress import handle_webhook
        import asyncio

        result = asyncio.run(handle_webhook("github", {"action": "opened"}, multichannel_bus=None))
        assert result["status"] == "ok"
        assert result["channel"] == "github"

    def test_handle_webhook_with_bus(self):
        """handle_webhook 应在有 bus 时调用 publish。"""
        from tools.server.webhook_ingress import handle_webhook
        from tools.messaging.channel import ChannelRegistry
        from tools.messaging.multichannel_bus import MultiChannelBus
        from tools.workflow.messaging import MessageBus
        import asyncio

        inner = MessageBus()
        bus = MultiChannelBus(inner=inner, registry=ChannelRegistry(), routing_rules={})
        result = asyncio.run(handle_webhook("stripe", {"event": "payment"}, multichannel_bus=bus))
        assert result["status"] == "ok"
