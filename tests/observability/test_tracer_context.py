# tests/observability/test_tracer_context.py
"""Tests for Tracer — contextmanager span_ctx."""

import pytest

from tools.observability.pipeline_telemetry import Tracer


class TestTracerContextManager:
    def test_span_ctx_yields_span(self):
        t = Tracer()
        with t.span_ctx("test_span", key="val") as span:
            assert span["name"] == "test_span"
            assert span["attributes"]["key"] == "val"
        assert span["duration_ms"] >= 0

    def test_span_ctx_auto_finishes_on_success(self):
        t = Tracer()
        with t.span_ctx("auto_finish"):
            pass
        assert len(t.spans) == 1
        assert t.spans[0]["status"] == "ok"
        assert t._stack == []

    def test_span_ctx_marks_error_on_exception(self):
        t = Tracer()
        with pytest.raises(ValueError, match="boom"):
            with t.span_ctx("failing_span"):
                raise ValueError("boom")

        assert len(t.spans) == 1
        assert t.spans[0]["status"] == "error"
        assert t.spans[0]["attributes"]["error"] == "boom"
        assert t.spans[0]["attributes"]["error_type"] == "ValueError"
        assert t._stack == []

    def test_nested_span_ctx(self):
        t = Tracer()
        with t.span_ctx("outer"):
            with t.span_ctx("inner"):
                pass
        assert len(t.spans) == 2
        assert t.spans[0]["name"] == "outer"
        assert t.spans[1]["name"] == "inner"
        assert t.spans[1]["parent_id"] == t.spans[0]["span_id"]

    def test_nested_span_ctx_exception_in_inner(self):
        t = Tracer()
        with t.span_ctx("outer"):
            with pytest.raises(RuntimeError):
                with t.span_ctx("inner"):
                    raise RuntimeError("fail")

        assert t.spans[0]["status"] == "ok"
        assert t.spans[1]["status"] == "error"

    def test_span_ctx_with_manual_span_compatibility(self):
        t = Tracer()
        manual = t.span("manual")
        with t.span_ctx("ctx_span"):
            pass
        t.finish_span(manual)

        names = [s["name"] for s in t.spans]
        assert "manual" in names
        assert "ctx_span" in names

    def test_span_ctx_records_duration(self):
        t = Tracer()
        with t.span_ctx("timed") as span:
            pass
        assert span["duration_ms"] >= 0
