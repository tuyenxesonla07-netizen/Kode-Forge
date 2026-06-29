# tools/server/middleware.py

"""
HTTP 中间件 — 关联 ID、安全头、请求体限制、Guardrails、错误脱敏。

从 app.py 中拆出，使主应用文件更聚焦于路由和配置。

本模块包含:
  - SENSITIVE_PATTERNS / sanitize_error / sanitize_log_message (from error_handlers.py)
  - CorrelationIdMiddleware                              (from middleware.py)
  - SecurityHeadersMiddleware / RequestSizeLimitMiddleware
  - GuardrailsMiddleware / GUARDED_PATHS                  (from guardrails_middleware.py)
"""

import json
import logging
import re
import uuid
from typing import List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error sanitization (from error_handlers.py)
# ---------------------------------------------------------------------------

# 需要脱敏的模式
SENSITIVE_PATTERNS = [
    re.compile(r"[a-zA-Z0-9.-]+:\d{2,5}"),        # host:port
    re.compile(r"/[a-zA-Z0-9_./-]+"),               # file paths
    re.compile(r"Connection to .+ failed"),         # connection strings
    re.compile(r"sqlite://|mysql://|postgres://"),  # database URLs
    re.compile(r"File \".+\.py\", line \d+"),       # stack trace
]


def sanitize_error(exc: Exception) -> str:
    """
    将异常信息脱敏，返回安全的错误描述。

    Args:
        exc: 原始异常

    Returns:
        脱敏后的错误描述字符串
    """
    # HTTPException — 保留 detail（由开发者主动设置）
    # 但 500 级别的错误可能包含内部信息，需要脱敏
    if hasattr(exc, 'status_code') and hasattr(exc, 'detail'):
        if exc.status_code >= 500:
            return "An internal error occurred"
        return str(exc.detail)

    # ValueError / TypeError — 可能是用户输入问题
    if isinstance(exc, (ValueError, TypeError)):
        return f"Invalid request: {exc}"

    # 其他所有异常 — 不暴露内部信息
    return "An internal error occurred"


def sanitize_log_message(message: str) -> str:
    """
    对日志消息做基本脱敏（防止日志泄露敏感信息）。

    Args:
        message: 原始日志消息

    Returns:
        脱敏后的日志消息
    """
    result = message
    for pattern in SENSITIVE_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


# ---------------------------------------------------------------------------
# Correlation ID middleware (from middleware.py)
# ---------------------------------------------------------------------------

class CorrelationIdMiddleware:
    """
    请求关联 ID 中间件。

    从 X-Request-ID header 获取或生成新的 request_id，
    存入 request.state.request_id，并在响应头中返回。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 从请求头获取或生成 request_id
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode("utf-8", errors="replace")

        if not request_id:
            request_id = uuid.uuid4().hex[:12]

        # 将 request_id 存入 scope 供下游中间件/路由使用
        scope["request_id"] = request_id

        # 包装 send 以注入响应头
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-request-id"] = request_id.encode("utf-8")
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware:
    """添加安全响应头"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-content-type-options"] = b"nosniff"
                headers[b"x-frame-options"] = b"DENY"
                headers[b"x-xss-protection"] = b"1; mode=block"
                headers[b"referrer-policy"] = b"strict-origin-when-cross-origin"
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------------------------------------------------------------------------
# RequestSizeLimitMiddleware
# ---------------------------------------------------------------------------

class RequestSizeLimitMiddleware:
    """限制请求体大小"""

    def __init__(self, app, max_size_bytes: int = 10 * 1024 * 1024):
        self.app = app
        self.max_size_bytes = max_size_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 只检查 POST/PUT/PATCH
        if scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        # 检查 Content-Length header
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.max_size_bytes:
                    from starlette.responses import JSONResponse
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    )
                    await response(scope, receive, send)
                    return
            except (ValueError, TypeError):
                pass

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Guardrails middleware (from guardrails_middleware.py)
# ---------------------------------------------------------------------------

# 需要检查的路径
GUARDED_PATHS = ("/api/v1/pipeline/run", "/api/v1/pipeline/stream")


class GuardrailsMiddleware:
    """
    Guardrails HTTP 中间件。

    对 POST 到 pipeline 端点的请求做 InputGuard 检查，
    对 pipeline 响应做 OutputGuard 检查（strict + is_code）。

    其他路径（health, sessions, docs 等）不做 guardrails 检查。
    """

    def __init__(self, app, enabled: bool = True):
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # 只对 POST 到 pipeline 端点做 guardrails
        if method != "POST" or path not in GUARDED_PATHS:
            await self.app(scope, receive, send)
            return

        # ─── 请求检查 (InputGuard) ─────────────────────────────

        # 读取请求 body
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        # 尝试解析 JSON 并检查 requirement 字段
        if body:
            try:
                body_json = json.loads(body)
                requirement = body_json.get("requirement", "")

                if requirement:
                    from tools.guardrails.input_guard import InputGuard

                    guard = InputGuard(max_length=5000)
                    result = guard.check(requirement)

                    if not result.passed:
                        logger.warning(
                            "[Guardrails] Input blocked: %s", result.reason
                        )
                        from starlette.responses import JSONResponse
                        response = JSONResponse(
                            status_code=400,
                            content={"detail": result.reason},
                        )
                        await response(scope, receive, send)
                        return

                    # 用脱敏后的 requirement 替换原始 body
                    if result.text != requirement:
                        body_json["requirement"] = result.text
                        body = json.dumps(body_json, ensure_ascii=False).encode("utf-8")

            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # 非 JSON body，跳过 InputGuard

        # 构造新的 receive 函数，将已消费的 body 重新注入
        body_sent = False

        async def receive_wrapper():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return await receive()

        # ─── 响应检查 (OutputGuard) ─────────────────────────────

        response_body_chunks = []

        async def send_wrapper(message):
            if message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    response_body_chunks.append(chunk)
            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)

        # 收集完整响应 body 并做 OutputGuard 检查
        if response_body_chunks:
            full_body = b"".join(response_body_chunks)
            try:
                body_text = full_body.decode("utf-8", errors="replace")

                # 只检查 JSON 响应（跳过 SSE）
                if body_text.startswith("{") or body_text.startswith("["):
                    from tools.guardrails.output_guard import OutputGuard

                    guard = OutputGuard(strict=True)
                    result = guard.check(body_text, is_code=True)

                    if not result.passed:
                        logger.warning(
                            "[Guardrails] Output blocked: %s",
                            "; ".join(result.issues),
                        )
            except Exception:
                pass  # 不因 guardrails 错误影响服务
