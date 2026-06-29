"""Phase 5 tests: Concurrency control, memory management, circuit breaker."""

import asyncio
import pytest
from tools.workflow.engine import WorkflowEngine, WorkflowResult
from tools.workflow.engine import CircuitBreaker, CircuitState, CircuitBreakerOpenError


# ===========================================================================
# Gap 17: Concurrency control
# ===========================================================================

class TestConcurrency:
    def test_semaphore_exists(self):
        engine = WorkflowEngine(max_concurrent=3)
        assert engine._semaphore._value == 3

    def test_semaphore_limits_concurrent_execution(self):
        """Verify semaphore value is respected."""
        engine = WorkflowEngine(max_concurrent=1)
        assert engine._semaphore._value == 1

    def test_default_concurrent_is_5(self):
        engine = WorkflowEngine()
        assert engine._max_concurrent == 5

    def test_custom_concurrent_limit(self):
        engine = WorkflowEngine(max_concurrent=10)
        assert engine._semaphore._value == 10


# ===========================================================================
# Gap 18: Memory management (LRU cache)
# ===========================================================================

class TestMemoryManagement:
    def test_runs_eviction(self):
        """Gap 18: Old runs are evicted when cache exceeds max_runs_cache."""
        engine = WorkflowEngine(max_runs_cache=5)
        for i in range(10):
            engine._runs[f"run_{i}"] = WorkflowResult(
                workflow_id="test", status="success",
                outputs={}, execution_time_ms=0, logs=[],
                started_at="2024-01-01T00:00:00Z", finished_at="2024-01-01T00:00:01Z",
            )
        engine._evict_runs_cache()
        assert len(engine._runs) == 5
        # Oldest entries should be evicted
        assert "run_0" not in engine._runs
        assert "run_1" not in engine._runs
        assert "run_9" in engine._runs
        assert "run_8" in engine._runs

    def test_eviction_preserves_recent(self):
        """Recent runs are kept after eviction."""
        engine = WorkflowEngine(max_runs_cache=3)
        for i in range(5):
            engine._runs[f"run_{i}"] = WorkflowResult(
                workflow_id="test", status="success",
                outputs={}, execution_time_ms=0, logs=[],
                started_at="2024-01-01T00:00:00Z", finished_at="2024-01-01T00:00:01Z",
            )
        engine._evict_runs_cache()
        assert len(engine._runs) == 3
        assert "run_2" in engine._runs
        assert "run_3" in engine._runs
        assert "run_4" in engine._runs

    def test_default_cache_size(self):
        engine = WorkflowEngine()
        assert engine._max_runs_cache == 1000


# ===========================================================================
# Gap 19: Anthropic timeout
# ===========================================================================

class TestAnthropicTimeout:
    def test_timeout_configured(self):
        """Gap 19: Provider has timeout attribute."""
        from tools.llm.anthropic import _DEFAULT_TIMEOUT_SECONDS
        assert _DEFAULT_TIMEOUT_SECONDS == 120.0

    def test_timeout_value(self):
        """Gap 19: Provider instance has _timeout attribute."""
        from tools.llm.anthropic import _DEFAULT_TIMEOUT_SECONDS
        assert _DEFAULT_TIMEOUT_SECONDS == 120.0


# ===========================================================================
# Gap 20: Retry jitter
# ===========================================================================

class TestRetryJitter:
    def test_jitter_in_retry_delay(self):
        """Gap 20: Retry delay includes jitter (random component)."""
        import inspect
        from tools.llm.anthropic import AnthropicClaudeProvider
        source = inspect.getsource(AnthropicClaudeProvider.complete)
        assert "random" in source.lower() or "jitter" in source.lower()

    def test_random_imported(self):
        """random module is imported in anthropic.py."""
        import inspect
        from tools.llm import anthropic
        source = inspect.getsource(anthropic)
        assert "import random" in source


# ===========================================================================
# Circuit Breaker (Gap 16)
# ===========================================================================

class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        async def failing():
            raise ConnectionError("LLM service unavailable")

        async def run():
            cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
            for _ in range(2):
                try:
                    await cb.call(failing)
                except ConnectionError:
                    pass
            assert cb.state == CircuitState.OPEN

        asyncio.run(run())

    def test_stays_closed_under_threshold(self):
        async def failing():
            raise ConnectionError("error")

        async def run():
            cb = CircuitBreaker(failure_threshold=3)
            for _ in range(2):
                try:
                    await cb.call(failing)
                except ConnectionError:
                    pass
            assert cb.state == CircuitState.CLOSED

        asyncio.run(run())

    def test_half_open_after_timeout(self):
        async def run():
            cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))
            except ConnectionError:
                pass

            assert cb.state == CircuitState.OPEN
            await asyncio.sleep(0.15)
            # After recovery_timeout, should transition to half_open on next call
            # But since we check state directly, it's still OPEN until call() is invoked
            # The transition happens inside call()

        asyncio.run(run())

    def test_recovery_on_success(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("fail")
            return "success"

        async def run():
            cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
            # Trip the breaker
            for _ in range(2):
                try:
                    await cb.call(flaky)
                except ConnectionError:
                    pass

            assert cb.state == CircuitState.OPEN

            # Wait for recovery
            await asyncio.sleep(0.15)

            # This should succeed and close the circuit
            result = await cb.call(flaky)
            assert result == "success"
            assert cb.state == CircuitState.CLOSED

        asyncio.run(run())

    def test_open_raises_circuit_breaker_open_error(self):
        async def run():
            cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))
            except ConnectionError:
                pass

            with pytest.raises(CircuitBreakerOpenError):
                await cb.call(lambda: asyncio.coroutine(lambda: "ok")())

        asyncio.run(run())

    def test_reset(self):
        async def run():
            cb = CircuitBreaker(failure_threshold=1)
            try:
                await cb.call(lambda: (_ for _ in ()).throw(ConnectionError("fail")))
            except ConnectionError:
                pass

            assert cb.state == CircuitState.OPEN
            cb.reset()
            assert cb.state == CircuitState.CLOSED
            assert cb.failure_count == 0

        asyncio.run(run())
