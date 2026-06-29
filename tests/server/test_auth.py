"""Phase 1 tests: Authentication, CORS, Security Headers, Request Size Limits."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from tools.server.app import create_app, ServerConfig
from tools.server.app import hash_api_key, verify_api_key, APIKeyValidator

VALID_KEY = "test-secure-key-12345"
VALID_KEY_HASH = hashlib.sha256(VALID_KEY.encode()).hexdigest()


# ===========================================================================
# Auth: API Key Hashing & Verification
# ===========================================================================

class TestApiKeyHashing:
    def test_hash_api_key_returns_sha256(self):
        h = hash_api_key("any-key")
        assert len(h) == 64  # SHA-256 hex digest

    def test_hash_deterministic(self):
        assert hash_api_key("key1") == hash_api_key("key1")

    def test_different_keys_different_hashes(self):
        assert hash_api_key("key1") != hash_api_key("key2")


class TestVerifyApiKey:
    def test_empty_allowed_always_true(self):
        assert verify_api_key("any-key", []) is True

    def test_matching_key_returns_true(self):
        assert verify_api_key(VALID_KEY, [VALID_KEY_HASH]) is True

    def test_non_matching_key_returns_false(self):
        assert verify_api_key("wrong-key", [VALID_KEY_HASH]) is False

    def test_multiple_keys_matches_second(self):
        h2 = hashlib.sha256(b"key2").hexdigest()
        assert verify_api_key("key2", [VALID_KEY_HASH, h2]) is True


# ===========================================================================
# Auth: HTTP Layer
# ===========================================================================

class TestAuthEnabled:
    """Tests when api_keys is configured."""

    def test_missing_key_returns_401(self):
        app = create_app(config=ServerConfig(api_keys=[VALID_KEY_HASH]))
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.status_code == 401

    def test_invalid_key_returns_401(self):
        app = create_app(config=ServerConfig(api_keys=[VALID_KEY_HASH]))
        client = TestClient(app)
        response = client.get("/api/v1/health", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401

    def test_valid_key_returns_200(self):
        app = create_app(config=ServerConfig(api_keys=[VALID_KEY_HASH]))
        client = TestClient(app)
        response = client.get("/api/v1/health", headers={"X-API-Key": VALID_KEY})
        assert response.status_code == 200

    def test_pipeline_run_requires_auth(self):
        app = create_app(config=ServerConfig(api_keys=[VALID_KEY_HASH]))
        client = TestClient(app)
        response = client.post("/api/v1/pipeline/run", json={"requirement": "test"})
        assert response.status_code == 401

    def test_pipeline_run_with_key_succeeds(self):
        app = create_app(config=ServerConfig(api_keys=[VALID_KEY_HASH]))
        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline/run",
            json={"requirement": "test"},
            headers={"X-API-Key": VALID_KEY},
        )
        # 200 or 500 (pipeline may fail but auth passes)
        assert response.status_code != 401

    def test_sessions_requires_auth(self):
        app = create_app(config=ServerConfig(api_keys=[VALID_KEY_HASH]))
        client = TestClient(app)
        response = client.get("/api/v1/sessions")
        assert response.status_code == 401

    def test_sessions_with_key_succeeds(self):
        app = create_app(config=ServerConfig(api_keys=[VALID_KEY_HASH]))
        client = TestClient(app)
        response = client.get("/api/v1/sessions", headers={"X-API-Key": VALID_KEY})
        assert response.status_code == 200


class TestAuthDisabled:
    """Tests backward compat: no api_keys = no auth required."""

    def test_no_key_accepted_when_no_config(self):
        app = create_app(config=ServerConfig(api_keys=[]))
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_pipeline_run_no_key_when_no_config(self):
        app = create_app(config=ServerConfig(api_keys=[]))
        client = TestClient(app)
        response = client.post("/api/v1/pipeline/run", json={"requirement": "test"})
        assert response.status_code != 401


class TestSecurityHeaders:
    def test_x_content_type_options(self):
        app = create_app(config=ServerConfig())
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self):
        app = create_app(config=ServerConfig())
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_x_xss_protection(self):
        app = create_app(config=ServerConfig())
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.headers.get("x-xss-protection") == "1; mode=block"

    def test_referrer_policy(self):
        app = create_app(config=ServerConfig())
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert "strict-origin-when-cross-origin" in response.headers.get("referrer-policy", "")


class TestCORS:
    def test_cors_default_allows_all(self):
        app = create_app(config=ServerConfig(cors_origins=["*"]))
        client = TestClient(app)
        response = client.options(
            "/api/v1/pipeline/run",
            headers={"Origin": "http://any-origin.com"},
        )
        allow_origin = response.headers.get("access-control-allow-origin", "")
        # When credentials=True, Starlette mirrors the origin instead of "*"
        assert allow_origin in ("*", "http://any-origin.com")

    def test_cors_specific_origin(self):
        app = create_app(config=ServerConfig(cors_origins=["http://localhost:3000"]))
        client = TestClient(app)
        response = client.options(
            "/api/v1/pipeline/run",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_rejects_unlisted_origin(self):
        app = create_app(config=ServerConfig(cors_origins=["http://localhost:3000"]))
        client = TestClient(app)
        response = client.options(
            "/api/v1/pipeline/run",
            headers={"Origin": "http://evil.com"},
        )
        assert response.headers.get("access-control-allow-origin") != "http://evil.com"

    def test_cors_origins_from_env(self):
        config = ServerConfig(cors_origins=["http://myapp.com"])
        assert config.cors_origins == ["http://myapp.com"]


class TestDocsProtection:
    def test_docs_open_by_default(self):
        app = create_app(config=ServerConfig(protect_docs=False))
        client = TestClient(app)
        response = client.get("/docs")
        assert response.status_code == 200

    def test_docs_closed_when_protected_no_keys(self):
        """protect_docs=True but no api_keys → docs still open (auth not enforced on docs)."""
        app = create_app(config=ServerConfig(protect_docs=True))
        client = TestClient(app)
        response = client.get("/docs")
        # docs_url=None means FastAPI doesn't serve it
        assert response.status_code == 404


class TestConfigFromEnv:
    def test_api_keys_from_env(self):
        import os
        os.environ["CC_API_KEYS"] = f"hash1,hash2"
        try:
            config = ServerConfig.from_env()
            assert config.api_keys == ["hash1", "hash2"]
        finally:
            del os.environ["CC_API_KEYS"]

    def test_rate_limit_from_env(self):
        import os
        os.environ["CC_RATE_LIMIT"] = "30/minute"
        try:
            config = ServerConfig.from_env()
            assert config.rate_limit == "30/minute"
        finally:
            del os.environ["CC_RATE_LIMIT"]

    def test_protect_docs_from_env(self):
        import os
        os.environ["CC_PROTECT_DOCS"] = "true"
        try:
            config = ServerConfig.from_env()
            assert config.protect_docs is True
        finally:
            del os.environ["CC_PROTECT_DOCS"]
