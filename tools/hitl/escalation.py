# tools/hitl/escalation.py

"""
SLA 定时器与升级策略 — 异步超时驱动的自动升级。

当审批请求在 SLA 时间内未响应时，自动执行升级操作：
- 升级到下一审批层级
- 通知升级目标
- 标记原请求为 EXPIRED
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# 升级回调类型：接收 (approval_id, current_level) -> None
EscalationCallback = Callable[[str, int], Awaitable[None]]


@dataclass
class EscalationPolicy:
    """
    升级策略配置。

    Attributes:
        max_escalations: 最大升级次数（防止无限升级）
        escalation_delay: SLA 超时后的延迟时间（模拟 SLA 窗口）
        notify_on_escalate: 升级时是否通知
        auto_approve_on_final: 到达最终层级后是否自动批准
    """
    max_escalations: int = 3
    escalation_delay: timedelta = field(default_factory=lambda: timedelta(seconds=0))
    notify_on_escalate: bool = True
    auto_approve_on_final: bool = False

    def __post_init__(self) -> None:
        if self.max_escalations < 0:
            raise ValueError(f"max_escalations must be >= 0, got {self.max_escalations}")
        if self.escalation_delay.total_seconds() < 0:
            raise ValueError("escalation_delay must be non-negative")


class SLATimer:
    """
    SLA 定时器。

    在指定的 SLA 时间后触发超时回调。支持取消（审批完成时取消定时器）。

    用法:
        async def on_timeout(approval_id, level):
            print(f"SLA exceeded for {approval_id} at level {level}")

        timer = SLATimer("req-123", level=1, sla=timedelta(hours=24), on_timeout=on_timeout)
        timer.start()
        # ... later, if approved ...
        timer.cancel()
    """

    def __init__(
        self,
        approval_id: str,
        level: int,
        sla: timedelta,
        on_timeout: EscalationCallback,
    ) -> None:
        self.approval_id = approval_id
        self.level = level
        self.sla = sla
        self.on_timeout = on_timeout
        self._task: Optional[asyncio.Task] = None
        self._cancelled = False

    def start(self) -> None:
        """启动 SLA 定时器。"""
        if self._task is not None:
            raise RuntimeError(f"Timer for {self.approval_id} already started")
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())
        except RuntimeError:
            # 没有运行中的事件循环，创建独立循环（同步上下文）
            # timer 在同步测试中不会触发超时，但保持接口一致
            loop = asyncio.new_event_loop()
            self._task = loop.create_task(self._run())
            # 不启动 loop（同步上下文下由异步代码驱动）

    def cancel(self) -> None:
        """取消 SLA 定时器（审批完成时调用）。"""
        self._cancelled = True
        if self._task is not None:
            self._task.cancel()

    @property
    def is_running(self) -> bool:
        """定时器是否正在运行。"""
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        """内部运行：等待 SLA 时间后触发回调。"""
        try:
            await asyncio.sleep(self.sla.total_seconds())
            if not self._cancelled:
                logger.info(
                    "[SLA] Timeout for approval %s at level %d after %s",
                    self.approval_id, self.level, self.sla,
                )
                await self.on_timeout(self.approval_id, self.level)
        except asyncio.CancelledError:
            logger.debug("[SLA] Timer cancelled for %s", self.approval_id)
            raise


@dataclass
class EscalationState:
    """跟踪某个审批请求的升级状态。"""
    approval_id: str
    current_level: int = 1
    escalation_count: int = 0
    last_escalation_time: Optional[str] = None

    def can_escalate(self, policy: EscalationPolicy) -> bool:
        """检查是否还可以继续升级。"""
        return self.escalation_count < policy.max_escalations

    def record_escalation(self, target_level: int) -> None:
        """记录一次升级。"""
        from datetime import datetime, timezone
        self.escalation_count += 1
        self.current_level = target_level
        self.last_escalation_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
