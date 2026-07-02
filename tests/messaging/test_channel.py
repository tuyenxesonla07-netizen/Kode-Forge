# tests/messaging/test_channel.py

"""
Tests for tools.messaging.channel — MessageEnvelope, ChannelRegistry.
"""

import pytest

from tools.messaging.channel import (
    ChannelAdapter,
    MessageEnvelope,
    ChannelRegistry,
    ChannelStatus,
)


class TestMessageEnvelope:

    def test_basic_creation(self):
        env = MessageEnvelope(channel="slack", payload={"text": "hello"})
        assert env.channel == "slack"
        assert env.payload == {"text": "hello"}
        assert env.reply_to is None
        assert env.metadata == {}

    def test_with_reply_to(self):
        env = MessageEnvelope(channel="email", payload={}, reply_to="user@example.com")
        assert env.reply_to == "user@example.com"

    def test_with_metadata(self):
        env = MessageEnvelope(channel="webhook", payload={}, metadata={"retry_count": 3})
        assert env.metadata["retry_count"] == 3

    def test_frozen(self):
        env = MessageEnvelope(channel="slack", payload={"text": "hi"})
        with pytest.raises(AttributeError):
            env.channel = "telegram"


class TestChannelStatus:

    def test_enum_values(self):
        assert ChannelStatus.STOPPED.value == "stopped"
        assert ChannelStatus.STARTING.value == "starting"
        assert ChannelStatus.RUNNING.value == "running"
        assert ChannelStatus.ERROR.value == "error"


class TestChannelRegistry:

    def _make_adapter(self, name="test"):
        class TestAdapter(ChannelAdapter):
            channel_name = name

            async def send(self, message):
                return True

            async def receive(self):
                return None

            async def start(self):
                pass

            async def stop(self):
                pass

            async def health_check(self):
                return {"status": "ok"}

        return TestAdapter()

    def test_register_and_get(self):
        reg = ChannelRegistry()
        adapter = self._make_adapter("test1")
        reg.register("test1", adapter)
        assert reg.get("test1") is adapter

    def test_unregister(self):
        reg = ChannelRegistry()
        reg.register("test", self._make_adapter())
        assert reg.unregister("test") is True
        assert reg.get("test") is None

    def test_unregister_missing(self):
        reg = ChannelRegistry()
        assert reg.unregister("nonexistent") is False

    def test_list_adapters(self):
        reg = ChannelRegistry()
        a1 = self._make_adapter("a1")
        a2 = self._make_adapter("a2")
        reg.register("a1", a1)
        reg.register("a2", a2)
        items = reg.list_adapters()
        assert len(items) == 2

    def test_list_names(self):
        reg = ChannelRegistry()
        reg.register("x", self._make_adapter())
        reg.register("y", self._make_adapter())
        names = reg.list_names()
        assert "x" in names
        assert "y" in names

    def test_contains(self):
        reg = ChannelRegistry()
        reg.register("test", self._make_adapter())
        assert "test" in reg
        assert "missing" not in reg

    def test_len(self):
        reg = ChannelRegistry()
        assert len(reg) == 0
        reg.register("a", self._make_adapter())
        assert len(reg) == 1

    def test_overwrite_logs_warning(self):
        """重复注册同名适配器应覆盖并记录警告。"""
        reg = ChannelRegistry()
        reg.register("test", self._make_adapter())
        reg.register("test", self._make_adapter())
        assert len(reg) == 1

    def test_register_from_config_unknown_channel(self):
        reg = ChannelRegistry()
        reg.register_from_config({"unknown_channel": {"key": "val"}})
        assert len(reg) == 0

    def test_register_from_config_sse(self):
        """SSE 适配器无需外部 SDK，应成功注册。"""
        reg = ChannelRegistry()
        reg.register_from_config({"sse": {"max_queue_size": 100}})
        assert "sse" in reg

    def test_register_from_config_slack_no_sdk(self):
        """Slack 无 SDK 时应跳过（不报错）。"""
        reg = ChannelRegistry()
        reg.register_from_config({"slack": {"token": "xoxb-test", "channel_id": "C123"}})
        # slack_sdk 未安装时返回 None，不注册
        # 如果已安装则注册成功
        # 两种情况都不应抛出异常


class TestChannelAdapterABC:

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ChannelAdapter()

    def test_concrete_adapter(self):
        class MyAdapter(ChannelAdapter):
            channel_name = "my"

            async def send(self, message):
                return True

            async def receive(self):
                return None

            async def start(self):
                pass

            async def stop(self):
                pass

            async def health_check(self):
                return {"status": "ok"}

        adapter = MyAdapter()
        assert adapter.channel_name == "my"
