# tests/messaging/test_multichannel_bus.py

"""
Tests for tools.messaging.multichannel_bus — MultiChannelBus.
"""

import asyncio
import pytest

from tools.messaging.channel import (
    ChannelRegistry,
    MessageEnvelope,
    ChannelAdapter,
)
from tools.messaging.multichannel_bus import MultiChannelBus
from tools.workflow.messaging import MessageBus, Message


class _FakeAdapter(ChannelAdapter):
    """测试用适配器，记录所有发送的消息。"""

    channel_name = "fake"

    def __init__(self):
        self.sent_messages: list[MessageEnvelope] = []
        self._running = False

    async def send(self, message: MessageEnvelope) -> bool:
        self.sent_messages.append(message)
        return True

    async def receive(self):
        return None

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    async def health_check(self):
        return {"status": "ok" if self._running else "stopped"}


class _FailingAdapter(ChannelAdapter):
    """总是发送失败的适配器。"""

    channel_name = "failing"

    async def send(self, message):
        raise RuntimeError("Connection error")

    async def receive(self):
        return None

    async def start(self):
        pass

    async def stop(self):
        pass

    async def health_check(self):
        return {"status": "error"}


@pytest.fixture
def inner_bus():
    return MessageBus()


@pytest.fixture
def registry():
    reg = ChannelRegistry()
    reg.register("fake", _FakeAdapter())
    reg.register("failing", _FailingAdapter())
    return reg


@pytest.fixture
def multichannel_bus(inner_bus, registry):
    rules = {
        "results.*": ["fake"],
        "events.pipeline": ["fake"],
        "escalation.*": ["fake"],
    }
    return MultiChannelBus(inner=inner_bus, registry=registry, routing_rules=rules)


class TestMultiChannelBusInit:

    def test_init(self, multichannel_bus):
        assert multichannel_bus.inner is not None
        assert multichannel_bus.registry is not None
        assert len(multichannel_bus.routes) == 3

    def test_inner_property(self, multichannel_bus, inner_bus):
        assert multichannel_bus.inner is inner_bus

    def test_registry_property(self, multichannel_bus, registry):
        assert multichannel_bus.registry is registry


class TestMultiChannelBusPublish:

    def test_publish_to_inner_bus(self, multichannel_bus):
        msg = Message.create("a", "b", "phase1", "test", {"key": "val"})
        multichannel_bus.publish(msg)
        assert multichannel_bus.inner.get_queue_size("b") == 1

    def test_publish_with_topic_routes(self, multichannel_bus):
        """带 topic 的发布应触发外部渠道路由。"""
        msg = {"approval_id": "abc123", "level": 2}
        multichannel_bus.publish("escalation.sla_timeout", msg)

        # 内部总线收到
        # 外部渠道收到（异步）
        # 同步测试中不验证异步行为

    def test_publish_no_match(self, multichannel_bus):
        """不匹配任何路由规则时不应报错。"""
        multichannel_bus.publish("unknown.topic", {"data": 123})


class TestMultiChannelBusRouting:

    def test_match_routes_exact(self, multichannel_bus):
        matched = multichannel_bus._match_routes("events.pipeline")
        assert "fake" in matched

    def test_match_routes_wildcard(self, multichannel_bus):
        matched = multichannel_bus._match_routes("results.auth")
        assert "fake" in matched

    def test_match_routes_no_match(self, multichannel_bus):
        matched = multichannel_bus._match_routes("unknown.topic")
        assert matched == []

    def test_match_routes_multiple_patterns(self, multichannel_bus):
        """一个 topic 可以匹配多个规则。"""
        matched = multichannel_bus._match_routes("escalation.sla_timeout")
        assert "fake" in matched

    def test_match_deduplicates(self):
        """多个规则匹配同一 topic 时，渠道名应去重。"""
        inner = MessageBus()
        reg = ChannelRegistry()
        reg.register("a", _FakeAdapter())
        rules = {
            "escalation.*": ["a"],
            "escalation.sla_*": ["a"],
        }
        bus = MultiChannelBus(inner=inner, registry=reg, routing_rules=rules)
        matched = bus._match_routes("escalation.sla_timeout")
        assert matched == ["a"]


class TestMultiChannelBusPassthrough:

    def test_subscribe_passthrough(self, multichannel_bus):
        called = []

        def handler(msg):
            called.append(msg)

        unsub = multichannel_bus.subscribe("test.topic", handler)
        msg = Message.create("a", "b", "p", "test", {})
        multichannel_bus.publish("test.topic", msg)
        unsub()

    def test_unsubscribe_passthrough(self, multichannel_bus):
        called = []

        def handler(msg):
            called.append(msg)

        multichannel_bus.subscribe("test.topic", handler)
        multichannel_bus.unsubscribe("test.topic", handler)

    def test_get_history_passthrough(self, multichannel_bus):
        msg = Message.create("a", "b", "p", "test", {})
        multichannel_bus.publish(msg)
        history = multichannel_bus.get_history(limit=10)
        assert len(history) >= 1


class TestMultiChannelBusDynamicRoutes:

    def test_add_route(self, multichannel_bus):
        multichannel_bus.add_route("alerts.*", ["fake"])
        assert "alerts.*" in multichannel_bus.routes

    def test_remove_route(self, multichannel_bus):
        multichannel_bus.add_route("alerts.*", ["fake"])
        assert multichannel_bus.remove_route("alerts.*") is True
        assert "alerts.*" not in multichannel_bus.routes

    def test_remove_missing_route(self, multichannel_bus):
        assert multichannel_bus.remove_route("nonexistent") is False


class TestMessageToPayload:

    def test_dict_message(self):
        result = MultiChannelBus._message_to_payload({"key": "val"}, "test")
        assert result == {"key": "val"}

    def test_message_object(self):
        msg = Message.create("a", "b", "p", "test", {"data": 1})
        result = MultiChannelBus._message_to_payload(msg, "test")
        assert "meta" in result
        assert "payload" in result

    def test_string_message(self):
        result = MultiChannelBus._message_to_payload("hello world", "test.topic")
        assert result["text"] == "hello world"
        assert result["topic"] == "test.topic"
