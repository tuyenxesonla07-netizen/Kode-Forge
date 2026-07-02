# tools/messaging/config.py

"""
消息渠道 YAML 配置加载。

配置格式:
    channels:
      slack:
        token: xoxb-...
        channel_id: C12345
      telegram:
        token: ...
        chat_id: -100123
      webhook:
        url: https://example.com/webhook
      sse:
        max_queue_size: 1000

    routing:
      "results.*": ["slack", "webhook"]
      "events.pipeline": ["sse"]
      "escalation.*": ["slack", "email"]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class MessagingConfig:
    """消息渠道配置。"""
    channels: dict[str, dict[str, Any]] = field(default_factory=dict)
    routing: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "MessagingConfig":
        """从字典创建配置。"""
        return cls(
            channels=data.get("channels", {}),
            routing=data.get("routing", {}),
        )

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "channels": self.channels,
            "routing": self.routing,
        }

def load_messaging_config(path: str = "config/messaging.yaml") -> MessagingConfig:
    """
    从 YAML 文件加载消息渠道配置。

    如果文件不存在，返回空配置。
    如果 pyyaml 未安装，返回空配置并记录警告。

    Args:
        path: YAML 配置文件路径

    Returns:
        MessagingConfig 实例
    """
    config_path = Path(path)

    if not config_path.exists():
        logger.info("[MessagingConfig] Config file not found: %s, using empty config", path)
        return MessagingConfig()

    try:
        import yaml
    except ImportError:
        logger.warning(
            "[MessagingConfig] pyyaml not installed. "
            "Cannot load messaging config from %s. "
            "Install with: pip install pyyaml",
            path,
        )
        return MessagingConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 处理 Markdown 代码块包裹的情况
        lines = content.split("\n")
        yaml_lines = []
        in_yaml = False
        for line in lines:
            if line.strip().startswith("```yaml"):
                in_yaml = True
                continue
            if line.strip() == "```" and in_yaml:
                break
            if in_yaml:
                yaml_lines.append(line)

        yaml_content = "\n".join(yaml_lines) if yaml_lines else content
        data = yaml.safe_load(yaml_content) or {}
        return MessagingConfig.from_dict(data)

    except Exception as e:
        logger.error("[MessagingConfig] Failed to load config: %s", e)
        return MessagingConfig()

def save_messaging_config(config: MessagingConfig, path: str = "config/messaging.yaml") -> None:
    """
    保存配置到 YAML 文件。

    Args:
        config: 配置实例
        path: 目标文件路径
    """
    try:
        import yaml
    except ImportError:
        logger.error("[MessagingConfig] pyyaml not installed. Cannot save config.")
        return

    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False, allow_unicode=True)

    logger.info("[MessagingConfig] Config saved to %s", path)
