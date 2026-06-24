# tools/messaging/__init__.py

"""
Message Bus — 事件驱动消息总线

  MessageBus     — 消息发布/订阅/历史记录
  Message        — 统一消息信封
  Topic          — Topic 定义和解析
"""

from tools.messaging.message_bus import MessageBus
from tools.messaging.message import Message, Topic

__all__ = ["MessageBus", "Message", "Topic"]
