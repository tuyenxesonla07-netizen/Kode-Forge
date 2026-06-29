# tests/observability/test_alert_manager.py
"""Tests for AlertManager — alert mechanism with error rate tracking."""

import pytest

from tools.observability.pipeline_telemetry import AlertManager, AlertRule, Tracer


def _make_error_span(tracer, name):
    """Helper: create a span with error status."""
    span = tracer.span(name)
    span["status"] = "error"
    tracer.finish_span(span)
    return span


class TestAlertManager:
    def test_error_rate_alert(self):
        tracer = Tracer()
        alerts = AlertManager(tracer)
        alerts.add_rule(AlertRule("high_error_rate", "error_rate", 0.5, window=5))

        tracer.span("ok1")
        s1 = tracer.span("err1"); s1["status"] = "error"; tracer.finish_span(s1)
        s2 = tracer.span("err2"); s2["status"] = "error"; tracer.finish_span(s2)
        s3 = tracer.span("err3"); s3["status"] = "error"; tracer.finish_span(s3)

        fired = alerts.check()
        assert len(fired) >= 1
        assert fired[0]["rule"] == "high_error_rate"

    def test_no_false_positive_low_error_rate(self):
        tracer = Tracer()
        alerts = AlertManager(tracer)
        alerts.add_rule(AlertRule("high_error_rate", "error_rate", 0.8, window=5))

        tracer.span("ok1")
        tracer.span("ok2")
        s1 = tracer.span("err1"); s1["status"] = "error"; tracer.finish_span(s1)
        tracer.span("ok3")
        tracer.span("ok4")

        fired = alerts.check()
        assert len(fired) == 0

    def test_consecutive_error_alert(self):
        tracer = Tracer()
        alerts = AlertManager(tracer)
        alerts.add_rule(AlertRule("consecutive_errors", "error_count", 3, window=10))

        for name in ["err1", "err2", "err3"]:
            s = tracer.span(name); s["status"] = "error"; tracer.finish_span(s)

        fired = alerts.check()
        assert any(a["rule"] == "consecutive_errors" for a in fired)

    def test_alert_history(self):
        tracer = Tracer()
        alerts = AlertManager(tracer)
        alerts.add_rule(AlertRule("test", "error_rate", 0.5, window=3))

        s1 = tracer.span("err1"); s1["status"] = "error"; tracer.finish_span(s1)
        s2 = tracer.span("err2"); s2["status"] = "error"; tracer.finish_span(s2)
        alerts.check()

        assert len(alerts.fired_alerts) >= 1
        alerts.clear_history()
        assert len(alerts.fired_alerts) == 0
