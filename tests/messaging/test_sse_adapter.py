# tests/messaging/test_sse_adapter.py

"""
Tests for tools.messaging.channels.sse_adapter — SSEAdapter.

SSE 适配器零依赖，可以完整测试。
"""

import asyncio
import pytest

from tools.messaging.channels.sse_adapter import SSEAdapter
from tools.messaging.channel import MessageEnvelope, ChannelStatus


class TestSSEAdapterInit:

    def test_default_init(self):
        adapter = SSEAdapter()
        assert adapter.channel_name == "sse"
        assert adapter.queue_size == 0

    @pytest.mark.asyncio
    async def test_custom_queue_size(self):
        adapter = SSEAdapter(max_queue_size=500)
        health = await adapter.health_check()
        assert health["max_queue_size"] == 500


class TestSSEAdapterSendReceive:

    @pytest.mark.asyncio
    async def test_send_and_receive(self):
        adapter = SSEAdapter()
        await adapter.start()

        env = MessageEnvelope(channel="sse", payload={"event": "test", "data": "hello"})
        assert await adapter.send(env) is True

        received = await adapter.receive()
        assert received is not None
        assert received.payload["event"] == "test"
        assert received.payload["data"] == "hello"

        await adapter.stop()

    @pytest.mark.asyncio
    async def test_receive_empty(self):
        adapter = SSEAdapter()
        await adapter.start()
        result = await adapter.receive()
        assert result is None
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_receive_wait_timeout(self):
        adapter = SSEAdapter()
        await adapter.start()
        result = await adapter.receive_wait(timeout=0.05)
        assert result is None
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_queue_full(self):
        adapter = SSEAdapter(max_queue_size=1)
        await adapter.start()

        env1 = MessageEnvelope(channel="sse", payload={"n": 1})
        env2 = MessageEnvelope(channel="sse", payload={"n": 2})

        assert await adapter.send(env1) is True
        assert await adapter.send(env2) is False  # 队列满了

        await adapter.stop()


class TestSSEAdapterLifecycle:

    @pytest.mark.asyncio
    async def test_start_stop(self):
        adapter = SSEAdapter()
        await adapter.start()
        health = await adapter.health_check()
        assert health["status"] == "ok"
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with SSEAdapter() as adapter:
            health = await adapter.health_check()
            assert health["status"] == "ok"
            await adapter.send(MessageEnvelope(channel="sse", payload={}))
        # 退出后不再可用


class TestSSEAdapterHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_format(self):
        adapter = SSEAdapter(max_queue_size=200)
        health = await adapter.health_check()
        assert "status" in health
        assert "queue_size" in health
        assert "max_queue_size" in health
        assert "channel" in health
        assert health["channel"] == "sse"

    def test_queue_size_property(self):
        adapter = SSEAdapter()
        assert adapter.queue_size == 0
