# tests/workflow/test_recovery.py
"""Tests for RecoveryManager + RetryPolicy — error recovery and degradation."""

import asyncio

import pytest

from tools.workflow.engine import RecoveryManager, RetryPolicy


class TestRetryPolicy:
    def test_exponential_delay(self):
        policy = RetryPolicy(base_delay=1.0, exponential=True, jitter=False)
        assert policy.compute_delay(0) == 1.0
        assert policy.compute_delay(1) == 2.0
        assert policy.compute_delay(2) == 4.0

    def test_max_delay_cap(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=5.0, exponential=True, jitter=False)
        assert policy.compute_delay(10) == 5.0

    def test_should_retry(self):
        policy = RetryPolicy()
        assert policy.should_retry(ConnectionError("timeout")) is True
        assert policy.should_retry(ValueError("bad input")) is False


class TestRecoveryManager:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        rm = RecoveryManager()
        result = await rm.execute_with_recovery(lambda: "success")
        assert result.success is True
        assert result.strategy == "retry"
        assert result.output == "success"

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("timeout")
            return "ok"

        policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)
        rm = RecoveryManager(policy=policy)
        result = await rm.execute_with_recovery(flaky)
        assert result.success is True
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_degradation(self):
        def fail():
            raise ConnectionError("timeout")

        def degrade(ctx):
            return "cached_result"

        policy = RetryPolicy(max_retries=1, base_delay=0.01, jitter=False)
        rm = RecoveryManager(policy=policy, degrade_fn=degrade)
        result = await rm.execute_with_recovery(fail)
        assert result.success is True
        assert result.strategy == "degrade"
        assert result.output == "cached_result"

    @pytest.mark.asyncio
    async def test_human_fallback(self):
        def fail():
            raise ConnectionError("timeout")

        human_called = False

        async def human(ctx):
            nonlocal human_called
            human_called = True

        policy = RetryPolicy(max_retries=1, base_delay=0.01, jitter=False)
        rm = RecoveryManager(policy=policy, human_fn=human)
        result = await rm.execute_with_recovery(fail)
        assert human_called is True
        assert result.strategy == "human_fallback"

    @pytest.mark.asyncio
    async def test_all_strategies_fail(self):
        def fail():
            raise ConnectionError("timeout")

        policy = RetryPolicy(max_retries=1, base_delay=0.01, jitter=False)
        rm = RecoveryManager(policy=policy)
        result = await rm.execute_with_recovery(fail)
        assert result.success is False
        assert result.strategy == "failed"
