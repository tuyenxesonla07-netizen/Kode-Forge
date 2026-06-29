"""Tests for FastAPI server app."""

import pytest
from tools.server.app import create_app, ServerConfig


class TestServerConfig:
    def test_default_config(self):
        config = ServerConfig()
        assert config.port == 8080
        assert config.host == "0.0.0.0"
        assert config.max_concurrent_pipelines == 5

    def test_from_env(self):
        import os
        os.environ["CC_SERVER_PORT"] = "9090"
        os.environ["CC_DEBUG"] = "true"
        config = ServerConfig.from_env()
        assert config.port == 9090
        assert config.debug is True
        # Cleanup
        del os.environ["CC_SERVER_PORT"]
        del os.environ["CC_DEBUG"]


class TestApp:
    @pytest.fixture
    def client(self):
        """Create test client."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi.testclient not installed (pip install httpx)")

        app = create_app(config=ServerConfig(debug=True))
        return TestClient(app)

    def test_health_check(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data

    def test_list_components(self, client):
        response = client.get("/api/v1/components")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data

    def test_run_pipeline_missing_requirement(self, client):
        response = client.post("/api/v1/pipeline/run", json={})
        # FastAPI may return 422 for missing required field or 400 from our handler
        assert response.status_code in (400, 422)

    def test_run_pipeline_empty_requirement(self, client):
        response = client.post("/api/v1/pipeline/run", json={"requirement": "  "})
        assert response.status_code in (400, 422)

    def test_run_pipeline_invalid_json(self, client):
        response = client.post(
            "/api/v1/pipeline/run",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        # FastAPI returns 422 for malformed request bodies
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_run_pipeline_success(self, client):
        """Test successful pipeline execution."""
        response = client.post(
            "/api/v1/pipeline/run",
            json={"requirement": "构建用户登录模块"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "run_id" in data

    def test_stream_endpoint_exists(self, client):
        """Test that stream endpoint returns SSE format."""
        response = client.post(
            "/api/v1/pipeline/stream",
            json={"requirement": "构建认证模块"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_status_not_found(self, client):
        response = client.get("/api/v1/pipeline/status/nonexistent")
        assert response.status_code == 404
