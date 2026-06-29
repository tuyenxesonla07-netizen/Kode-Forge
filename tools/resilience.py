# tools/resilience.py
"""
P1-3: 错误恢复与降级策略。

提供:
  - RetryWithFallback: 带重试和降级的执行器
  - FallbackProvider: LLM Provider 链式降级
  - CircuitBreaker: 熔断器，防止连续失败
  - graceful_degrade: 通用降级装饰器
"""
from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional, Type

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"        # 正常
    OPEN = "open"            # 熔断（拒绝请求）
    HALF_OPEN = "half_open"  # 半开（尝试恢复）


@dataclass
class CircuitBreaker:
    """
    熔断器 — 防止连续失败时反复调用故障服务。

    状态机:
      CLOSED  → 失败次数 >= failure_threshold → OPEN
      OPEN    → 等待 recovery_timeout 秒 → HALF_OPEN
      HALF_OPEN → 成功 → CLOSED
      HALF_OPEN → 失败 → OPEN
    """
    failure_threshold: int = 3
    recovery_timeout: float = 30.0  # 秒
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _state: CircuitState = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self):
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def can_execute(self) -> bool:
        # 直接检查内部状态（不触发 state 属性的超时转换逻辑）
        return self._state != CircuitState.OPEN

    def __call__(self, func):
        """作为装饰器使用"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not self.can_execute():
                raise CircuitOpenError(f"Circuit breaker is OPEN ({self._failure_count} failures)")
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise
        return wrapper


class CircuitOpenError(Exception):
    """熔断器打开时抛出的异常"""
    pass


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    base_delay: float = 1.0          # 基础延迟（秒）
    max_delay: float = 30.0          # 最大延迟
    exponential_backoff: bool = True  # 指数退避
    retryable_exceptions: tuple = (Exception,)  # 哪些异常触发重试
    on_retry: Optional[Callable] = None  # 每次重试时的回调(exception, attempt)


def retry_with_fallback(
    config: Optional[RetryConfig] = None,
    fallback_value: Any = None,
    fallback_factory: Optional[Callable] = None,
):
    """
    带重试和降级执行的装饰器。

    用法:
        @retry_with_fallback(config=RetryConfig(max_retries=2), fallback_value="default")
        def call_llm():
            ...

        @retry_with_fallback(fallback_factory=lambda e: get_mock_response())
        def call_llm():
            ...
    """
    if config is None:
        config = RetryConfig()

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e
                    if attempt < config.max_retries:
                        delay = _compute_delay(attempt, config)
                        logger.warning(
                            "[Retry] Attempt %d/%d failed: %s. Retrying in %.1fs",
                            attempt + 1, config.max_retries + 1, e, delay,
                        )
                        if config.on_retry:
                            config.on_retry(e, attempt + 1)
                        time.sleep(delay)
                    else:
                        logger.error(
                            "[Retry] All %d attempts failed. Last error: %s",
                            config.max_retries + 1, e,
                        )

            # 所有重试失败，尝试降级
            if fallback_factory is not None:
                try:
                    return fallback_factory(last_exception)
                except Exception as fallback_error:
                    logger.error("[Fallback] Fallback also failed: %s", fallback_error)

            if fallback_value is not None:
                return fallback_value

            raise last_exception
        return wrapper
    return decorator


def _compute_delay(attempt: int, config: RetryConfig) -> float:
    if config.exponential_backoff:
        delay = config.base_delay * (2 ** attempt)
    else:
        delay = config.base_delay
    return min(delay, config.max_delay)


@dataclass
class FallbackProvider:
    """
    LLM Provider 链式降级。

    按优先级尝试多个 Provider，当前一个失败时自动切换到下一个。

    用法:
        provider = FallbackProvider([anthropic_provider, openai_provider, mock_provider])
        response = provider.complete("Hello")
    """
    providers: List[Any] = field(default_factory=list)
    circuit_breakers: List[CircuitBreaker] = field(default_factory=list)

    def __post_init__(self):
        if not self.circuit_breakers:
            self.circuit_breakers = [CircuitBreaker() for _ in self.providers]

    def complete(self, prompt: str, **kwargs) -> Any:
        """按优先级尝试所有 Provider"""
        errors = []
        for i, (provider, cb) in enumerate(zip(self.providers, self.circuit_breakers)):
            if not cb.can_execute():
                continue
            try:
                result = provider.complete(prompt, **kwargs)
                cb.record_success()
                return result
            except Exception as e:
                cb.record_failure()
                errors.append(f"Provider {i} ({provider.__class__.__name__}): {e}")
                logger.warning("[FallbackProvider] Provider %d failed: %s", i, e)

        # 所有 Provider 都失败
        error_summary = "; ".join(errors)
        raise RuntimeError(f"All LLM providers failed: {error_summary}")

    def get_name(self) -> str:
        names = [p.get_name() if hasattr(p, 'get_name') else p.__class__.__name__
                 for p in self.providers]
        return f"FallbackProvider({ ' → '.join(names) })"


def graceful_degrade(
    default_return: Any = None,
    exceptions: tuple = (Exception,),
    log_level: int = logging.WARNING,
):
    """
    通用降级装饰器 — 发生异常时返回默认值而不是崩溃。

    用法:
        @graceful_degrade(default_return={"status": "degraded"})
        def risky_operation():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                logger.log(log_level, "[GracefulDegrade] %s failed: %s. Returning default.", func.__name__, e)
                return default_return
        return wrapper
    return decorator
