"""Phase 4 tests: Correlation IDs (Gap 28)."""

import pytest
from fastapi.testclient import TestClient

from tools.server.app import create_app, ServerConfig


class TestCorrelationID:
    def test_request_id_generated(self):
        """Gap 28: Server generates X-Request-ID when not provided."""
        app = create_app(config=ServerConfig(debug=True))
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    def test_request_id_propagated(self):
        """Gap 28: Custom X-Request-ID is propagated back."""
        app = create_app(config=ServerConfig(debug=True))
        client = TestClient(app)
        custom_id = "my-custom-id-123"
        response = client.get(
            "/api/v1/health",
            headers={"X-Request-ID": custom_id},
        )
        assert response.headers["x-request-id"] == custom_id

    def test_request_id_unique_per_request(self):
        """Each request gets a unique ID."""
        app = create_app(config=ServerConfig(debug=True))
        client = TestClient(app)
        r1 = client.get("/api/v1/health")
        r2 = client.get("/api/v1/health")
        # IDs should be different (unless extremely unlucky)
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]

    def test_request_id_present_on_post(self):
        """POST responses also include X-Request-ID."""
        app = create_app(config=ServerConfig(debug=True))
        client = TestClient(app)
        response = client.post(
            "/api/v1/pipeline/run",
            json={"requirement": "test"},
        )
        assert "x-request-id" in response.headers

    def test_request_id_present_on_404(self):
        """Even 404 responses include X-Request-ID."""
        app = create_app(config=ServerConfig(debug=True))
        client = TestClient(app)
        response = client.get("/api/v1/nonexistent")
        assert "x-request-id" in response.headers
