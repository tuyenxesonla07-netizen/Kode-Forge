# tools/messaging/channels/email_adapter.py

"""
Email 渠道适配器 — 通过 aiosmtplib 发送邮件。

依赖: aiosmtplib>=3.0 (可选)
安装: pip install "aiosmtplib>=3.0"
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from tools.messaging.channel import ChannelAdapter, MessageEnvelope, ChannelStatus

logger = logging.getLogger(__name__)


class EmailAdapter(ChannelAdapter):
    """Email 消息渠道适配器。"""

    channel_name = "email"

    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        use_tls: bool = True,
        **kwargs,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._use_tls = use_tls
        self._status = ChannelStatus.STOPPED

    async def send(self, message: MessageEnvelope) -> bool:
        try:
            from aiosmtplib import SMTP
            to_addr = message.reply_to or message.payload.get("to", "")
            if not to_addr:
                logger.warning("[Email] No recipient specified")
                return False

            subject = message.payload.get("subject", "CC Notification")
            body = message.payload.get("body", message.payload.get("text", str(message.payload)))

            from email.message import EmailMessage
            msg = EmailMessage()
            msg["From"] = self._from_addr
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.set_content(body)

            async with SMTP(hostname=self._smtp_host, port=self._smtp_port, use_tls=self._use_tls) as smtp:
                if self._username:
                    await smtp.login(self._username, self._password)
                await smtp.send_message(msg)
            return True
        except ImportError:
            logger.error("[Email] aiosmtplib not installed. pip install aiosmtplib")
            return False
        except Exception as e:
            logger.error("[Email] Send failed: %s", e)
            return False

    async def receive(self) -> Optional[MessageEnvelope]:
        # Email 接收需要 IMAP/POP3，不在本适配器范围内
        return None

    async def start(self) -> None:
        self._status = ChannelStatus.RUNNING
        logger.info("[Email] Adapter started (%s:%d)", self._smtp_host, self._smtp_port)

    async def stop(self) -> None:
        self._status = ChannelStatus.STOPPED
        logger.info("[Email] Adapter stopped")

    async def health_check(self) -> dict:
        try:
            from aiosmtplib import SMTP
            async with SMTP(hostname=self._smtp_host, port=self._smtp_port) as smtp:
                await smtp.connect()
                if self._use_tls:
                    await smtp.starttls()
                return {"status": "ok", "host": self._smtp_host, "port": self._smtp_port}
        except ImportError:
            return {"status": "error", "reason": "aiosmtplib_not_installed"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
