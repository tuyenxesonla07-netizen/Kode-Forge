"""Phase 4 tests: Error sanitization (Gap 14)."""

import pytest
from tools.server.app import sanitize_error, sanitize_log_message


class TestSanitizeError:
    def test_runtime_error_sanitized(self):
        result = sanitize_error(RuntimeError("Connection to internal-db:5432 failed"))
        assert "internal-db" not in result
        assert "5432" not in result
        assert "internal error" in result.lower()

    def test_value_error_returns_safe_message(self):
        result = sanitize_error(ValueError("Invalid requirement format"))
        assert "Invalid" in result

    def test_type_error_returns_safe_message(self):
        result = sanitize_error(TypeError("Expected str, got int"))
        assert "Invalid" in result

    def test_http_exception_preserved(self):
        from fastapi import HTTPException
        exc = HTTPException(status_code=400, detail="Missing requirement field")
        result = sanitize_error(exc)
        assert "Missing requirement field" in result

    def test_http_exception_500_sanitized(self):
        from fastapi import HTTPException
        exc = HTTPException(status_code=500, detail="Internal server traceback...")
        result = sanitize_error(exc)
        assert "traceback" not in result.lower()

    def test_os_error_sanitized(self):
        result = sanitize_error(OSError("[Errno 2] No such file: '/etc/secrets'"))
        assert "/etc/secrets" not in result

    def test_generic_exception_sanitized(self):
        result = sanitize_error(Exception("Secret data: password=12345"))
        # Generic exception should not expose internal details
        assert "password" not in result or "internal error" in result.lower()


class TestSanitizeLogMessage:
    def test_host_port_redacted(self):
        result = sanitize_log_message("Connection to db-host:5432 failed")
        assert "5432" not in result
        assert "[REDACTED]" in result

    def test_file_path_redacted(self):
        result = sanitize_log_message("Error in /home/user/app/main.py")
        assert "/home/user" not in result

    def test_database_url_redacted(self):
        result = sanitize_log_message("Connected to postgres://user:pass@host/db")
        assert "postgres://" not in result

    def test_clean_message_unchanged(self):
        result = sanitize_log_message("Pipeline completed successfully")
        assert result == "Pipeline completed successfully"
