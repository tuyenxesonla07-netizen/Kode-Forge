"""Phase 8 tests: Observability completion (Gaps 25, 26, 29, 30)."""

import json
import logging
import os
import tempfile
import pytest


# ===========================================================================
# Gap 25: Grafana / metrics documentation
# ===========================================================================

class TestGap25_Grafana:
    """Gap 25: No Grafana dashboards (documented in repo)."""

    def test_metrics_doc_exists(self):
        assert (
            os.path.exists("docs/metrics.md")
            or os.path.exists("docs/observability.md")
            or os.path.exists("docs/DEPLOYMENT.md")
        )

    def test_metrics_doc_has_content(self):
        path = "docs/metrics.md" if os.path.exists("docs/metrics.md") else "docs/observability.md" if os.path.exists("docs/observability.md") else "docs/DEPLOYMENT.md"
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Prometheus" in content or "Grafana" in content or "监控" in content or "metrics" in content.lower()

    def test_metrics_doc_has_dashboard_config(self):
        path = "docs/metrics.md" if os.path.exists("docs/metrics.md") else "docs/observability.md" if os.path.exists("docs/observability.md") else "docs/DEPLOYMENT.md"
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Grafana" in content or "dashboard" in content.lower() or "仪表盘" in content or "监控" in content


# ===========================================================================
# Gap 26: Alert delivery
# ===========================================================================

class TestGap26_Alerting:
    """Gap 26: No alert delivery."""

    def test_webhook_alerter_imports(self):
        from tools.observability.production_observability import WebhookAlerter, AlertLevel
        assert WebhookAlerter is not None
        assert AlertLevel is not None

    def test_webhook_alerter_no_url(self):
        """Alerter with no webhook should still instantiate."""
        from tools.observability.production_observability import WebhookAlerter
        alerter = WebhookAlerter(webhook_url=None)
        assert alerter is not None
        assert alerter.webhook_url == ""

    def test_webhook_alerter_sends(self):
        """Alerter with no URL should return False and log."""
        from tools.observability.production_observability import WebhookAlerter, AlertLevel
        alerter = WebhookAlerter(webhook_url=None)
        result = alerter.send("Test alert", level=AlertLevel.WARNING)
        assert result is False

    def test_webhook_alerter_history(self):
        """Sent alerts should appear in history."""
        from tools.observability.production_observability import WebhookAlerter, AlertLevel
        alerter = WebhookAlerter(webhook_url=None)
        alerter.send("Test alert 1", level=AlertLevel.WARNING)
        alerter.send("Test alert 2", level=AlertLevel.CRITICAL)
        assert len(alerter.history) == 2
        assert alerter.history[0]["message"] == "Test alert 1"
        assert alerter.history[1]["level"] == "critical"

    def test_webhook_alerter_level_filter(self):
        """Warning alerts should be filtered when min_level is CRITICAL."""
        from tools.observability.production_observability import WebhookAlerter, AlertLevel
        alerter = WebhookAlerter(webhook_url=None, min_level=AlertLevel.CRITICAL)
        result = alerter.send("Warning", level=AlertLevel.WARNING)
        assert result is False
        assert len(alerter.history) == 0

    def test_webhook_alerter_clear_history(self):
        """Clear history should empty the list."""
        from tools.observability.production_observability import WebhookAlerter, AlertLevel
        alerter = WebhookAlerter(webhook_url=None)
        alerter.send("Test", level=AlertLevel.WARNING)
        alerter.clear_history()
        assert len(alerter.history) == 0


# ===========================================================================
# Gap 29: Log rotation (documented configuration)
# ===========================================================================

class TestGap29_LogRotation:
    """Gap 29: No log rotation (documented configuration)."""

    def test_deployment_guide_exists(self):
        assert os.path.exists("docs/deployment-guide.md") or os.path.exists("docs/DEPLOYMENT.md")

    def test_deployment_guide_has_log_section(self):
        path = "docs/deployment-guide.md" if os.path.exists("docs/deployment-guide.md") else "docs/DEPLOYMENT.md"
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "log" in content.lower() or "日志" in content

    def test_logging_config_module_exists(self):
        from tools.observability.production_observability import setup_json_logging
        assert setup_json_logging is not None


# ===========================================================================
# Gap 30: Tracer export
# ===========================================================================

class TestGap30_TracerExport:
    """Gap 30: Tracer doesn't export."""

    def test_setup_json_logging_exists(self):
        from tools.observability.production_observability import setup_json_logging
        assert setup_json_logging is not None

    def test_tracer_export_spans_json(self):
        from tools.observability.pipeline_telemetry import Tracer
        tracer = Tracer("test")
        with tracer.span_ctx("test_step"):
            pass
        result = tracer.export_spans("json")
        data = json.loads(result)
        assert "summary" in data
        assert "spans" in data
        assert len(data["spans"]) > 0

    def test_tracer_export_spans_otlp(self):
        from tools.observability.pipeline_telemetry import Tracer
        tracer = Tracer("test")
        tracer.event("test_event")
        result = tracer.export_spans("otlp")
        data = json.loads(result)
        assert "resourceSpans" in data
        spans = data["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) > 0
        assert "traceId" in spans[0]
        assert "spanId" in spans[0]

    def test_tracer_export_invalid_format(self):
        from tools.observability.pipeline_telemetry import Tracer
        tracer = Tracer("test")
        with pytest.raises(ValueError):
            tracer.export_spans("invalid_format")

    def test_json_logging_setup(self):
        """Verify setup_json_logging configures root logger."""
        from tools.observability.production_observability import setup_json_logging
        # Use temp file to avoid polluting test output
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_file = f.name
        try:
            setup_json_logging(level="DEBUG", log_file=log_file, enable_console=False)
            logger = logging.getLogger("test_phase8")
            logger.info("Test message", extra={"request_id": "test-123"})
            # Verify file was written
            assert os.path.exists(log_file)
            with open(log_file, encoding="utf-8") as f:
                content = f.read()
            assert "Test message" in content
        finally:
            # Cleanup
            root = logging.getLogger()
            for handler in root.handlers[:]:
                if hasattr(handler, 'baseFilename') and handler.baseFilename == log_file:
                    root.removeHandler(handler)
                    handler.close()
            os.unlink(log_file)

    def test_sensitive_filter_redacts_api_keys(self):
        """SensitiveFilter should redact sk- prefixed strings."""
        from tools.observability.production_observability import SensitiveFilter
        filter_obj = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0,
            msg="Key: sk-abc123def456ghi789",
            args=(), exc_info=None,
        )
        filter_obj.filter(record)
        assert "sk-***" in record.msg
        assert "sk-abc123def456ghi789" not in record.msg
