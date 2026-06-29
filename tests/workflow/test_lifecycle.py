# tests/workflow/test_lifecycle.py
"""Tests for LifecycleHooks — workflow lifecycle event system."""

import pytest

from tools.workflow.engine import LifecycleHooks


class TestLifecycleHooks:
    def test_register_and_emit(self):
        hooks = LifecycleHooks()
        called = []

        def on_start(event):
            called.append(event.hook)

        hooks.register("on_start", on_start)
        hooks.emit("on_start", run_id="r1")
        assert called == ["on_start"]

    def test_decorator_registration(self):
        hooks = LifecycleHooks()

        @hooks.on("on_step")
        def log_step(event):
            pass

        assert hooks.handler_count("on_step") == 1

    def test_multiple_handlers(self):
        hooks = LifecycleHooks()
        results = []

        hooks.register("on_complete", lambda e: results.append("first"))
        hooks.register("on_complete", lambda e: results.append("second"))

        hooks.emit("on_complete", run_id="r1")
        assert results == ["first", "second"]

    def test_error_in_handler_does_not_break(self):
        hooks = LifecycleHooks()

        def bad_handler(event):
            raise RuntimeError("handler error")

        def good_handler(event):
            pass

        hooks.register("on_error", bad_handler)
        hooks.register("on_error", good_handler)

        results = hooks.emit("on_error", run_id="r1", data={"error": "test"})
        assert len(results) == 2

    def test_unregister(self):
        hooks = LifecycleHooks()
        handler = lambda e: None
        hooks.register("on_start", handler)
        assert hooks.unregister("on_start", handler) is True
        assert hooks.handler_count("on_start") == 0

    def test_clear(self):
        hooks = LifecycleHooks()
        hooks.register("on_start", lambda e: None)
        hooks.register("on_step", lambda e: None)
        hooks.clear()
        assert hooks.handler_count() == 0

    def test_emit_with_data(self):
        hooks = LifecycleHooks()
        received = []

        def capture(event):
            received.append(event.data)

        hooks.register("on_error", capture)
        hooks.emit("on_error", run_id="r1", node_id="n5", data={"error": "timeout"})
        assert received[0]["error"] == "timeout"
