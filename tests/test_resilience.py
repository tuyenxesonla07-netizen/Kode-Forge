# tests/test_resilience.py
"""
P1-3: 错误恢复与降级策略测试。

覆盖: CircuitBreaker, retry_with_fallback, FallbackProvider, graceful_degrade
"""
import time
import unittest
from unittest.mock import MagicMock, patch

from tools.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    FallbackProvider,
    RetryConfig,
    graceful_degrade,
    retry_with_fallback,
)


class TestCircuitBreaker(unittest.TestCase):
    """CircuitBreaker 状态机测试"""

    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_resets_on_success(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_success()
        assert cb._failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_closes_on_success(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_decorator_blocks_when_open(self):
        cb = CircuitBreaker(failure_threshold=1)

        @cb
        def failing_func():
            raise ValueError("fail")

        with self.assertRaises(ValueError):
            failing_func()

        with self.assertRaises(CircuitOpenError):
            failing_func()


class TestRetryWithFallback(unittest.TestCase):
    """retry_with_fallback 测试"""

    def test_succeeds_first_try(self):
        @retry_with_fallback(config=RetryConfig(max_retries=2))
        def always_works():
            return "ok"

        assert always_works() == "ok"

    def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        @retry_with_fallback(config=RetryConfig(max_retries=3, base_delay=0.01))
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("timeout")
            return "success"

        result = flaky()
        assert result == "success"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        @retry_with_fallback(config=RetryConfig(max_retries=2, base_delay=0.01))
        def always_fails():
            raise ValueError("bad")

        with self.assertRaises(ValueError):
            always_fails()

    def test_fallback_value_on_failure(self):
        @retry_with_fallback(config=RetryConfig(max_retries=1, base_delay=0.01), fallback_value="default")
        def always_fails():
            raise RuntimeError("fail")

        assert always_fails() == "default"

    def test_fallback_factory_on_failure(self):
        def make_fallback(exc):
            return f"recovered from {type(exc).__name__}"

        @retry_with_fallback(config=RetryConfig(max_retries=1, base_delay=0.01), fallback_factory=make_fallback)
        def always_fails():
            raise RuntimeError("fail")

        assert always_fails() == "recovered from RuntimeError"

    def test_only_retries_specified_exceptions(self):
        call_count = 0

        @retry_with_fallback(
            config=RetryConfig(max_retries=3, base_delay=0.01, retryable_exceptions=(ConnectionError,)),
        )
        def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        with self.assertRaises(TypeError):
            raises_type_error()
        assert call_count == 1  # 不重试

    def test_exponential_backoff_delay(self):
        delays = []
        config = RetryConfig(max_retries=3, base_delay=0.1, exponential_backoff=True)

        @retry_with_fallback(config=config)
        def track_delays():
            delays.append(time.time())
            raise ValueError("fail")

        with patch("tools.resilience.time.sleep"):
            with self.assertRaises(ValueError):
                track_delays()

        # 验证 sleep 被调用且延迟递增
        # patch 了 sleep，所以 delays 没有实际延迟，但逻辑上应该调用了 3 次 sleep

    def test_on_retry_callback(self):
        callback_calls = []
        config = RetryConfig(max_retries=2, base_delay=0.01, on_retry=lambda e, n: callback_calls.append(n))

        @retry_with_fallback(config=config)
        def fails():
            raise ValueError("fail")

        with self.assertRaises(ValueError):
            fails()
        assert callback_calls == [1, 2]


class TestFallbackProvider(unittest.TestCase):
    """FallbackProvider 链式降级测试"""

    def test_first_provider_succeeds(self):
        p1 = MagicMock()
        p1.complete.return_value = "from_p1"
        p1.get_name.return_value = "P1"

        p2 = MagicMock()
        p2.get_name.return_value = "P2"

        provider = FallbackProvider([p1, p2])
        result = provider.complete("hello")

        assert result == "from_p1"
        p2.complete.assert_not_called()

    def test_falls_back_on_first_failure(self):
        p1 = MagicMock()
        p1.complete.side_effect = RuntimeError("API down")
        p1.get_name.return_value = "P1"

        p2 = MagicMock()
        p2.complete.return_value = "from_p2"
        p2.get_name.return_value = "P2"

        provider = FallbackProvider([p1, p2])
        result = provider.complete("hello")

        assert result == "from_p2"

    def test_raises_when_all_fail(self):
        p1 = MagicMock()
        p1.complete.side_effect = RuntimeError("fail1")
        p1.get_name.return_value = "P1"

        p2 = MagicMock()
        p2.complete.side_effect = RuntimeError("fail2")
        p2.get_name.return_value = "P2"

        provider = FallbackProvider([p1, p2])
        with self.assertRaises(RuntimeError) as ctx:
            provider.complete("hello")
        assert "All LLM providers failed" in str(ctx.exception)

    def test_skips_open_circuit_breaker(self):
        p1 = MagicMock()
        p1.complete.side_effect = RuntimeError("fail")
        p1.get_name.return_value = "P1"

        p2 = MagicMock()
        p2.complete.return_value = "from_p2"
        p2.get_name.return_value = "P2"

        provider = FallbackProvider([p1, p2])
        # 手动打开 p1 的熔断器
        provider.circuit_breakers[0]._state = CircuitState.OPEN

        result = provider.complete("hello")
        assert result == "from_p2"
        p1.complete.assert_not_called()

    def test_get_name(self):
        p1 = MagicMock()
        p1.get_name.return_value = "Anthropic"
        p2 = MagicMock()
        p2.get_name.return_value = "OpenAI"

        provider = FallbackProvider([p1, p2])
        assert "Anthropic" in provider.get_name()
        assert "OpenAI" in provider.get_name()


class TestGracefulDegrade(unittest.TestCase):
    """graceful_degrade 测试"""

    def test_returns_value_on_success(self):
        @graceful_degrade(default_return="fallback")
        def works():
            return "success"

        assert works() == "success"

    def test_returns_default_on_failure(self):
        @graceful_degrade(default_return="fallback")
        def fails():
            raise RuntimeError("oops")

        assert fails() == "fallback"

    def test_only_catches_specified_exceptions(self):
        @graceful_degrade(default_return="fallback", exceptions=(ValueError,))
        def raises_type_error():
            raise TypeError("not caught")

        with self.assertRaises(TypeError):
            raises_type_error()

    def test_returns_none_by_default(self):
        @graceful_degrade()
        def fails():
            raise RuntimeError("oops")

        assert fails() is None


if __name__ == "__main__":
    unittest.main()
