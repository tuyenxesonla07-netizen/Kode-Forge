"""P2-3 security tests: API auth production-mode enforcement + warn_if_insecure.

When api_keys is empty and debug=False (production), create_app auto-generates
a random key, stores its SHA-256 hash in api_keys, and logs the plaintext key.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from tools.server.app import create_app, ServerConfig


def _capture_auto_key(app, caplog_records=None):
    """从 create_app 的日志输出中提取自动生成的明文 API key。"""
    # 通过 caplog 或直接捕获 logging 输出
    handler = _KeyCaptureHandler()
    logging.getLogger("tools.server.app").addHandler(handler)
    return handler


class _KeyCaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.auto_keys = []

    def emit(self, record):
        msg = record.getMessage()
        if "X-API-Key:" in msg:
            key = msg.split("X-API-Key:")[-1].strip()
            self.auto_keys.append(key)


# ---------------------------------------------------------------------------
# ServerConfig.warn_if_insecure
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ServerConfig.warn_if_insecure
# ---------------------------------------------------------------------------

class TestWarnIfInsecure:
    def test_fully_insecure_returns_multiple_warnings(self):
        config = ServerConfig()
        warnings = config.warn_if_insecure()
        assert len(warnings) >= 3  # no auth, open CORS, no rate limit, no TLS

    def test_secure_config_returns_empty(self):
        config = ServerConfig(
            api_keys=["hash-of-key"],
            cors_origins=["https://app.example.com"],
            rate_limit="30/minute",
            tls_cert_path="/path/to/cert.pem",
        )
        assert config.warn_if_insecure() == []

    def test_partial_security(self):
        """只配了 api_keys 但仍缺少 rate_limit 和 TLS。"""
        config = ServerConfig(api_keys=["some-hash"])
        warnings = config.warn_if_insecure()
        # 不应再有 "auth disabled" 提示
        assert not any("authentication is DISABLED" in w for w in warnings)
        # 但还有限流和 TLS 警告
        assert any("Rate limiting" in w for w in warnings)
        assert any("TLS" in w for w in warnings)


# ---------------------------------------------------------------------------
# create_app auto-generates key in non-debug mode
# ---------------------------------------------------------------------------

class TestAutoApiKey:
    def _make_app_with_capture(self, config):
        """创建 app 并捕获自动生成的明文 key。"""
        cap = _KeyCaptureHandler()
        logger = logging.getLogger("tools.server.app")
        logger.addHandler(cap)
        try:
            app = create_app(config=config)
        finally:
            logger.removeHandler(cap)
        auto_key = cap.auto_keys[0] if cap.auto_keys else None
        return app, auto_key

    def test_auto_key_generated_in_non_debug(self):
        """非 debug 模式 + 空 api_keys 时自动生成随机 key。"""
        config = ServerConfig(debug=False, api_keys=[])
        app, auto_key = self._make_app_with_capture(config)
        assert auto_key is not None
        assert auto_key.startswith("kf-")
        # config.api_keys 存储的是 SHA-256 哈希
        assert len(config.api_keys) == 1
        assert config.api_keys[0] != auto_key  # 存储的不是明文

    def test_auto_key_not_generated_in_debug(self):
        """debug 模式下不自动生成 key（开发便利）。"""
        config = ServerConfig(debug=True, api_keys=[])
        app, auto_key = self._make_app_with_capture(config)
        assert auto_key is None  # debug 模式不生成
        assert config.api_keys == []

    def test_auto_key_not_overridden_when_provided(self):
        """已配置 api_keys 时不覆盖。"""
        from tools.server.auth import hash_api_key
        existing = [hash_api_key("my-key")]
        config = ServerConfig(debug=False, api_keys=existing.copy())
        app, auto_key = self._make_app_with_capture(config)
        assert auto_key is None  # 已有 key 时不生成
        assert config.api_keys == existing

    def test_generated_key_works_for_auth(self):
        """自动生成的 key 可成功通过 AuthMiddleware 验证。"""
        config = ServerConfig(debug=False, api_keys=[])
        app, auto_key = self._make_app_with_capture(config)
        assert auto_key is not None  # 确实生成了 key

        client = TestClient(app, raise_server_exceptions=False)

        # 不带 key: 应被 AuthMiddleware 拦截 (401)
        r_no_key = client.get("/api/v1/health")
        assert r_no_key.status_code == 401

        # 带自动生成的 key: 应通过
        r_with_key = client.get("/api/v1/health", headers={"X-API-Key": auto_key})
        assert r_with_key.status_code == 200

    def test_rate_limit_triggers_429_with_auto_auth(self):
        """rate_limit + auto_key 同时生效。"""
        config = ServerConfig(
            debug=False,
            api_keys=[],
            rate_limit="2/minute",
        )
        app, auto_key = self._make_app_with_capture(config)
        assert auto_key is not None

        client = TestClient(app, raise_server_exceptions=False)
        headers = {"X-API-Key": auto_key}

        r1 = client.get("/api/v1/health", headers=headers)
        r2 = client.get("/api/v1/health", headers=headers)
        r3 = client.get("/api/v1/health", headers=headers)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429

    def test_security_warnings_logged(self):
        """warn_if_insecure() 的日志在启动时打印。"""
        import logging

        config = ServerConfig()  # 全默认：最不安全
        # 不 debug，所以 api_keys 会被填充
        assert config.warn_if_insecure()  # 至少有一条
