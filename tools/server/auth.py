# tools/server/auth.py

"""
认证工具 — API Key 哈希、验证、中间件。

从 app.py 中拆出，使主应用文件更聚焦于路由和配置。

本模块包含:
  - hash_api_key / verify_api_key
  - APIKeyValidator (FastAPI 依赖注入)
  - AuthMiddleware (全局认证中间件)
"""

import hashlib
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth utilities
# ---------------------------------------------------------------------------

def hash_api_key(plain_key: str) -> str:
    """将明文 API Key 转为 SHA-256 哈希"""
    return hashlib.sha256(plain_key.encode()).hexdigest()


def verify_api_key(plain_key: str, allowed_hashes: List[str]) -> bool:
    """验证明文 API Key 是否匹配允许的哈希列表"""
    if not allowed_hashes:
        return True  # 无配置 = 全部允许
    key_hash = hash_api_key(plain_key)
    return key_hash in allowed_hashes


# ---------------------------------------------------------------------------
# APIKeyValidator
# ---------------------------------------------------------------------------

class APIKeyValidator:
    """
    FastAPI 依赖注入用的 API Key 验证器。

    用法:
        validator = APIKeyValidator(api_keys=["hash1", ...])
        app.add_api_route("/protected", dependencies=[Depends(validator)])

    或在 app.py 中直接使用:
        @app.get("/api/v1/protected", dependencies=[Depends(validator)])
    """

    def __init__(self, api_keys: Optional[List[str]] = None):
        self.allowed_hashes: List[str] = api_keys or []

    async def __call__(self, x_api_key: Optional[str] = None) -> bool:
        """
        FastAPI Security 依赖。

        Args:
            x_api_key: X-API-Key header 的值

        Returns:
            True if valid

        Raises:
            HTTPException: 401 if invalid
        """
        from fastapi import HTTPException

        # 无配置时全部放行
        if not self.allowed_hashes:
            return True

        # 未提供 key
        if not x_api_key:
            logger.warning("[Auth] Missing X-API-Key header")
            raise HTTPException(
                status_code=401,
                detail="Missing X-API-Key header",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        # 验证 key
        if not verify_api_key(x_api_key, self.allowed_hashes):
            logger.warning("[Auth] Invalid API key attempt: %s...", x_api_key[:8])
            raise HTTPException(
                status_code=401,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        return True

    @classmethod
    def from_env(cls) -> "APIKeyValidator":
        """从环境变量加载 API Keys"""
        import os
        keys_str = os.getenv("CC_API_KEYS", "")
        if keys_str:
            keys = [k.strip() for k in keys_str.split(",") if k.strip()]
            return cls(api_keys=keys)
        return cls(api_keys=[])


# ---------------------------------------------------------------------------
# AuthMiddleware
# ---------------------------------------------------------------------------

class AuthMiddleware:
    """
    全局认证中间件。

    当 api_keys 非空时，所有请求必须携带有效的 X-API-Key header。
    当 api_keys 为空时（默认），所有请求放行。

    应用于路由之前，在 SecurityHeadersMiddleware 之后。
    """

    def __init__(self, app, api_keys: Optional[List[str]] = None):
        self.app = app
        self.allowed_hashes: List[str] = api_keys or []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 无认证配置时全部放行
        if not self.allowed_hashes:
            await self.app(scope, receive, send)
            return

        # 提取 X-API-Key header
        headers = dict(scope.get("headers", []))
        x_api_key = headers.get(b"x-api-key", b"").decode("utf-8", errors="replace")

        if not x_api_key or not verify_api_key(x_api_key, self.allowed_hashes):
            from starlette.responses import JSONResponse
            response = JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid X-API-Key header"},
                headers={"WWW-Authenticate": "ApiKey"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
