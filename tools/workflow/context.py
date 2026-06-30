# tools/workflow/context.py

"""
工作流上下文窗口与生命周期钩子。

从 engine.py 中提取的辅助模块，使主引擎文件更聚焦于执行逻辑。

组件:
    ContextItem      — 单个上下文条目（role/content/priority）
    ContextWindow    — 动态上下文窗口（优先级淘汰、token 预算）
    LifecycleEvent   — 生命周期事件数据
    LifecycleHooks   — 钩子注册表（on_start/on_step/on_complete/on_error）
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ContextWindow + ContextItem
# ---------------------------------------------------------------------------

@dataclass
class ContextItem:
    """单个上下文条目"""
    role: str            # "system" | "user" | "assistant" | "tool"
    content: str
    priority: int = 5    # 1-10, 越高越重要
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tool_name: str = ""
    metadata: dict = field(default_factory=dict)


class ContextWindow:
    """
    动态上下文窗口 — 管理 LLM 对话上下文。

    支持优先级淘汰、角色过滤、token 预算控制。
    """

    def __init__(self, max_items: int = 50, max_tokens: int = 8000):
        self._items: List[ContextItem] = []
        self.max_items = max_items
        self.max_tokens = max_tokens

    def add(self, item: ContextItem) -> None:
        """添加上下文条目"""
        self._items.append(item)
        self._evict()

    def add_system(self, content: str, priority: int = 5) -> None:
        self.add(ContextItem(role="system", content=content, priority=priority))

    def add_user_message(self, content: str, priority: int = 5) -> None:
        self.add(ContextItem(role="user", content=content, priority=priority))

    def add_assistant(self, content: str, priority: int = 5) -> None:
        self.add(ContextItem(role="assistant", content=content, priority=priority))

    def add_tool_result(self, content: str, priority: int = 4,
                        tool_name: str = "") -> None:
        self.add(ContextItem(
            role="tool", content=content, priority=priority, tool_name=tool_name,
        ))

    def build(self) -> str:
        """构建上下文字符串（按优先级排序）"""
        sorted_items = sorted(self._items, key=lambda x: x.priority, reverse=True)
        parts = []
        for item in sorted_items:
            if item.role == "system":
                parts.append(f"[SYSTEM] {item.content}")
            elif item.role == "user":
                parts.append(f"[USER] {item.content}")
            elif item.role == "assistant":
                parts.append(f"[ASSISTANT] {item.content}")
            elif item.role == "tool":
                name = item.tool_name or "tool"
                parts.append(f"[{name.upper()}] {item.content}")
        return "\n\n".join(parts)

    def get_items(self, role: str = None) -> List[ContextItem]:
        """获取上下文条目（可按角色过滤）"""
        if role:
            return [i for i in self._items if i.role == role]
        return list(self._items)

    def clear(self) -> None:
        """清空上下文"""
        self._items.clear()

    def _evict(self) -> None:
        """按优先级淘汰超出限制的条目"""
        while len(self._items) > self.max_items:
            # 淘汰最低优先级的条目
            min_idx = min(range(len(self._items)), key=lambda i: self._items[i].priority)
            self._items.pop(min_idx)

    def __len__(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------
# LifecycleEvent / LifecycleHooks / LifecycleHandler
# ---------------------------------------------------------------------------

@dataclass
class LifecycleEvent:
    """生命周期事件"""
    hook: str
    run_id: str = ""
    node_id: str = ""
    data: dict = field(default_factory=dict)


LifecycleHandler = Callable[[LifecycleEvent], Any]


class LifecycleHooks:
    """
    工作流生命周期钩子注册表。

    支持的钩子:
    - on_start:    工作流开始执行
    - on_step:     每个节点执行完成
    - on_complete: 工作流执行成功
    - on_error:    工作流执行失败
    """

    HOOKS = ["on_start", "on_step", "on_complete", "on_error"]

    def __init__(self):
        self._handlers: Dict[str, List[LifecycleHandler]] = {
            hook: [] for hook in self.HOOKS
        }

    def register(self, hook: str, handler: LifecycleHandler) -> None:
        """注册一个钩子 handler"""
        if hook not in self._handlers:
            raise ValueError(f"Unknown hook: {hook}. Valid: {list(self._handlers)}")
        self._handlers[hook].append(handler)

    def on(self, hook: str):
        """装饰器语法注册钩子: @hooks.on('on_step')"""
        def decorator(fn: LifecycleHandler) -> LifecycleHandler:
            self.register(hook, fn)
            return fn
        return decorator

    def unregister(self, hook: str, handler: LifecycleHandler) -> bool:
        """注销一个钩子 handler"""
        if hook in self._handlers and handler in self._handlers[hook]:
            self._handlers[hook].remove(handler)
            return True
        return False

    def emit(self, hook: str, run_id: str = "", node_id: str = "",
             data: dict = None) -> list[Any]:
        """触发钩子，按顺序执行所有 handler"""
        event = LifecycleEvent(
            hook=hook,
            run_id=run_id,
            node_id=node_id,
            data=data or {},
        )

        results = []
        for handler in self._handlers.get(hook, []):
            try:
                result = handler(event)
                results.append(result)
            except Exception as e:
                logger.error("[Lifecycle] Handler %s failed for %s: %s",
                             handler.__name__, hook, e)
                results.append(None)

        return results

    def emit_sync(self, hook: str, **kwargs) -> None:
        """触发钩子（不关心返回值）"""
        self.emit(hook, **kwargs)

    def clear(self, hook: str = None) -> None:
        """清空指定钩子或全部"""
        if hook:
            self._handlers[hook] = []
        else:
            for h in self._handlers:
                self._handlers[h] = []

    def handler_count(self, hook: str = None) -> int:
        """返回指定钩子的 handler 数量"""
        if hook:
            return len(self._handlers.get(hook, []))
        return sum(len(v) for v in self._handlers.values())
