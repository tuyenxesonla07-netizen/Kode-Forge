# ADR-0006: 多渠道消息适配器 — Lazy Import 模式

## 状态
Accepted (V0.4.0 F4)

## 背景

企业场景需要将流水线事件推送到 Slack、Discord、Telegram、Email、Webhook、SSE 等渠道。每个渠道依赖不同的 SDK（slack_sdk、aiohttp、aiosmtplib 等），如果全部硬依赖会导致：
- 安装包体积膨胀
- 不同平台的依赖冲突
- 用户只需 1-2 个渠道却被迫安装全部 SDK

## 决策

采用 **Lazy Import + ABC 适配器** 模式：

### ChannelAdapter 抽象基类

```python
class ChannelAdapter(ABC):
    channel_name: str

    async def send(self, message: MessageEnvelope) -> bool: ...
    async def receive(self) -> MessageEnvelope | None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health_check(self) -> dict: ...
```

### Lazy Import 模式（每个 adapter 内部）

```python
class SlackAdapter(ChannelAdapter):
    async def send(self, message):
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            raise ImportError(
                "slack_sdk is required for Slack channel. "
                "Install with: pip install 'cc-project[openclaw-slack]'"
            )
        ...
```

### 可选 extras 分组

```toml
[project.optional-dependencies]
openclaw-slack = ["slack_sdk>=3.27"]
openclaw-discord = ["discord.py>=2.3"]
openclaw-telegram = ["python-telegram-bot>=21"]
openclaw-email = ["aiosmtplib>=3.0"]
openclaw-webhook = ["aiohttp>=3.9"]
openclaw-sse = []  # 零依赖
openclaw-all = [...]  # 以上全部
```

### 路由规则

YAML 配置，fnmatch 通配符匹配 topic：

```yaml
routing:
  "results.*": ["slack", "webhook"]
  "escalation.*": ["slack", "email"]
  "events.pipeline": ["sse"]
```

### SSE — 零依赖渠道

SSE adapter 使用 `asyncio.Queue` 作为内部缓冲，无需任何外部 SDK，是 GUI 实时推送的首选渠道。

## 后果

**优点**：
- 用户按需安装，最小依赖（SSE 零依赖）
- 新增渠道只需实现 `ChannelAdapter` + 一个 YAML 配置条目
- 渠道故障不影响核心流水线（try/except 隔离）

**缺点**：
- Lazy import 导致 ImportError 延迟到首次使用时（而非安装时）
- 每个 adapter 需要独立测试 mock SDK 缺失场景
- 异步 dispatch（`asyncio.create_task`）在同步上下文中可能丢失消息

## 相关

- ADR-0002: Entry Points 插件发现（类似的懒加载思想）
- ADR-0003: 审批升级事件 → 消息总线的集成点
- `tools/messaging/` — 多渠道消息实现
