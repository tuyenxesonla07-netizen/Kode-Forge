# tests/messaging/test_config.py

"""
Tests for tools.messaging.config — MessagingConfig, load/save YAML.
"""

import os
import tempfile
from pathlib import Path

import pytest

from tools.messaging.config import (
    MessagingConfig,
    load_messaging_config,
    save_messaging_config,
)


class TestMessagingConfig:

    def test_default(self):
        config = MessagingConfig()
        assert config.channels == {}
        assert config.routing == {}

    def test_from_dict(self):
        data = {
            "channels": {"slack": {"token": "xoxb-123"}},
            "routing": {"results.*": ["slack"]},
        }
        config = MessagingConfig.from_dict(data)
        assert "slack" in config.channels
        assert "results.*" in config.routing

    def test_to_dict(self):
        config = MessagingConfig(
            channels={"sse": {"max_queue_size": 500}},
            routing={"events.*": ["sse"]},
        )
        d = config.to_dict()
        assert d["channels"] == {"sse": {"max_queue_size": 500}}
        assert d["routing"] == {"events.*": ["sse"]}

    def test_from_dict_missing_keys(self):
        config = MessagingConfig.from_dict({})
        assert config.channels == {}
        assert config.routing == {}


class TestLoadMessagingConfig:

    def test_missing_file_returns_empty(self, tmp_path):
        config = load_messaging_config(str(tmp_path / "nonexistent.yaml"))
        assert config.channels == {}
        assert config.routing == {}

    def test_load_valid_yaml(self, tmp_path):
        yaml_content = """
channels:
  slack:
    token: xoxb-test
    channel_id: C12345
  sse:
    max_queue_size: 1000

routing:
  "results.*":
    - slack
    - sse
  "events.pipeline":
    - sse
"""
        path = tmp_path / "messaging.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        config = load_messaging_config(str(path))
        assert "slack" in config.channels
        assert config.channels["slack"]["token"] == "xoxb-test"
        assert "results.*" in config.routing
        assert "slack" in config.routing["results.*"]

    def test_load_yaml_in_markdown_block(self, tmp_path):
        """Markdown 代码块包裹的 YAML 也能正确解析。"""
        content = """# Messaging Config

```yaml
channels:
  telegram:
    token: abc123
routing:
  "escalation.*":
    - telegram
```
"""
        path = tmp_path / "config.md"
        path.write_text(content, encoding="utf-8")
        config = load_messaging_config(str(path))
        assert "telegram" in config.channels

    def test_invalid_yaml_returns_empty(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(":::invalid yaml content:::\n\t\t  \n  bad: [", encoding="utf-8")
        config = load_messaging_config(str(path))
        # 不应抛出异常
        assert isinstance(config, MessagingConfig)


class TestSaveMessagingConfig:

    def test_save_and_reload(self, tmp_path):
        config = MessagingConfig(
            channels={"sse": {"max_queue_size": 500}},
            routing={"events.*": ["sse"]},
        )
        path = tmp_path / "saved.yaml"
        save_messaging_config(config, str(path))

        assert path.exists()
        loaded = load_messaging_config(str(path))
        assert loaded.channels == config.channels
        assert loaded.routing == config.routing

    def test_save_creates_parent_dirs(self, tmp_path):
        config = MessagingConfig(channels={"a": {"k": "v"}}, routing={})
        path = tmp_path / "sub" / "dir" / "config.yaml"
        save_messaging_config(config, str(path))
        assert path.exists()
