"""P2-4 security tests: RateLimitMiddleware.

Uses sliding window based on monotonic clock; no external dependencies.
Tests verify: parsing correctness, request throttling, reset after window,
client IP isolation, health check bypass, and graceful degradation on config error.
"""

import time

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.types import Scope

from tools.server.middleware import (
    RateLimitMiddleware,
    _parse_rate_limit,
)


# ---------------------------------------------------------------------------
# _parse_rate_limit 解析
# ---------------------------------------------------------------------------

class TestParseRateLimit:
    @pytest.mark.parametrize(
        "spec,expected",
        [
            ("30/minute", (30, 60)),
            ("100/hour", (100, 3600)),
            ("1/second", (1, 1)),
            ("10/day", (10, 86400)),
            ("  50/hour  ", (50, 3600)),
        ],
    )
    def test_valid_specs(self, spec, expected):
        assert _parse_rate_limit(spec) == expected

    @pytest.mark.parametrize(
        "spec",
        ["", "   ", "invalid", "30", "minute", "30/", "/minute", "-5/minute", "0/minute", "30/decade"],
    )
    def test_invalid_specs_return_none(self, spec):
        assert _parse_rate_limit(spec) is None


# ---------------------------------------------------------------------------
# HTTP 层集成测试
# ---------------------------------------------------------------------------

class TestRateLimitHTTP:
    """通过 TestClient 间接测试 RateLimitMiddleware 的限流行为。"""

    def _make_client(self, rate_limit: str = "3/minute"):
        """构建一个只有健康检查端点 + RateLimitMiddleware 的最小 app。"""
        from starlette.applications import Starlette
        from starlette.routing import Route

        async def health(request: Request):
            return JSONResponse({"status": "ok"})

        app = Starlette(routes=[Route("/api/v1/health", health)])
        app.add_middleware(RateLimitMiddleware, rate_limit=rate_limit)
        return TestClient(app, raise_server_exceptions=False)

    def test_within_limit_allowed(self):
        """限制内请求正常通过。"""
        client = self._make_client("5/minute")
        for _ in range(5):
            r = client.get("/api/v1/health")
            assert r.status_code == 200, f"request should pass but got {r.status_code}"

    def test_over_limit_returns_429(self):
        """超过限制后返回 429。"""
        client = self._make_client("3/minute")
        results = [client.get("/api/v1/health").status_code for _ in range(5)]
        assert results[:3] == [200, 200, 200]
        assert results[3] == 429
        assert results[4] == 429

    def test_429_has_retry_after_header(self):
        client = self._make_client("1/minute")
        client.get("/api/v1/health")  # 第 1 次：pass
        r = client.get("/api/v1/health")  # 第 2 次：blocked
        assert r.status_code == 429
        assert "retry-after" in r.headers
        retry_after = int(r.headers["retry-after"])
        assert 0 < retry_after <= 65  # monotonic clock: allow small overhead over nominal 60s

    def test_no_rate_limit_means_no_throttling(self):
        """rate_limit 为空时不限流。"""
        client = self._make_client("")
        for _ in range(100):
            r = client.get("/api/v1/health")
            assert r.status_code == 200

    def test_health_check_not_special_cased(self):
        """RateLimit 对所有路径一视同仁（包括 health）。"""
        client = self._make_client("2/minute")
        # health 也被计入
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        # 第 3 次被限流
        assert client.get("/api/v1/health").status_code == 429


# ---------------------------------------------------------------------------
# Scope 级别测试 (验证 IP 隔离 + 非 HTTP 请求通过)
# ---------------------------------------------------------------------------

class TestRateLimitScope:
    def test_non_http_requests_pass_through(self):
        """websocket 等非 HTTP 请求不受限流。"""
        middleware = RateLimitMiddleware(app=_noop_asgi(), rate_limit="2/minute")
        scope: Scope = {"type": "websocket", "client": ("127.0.0.1", 8000)}
        # 不应抛出异常
        import asyncio

        async def run():
            captured = {}

            async def receive():
                return {}

            async def send(msg):
                captured["msg"] = msg

            await middleware(scope, receive, send)

        asyncio.run(run())

    def test_client_ip_isolation(self):
        """不同 IP 被分别限流。"""
        # 通过 mock app 来计数请求
        call_count = {"n": 0}

        async def counting_app(scope, receive, send):
            call_count["n"] += 1

        middleware = RateLimitMiddleware(app=counting_app, rate_limit="1/minute")

        import asyncio

        async def run():
            for _ in range(3):
                scope: Scope = {"type": "http", "client": ("10.0.0.1", 9000), "headers": []}
                await middleware(scope, _noop_receive, _noop_send)

        asyncio.run(run())
        assert call_count["n"] == 1  # 同 IP: 仅第一次通过

        # 另一个 IP 应不受影响
        call_count["n"] = 0
        for _ in range(3):
            scope: Scope = {"type": "http", "client": ("10.0.0.2", 9000), "headers": []}
            asyncio.run(_call_middleware(middleware, scope))
        assert call_count["n"] == 1  # 另 IP: 也仅第一次通过 (limit=1/minute)


class TestClientIpExtraction:
    """Verify _client_ip respects trusted_proxies to prevent XFF spoofing."""

    def test_without_trusted_proxies_ignores_xff(self):
        """未配置 trusted_proxies 时，即使请求带 XFF header，也使用直连 peer IP。"""
        async def counting_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(app=counting_app, rate_limit="1/minute")

        scope: Scope = {
            "type": "http",
            "client": ("10.0.0.1", 9000),
            "headers": [(b"x-forwarded-for", b"1.2.3.4")],
        }
        # Without trusted_proxies configured, XFF header is ignored → peer IP used
        assert middleware._client_ip(scope) == "10.0.0.1"

    def test_with_trusted_proxies_trusts_xff(self):
        """配置了 trusted_proxies 且 peer 在其中时，才解析 XFF。"""
        async def counting_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(
            app=counting_app, rate_limit="1/minute", trusted_proxies=["10.0.0.1"]
        )
        scope: Scope = {
            "type": "http",
            "client": ("10.0.0.1", 9000),
            "headers": [(b"x-forwarded-for", b"1.2.3.4")],
        }
        assert middleware._client_ip(scope) == "1.2.3.4"

    def test_trusted_proxies_peer_not_trusted_uses_peer_ip(self):
        """Peer IP 不在 trusted_proxies 中时，忽略 XFF（防止伪造绕过）。"""
        async def counting_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(
            app=counting_app, rate_limit="1/minute", trusted_proxies=["10.0.0.99"]
        )
        # 攻击者直连到服务器，伪造 XFF header
        scope: Scope = {
            "type": "http",
            "client": ("1.2.3.4", 9000),
            "headers": [(b"x-forwarded-for", b"10.0.0.1")],
        }
        # Peer (1.2.3.4) is not in trusted_proxies → XFF ignored
        assert middleware._client_ip(scope) == "1.2.3.4"

    def test_xff_leftmost_value_used(self):
        """XFF 存在多个代理 hop 时，取最左侧 = 原始客户端。"""
        async def counting_app(scope, receive, send):
            pass

        middleware = RateLimitMiddleware(
            app=counting_app, rate_limit="1/minute", trusted_proxies=["10.0.0.1"]
        )
        scope: Scope = {
            "type": "http",
            "client": ("10.0.0.1", 9000),
            "headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.2, 10.0.0.1")],
        }
        assert middleware._client_ip(scope) == "1.2.3.4"

    def test_xff_spoofing_cannot_bypass_rate_limit(self):
        """演示核心防护：无 trusted_proxies 时，XFF 伪造无法突破限流。"""
        call_count = {"n": 0}

        async def counting_app(scope, receive, send):
            call_count["n"] += 1

        # 限流 2/minute，不配置 trusted_proxies
        middleware = RateLimitMiddleware(app=counting_app, rate_limit="2/minute")

        import asyncio

        async def run():
            # 攻击者用不同 XFF 值发送请求，但都来自同一 peer IP
            for i in range(5):
                scope: Scope = {
                    "type": "http",
                    "client": ("192.168.1.100", 9000),
                    "headers": [(b"x-forwarded-for", f"10.0.0.{i}")],
                }
                await middleware(scope, _noop_receive, _noop_send)

        asyncio.run(run())
        # 前 2 次通过，后 3 次被限流（所有请求都因 peer IP 相同被归为同一客户端）
        assert call_count["n"] == 2

async def _noop_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _noop_send(msg):
    pass


async def _call_middleware(middleware, scope):
    await middleware(scope, _noop_receive, _noop_send)


def _noop_asgi():
    async def app(scope, receive, send):
        pass
    return app
