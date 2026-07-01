# tools/workflow/execution.py

"""
执行策略组件 — 重试、恢复、质量循环、熔断器、结果汇总。

从 engine.py 中拆出，使核心引擎文件更聚焦。

本模块包含:
  - RetryPolicy / RecoveryResult / RecoveryManager  (from recovery.py)
  - QualityLoopResult / QualityLoop                   (from quality_loop.py)
  - AgentResult / ResultAggregator                    (from aggregator.py)
  - CircuitState / CircuitBreakerOpenError / CircuitBreaker (from circuit_breaker.py)
"""

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RecoveryManager + RetryPolicy + RecoveryResult
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field


@dataclass
class RetryPolicy:
    """重试策略配置"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential: bool = True
    jitter: bool = True
    retryable_exceptions: tuple = (IOError, TimeoutError, ConnectionError)

    def compute_delay(self, attempt: int) -> float:
        """计算第 attempt 次重试的延迟"""
        if self.exponential:
            delay = self.base_delay * (2 ** attempt)
        else:
            delay = self.base_delay
        delay = min(delay, self.max_delay)
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return delay

    def should_retry(self, exception: Exception) -> bool:
        """判断异常是否可重试"""
        return isinstance(exception, self.retryable_exceptions)


@dataclass
class RecoveryResult:
    """恢复操作结果"""
    success: bool
    strategy: str          # "retry" | "degrade" | "human_fallback" | "failed"
    output: Any = None
    attempts: int = 0
    total_delay: float = 0.0
    final_error: str = ""


class RecoveryManager:
    """
    错误恢复管理器。

    分级策略:
    1. 重试 (retry) — 指数退避
    2. 降级 (degrade) — 切换到备用方案
    3. 人工兜底 (human_fallback) — 转人工处理
    """

    def __init__(
        self,
        policy: RetryPolicy = None,
        degrade_fn: Callable = None,
        human_fn: Callable = None,
    ) -> None:
        self.policy = policy or RetryPolicy()
        self.degrade_fn = degrade_fn
        self.human_fn = human_fn

    async def execute_with_recovery(
        self,
        fn: Callable,
        *args,
        task_context: dict = None,
        **kwargs,
    ) -> RecoveryResult:
        """执行函数，失败时按策略恢复"""
        total_delay = 0.0

        # Phase 1: 重试
        last_error = None
        for attempt in range(self.policy.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(fn):
                    output = await fn(*args, **kwargs)
                else:
                    output = fn(*args, **kwargs)
                return RecoveryResult(
                    success=True,
                    strategy="retry" if attempt == 0 else f"retry_after_{attempt}",
                    output=output,
                    attempts=attempt + 1,
                    total_delay=total_delay,
                )
            except Exception as e:
                last_error = e
                if attempt < self.policy.max_retries and self.policy.should_retry(e):
                    delay = self.policy.compute_delay(attempt)
                    total_delay += delay
                    logger.warning("[Recovery] Attempt %d failed: %s. Retry in %.1fs...",
                                   attempt + 1, e, delay)
                    await asyncio.sleep(delay)
                else:
                    logger.warning("[Recovery] Attempt %d failed: %s. No more retries.",
                                   attempt + 1, e)
                    break

        # Phase 2: 降级
        if self.degrade_fn:
            try:
                logger.info("[Recovery] Attempting degradation...")
                if asyncio.iscoroutinefunction(self.degrade_fn):
                    output = await self.degrade_fn(task_context or {})
                else:
                    output = self.degrade_fn(task_context or {})
                return RecoveryResult(
                    success=True,
                    strategy="degrade",
                    output=output,
                    attempts=self.policy.max_retries + 1,
                    total_delay=total_delay,
                )
            except Exception as e:
                logger.error("[Recovery] Degradation also failed: %s", e)

        # Phase 3: 人工兜底
        if self.human_fn:
            logger.info("[Recovery] Escalating to human...")
            if asyncio.iscoroutinefunction(self.human_fn):
                await self.human_fn(task_context or {})
            else:
                self.human_fn(task_context or {})
            return RecoveryResult(
                success=False,
                strategy="human_fallback",
                attempts=self.policy.max_retries + 1,
                total_delay=total_delay,
                final_error=str(last_error),
            )

        return RecoveryResult(
            success=False,
            strategy="failed",
            attempts=self.policy.max_retries + 1,
            total_delay=total_delay,
            final_error=str(last_error),
        )

    @staticmethod
    def simple_retry(fn: Callable, max_retries: int = 3,
                     delay: float = 1.0, task_context: dict = None) -> Any:
        """简单同步重试"""
        import time
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(delay * (2 ** attempt))
        raise last_error


# ---------------------------------------------------------------------------
# QualityLoop + QualityLoopResult
# ---------------------------------------------------------------------------

@dataclass
class QualityLoopResult:
    """质量循环执行结果"""
    output: str                      # 最终代码输出
    quality_report: Any              # QualityReport
    iterations: int                  # 实际迭代次数
    converged: bool                  # 是否收敛
    history: List[dict]              # 每轮的历史记录


class QualityLoop:
    """
    质量评估 + 自动修复循环。

    对 LLM 生成的代码进行多轮验证和修复:
    - 每轮执行 AST 验证 + 质量评估
    - 不达标时生成修复 prompt 并重新生成
    - 收敛检测器决定是否继续
    """

    def __init__(
        self,
        max_iterations: int = 3,
        quality_threshold: float = 0.8,
        convergence_detector = None,
    ) -> None:
        self.max_iterations = max_iterations
        self.quality_threshold = quality_threshold

        from tools.quality.quality_evaluator import QualityEvaluator
        from tools.quality.ast_validator import ASTValidator

        self.evaluator = QualityEvaluator()
        self.ast_validator = ASTValidator()

        if convergence_detector is None:
            from tools.quality.convergence_detector import ConvergenceDetector
            convergence_detector = ConvergenceDetector(max_iterations=max_iterations)
        self.convergence = convergence_detector

    async def execute_with_quality(
        self,
        node: Any,
        inputs: dict,
        context: dict = None,
    ) -> QualityLoopResult:
        """执行节点 → 评估 → 修复循环"""
        from tools.quality.quality_evaluator import ReviewResult, QualityReport

        context = context or {}
        history: List[dict] = []
        last_output = ""
        last_report: Optional[QualityReport] = None

        for iteration in range(self.max_iterations):
            logger.info(
                "[QualityLoop] Iteration %d/%d for node %s",
                iteration + 1, self.max_iterations, node.id,
            )

            # 1. 执行节点生成代码
            last_output = await self._run_node(node, inputs, context)

            # 2. 评估代码质量
            review = self._review_output(last_output, node, context)
            last_report = self.evaluator.evaluate([review], iteration=iteration)

            history.append({
                "iteration": iteration,
                "output_length": len(last_output),
                "quality_score": last_report.quality_score,
                "passed": last_report.passed,
                "issue_count": len(review.issues),
                "has_critical": review.has_critical,
            })

            logger.info(
                "[QualityLoop] Iteration %d: score=%.2f, passed=%s, issues=%d",
                iteration + 1,
                last_report.quality_score,
                last_report.passed,
                len(review.issues),
            )

            # 3. 收敛检测
            should_continue, reason = self.convergence.should_continue(
                iteration=iteration,
                quality_score=last_report.quality_score,
                has_critical=last_report.has_critical,
            )

            if not should_continue:
                logger.info(
                    "[QualityLoop] Converged at iteration %d: %s",
                    iteration + 1, reason,
                )
                return QualityLoopResult(
                    output=last_output,
                    quality_report=last_report,
                    iterations=iteration + 1,
                    converged=True,
                    history=history,
                )

            # 4. 生成修复 prompt，准备下一轮
            if iteration < self.max_iterations - 1:
                inputs = self._apply_fix_prompt(inputs, review, last_output)

        # 达到最大迭代
        logger.warning(
            "[QualityLoop] Max iterations (%d) reached for node %s. Score: %.2f",
            self.max_iterations, node.id,
            last_report.quality_score if last_report else 0.0,
        )
        return QualityLoopResult(
            output=last_output,
            quality_report=last_report,
            iterations=self.max_iterations,
            converged=False,
            history=history,
        )

    def _review_output(self, code: str, node: Any, context: dict) -> Any:
        """将 LLM 输出转为 ReviewResult"""
        from tools.quality.quality_evaluator import ReviewResult

        spec = self._get_node_spec(node)
        validation = self.ast_validator.validate(code, spec)

        issues = []
        for v_issue in validation.issues:
            issues.append({
                "severity": v_issue.severity,
                "type": v_issue.type,
                "message": v_issue.message,
                "line": v_issue.line,
                "suggestion": v_issue.suggestion,
            })

        if validation.has_critical:
            verdict = "fail"
        elif any(i["severity"] == "major" for i in issues):
            verdict = "conditional"
        else:
            verdict = "pass"

        return ReviewResult(
            module=node.id,
            verdict=verdict,
            issues=issues,
            metrics=validation.metrics,
            confidence=max(0.0, 1.0 - len(issues) * 0.05),
        )

    def _get_node_spec(self, node: Any) -> dict:
        """从节点 config 提取验证用的 spec"""
        spec = {}
        config = getattr(node, "config", {}) or {}
        prompt = config.get("prompt_template", "")

        spec["required_classes"] = config.get("required_classes", [])
        spec["required_functions"] = config.get("required_functions", [])

        module_name = config.get("module_name", "")
        if module_name:
            spec["components"] = [{"name": module_name, "type": "service"}]

        return spec

    def _apply_fix_prompt(
        self,
        inputs: dict,
        review,
        last_output: str,
    ) -> dict:
        """根据 ReviewResult 生成修复 prompt"""
        fix_lines = []
        for issue in review.issues:
            if isinstance(issue, dict):
                severity = issue.get("severity", "minor")
                msg = issue.get("message", str(issue))
                suggestion = issue.get("suggestion", "")
            else:
                severity = issue.severity
                msg = issue.message
                suggestion = issue.suggestion

            icon = "🔴" if severity == "critical" else ("🟡" if severity == "major" else "🔵")
            fix_lines.append(f"{icon} [{severity}] {msg}")
            if suggestion:
                fix_lines.append(f"   → Suggestion: {suggestion}")

        fix_prompt = f"""## Quality Issues Found in Previous Generation

The following issues were detected in the generated code. Please fix ALL of them:

{chr(10).join(fix_lines)}

## Previous Code (with issues)

```python
{last_output}
```

## Instructions

1. Fix ALL issues listed above
2. Ensure the corrected code is complete and executable
3. Maintain the same overall structure and functionality
4. Output ONLY the fixed code, no explanations

## Fixed Code:

"""

        new_inputs = dict(inputs)
        new_inputs["_fix_prompt"] = fix_prompt
        new_inputs["_last_output"] = last_output
        new_inputs["_quality_issues"] = [
            {
                "severity": (i.get("severity", "minor") if isinstance(i, dict) else i.severity),
                "type": (i.get("type", "") if isinstance(i, dict) else i.type),
                "message": (i.get("message", str(i)) if isinstance(i, dict) else i.message),
            }
            for i in review.issues
        ]

        return new_inputs

    async def _run_node(self, node: Any, inputs: dict, context: dict) -> str:
        """执行单个 LLM 节点"""
        from tools.workflow.nodes import LLMNode

        llm_node = LLMNode(
            prompt_template=node.config.get("prompt_template", ""),
            provider=context.get("llm_provider"),
            temperature=node.config.get("temperature", 0.7),
        )

        fix_prompt = inputs.get("_fix_prompt", "")
        if fix_prompt:
            original_prompt = node.config.get("prompt_template", "")
            llm_node.prompt_template = original_prompt + "\n\n" + fix_prompt

        return await llm_node.execute(inputs)


# ---------------------------------------------------------------------------
# ResultAggregator + AgentResult
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """单个 Agent 的产出"""
    agent_id: str
    module_name: str
    components: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "success"       # success | partial | failed
    error: str = ""
    metadata: dict = field(default_factory=dict)


class ResultAggregator:
    """
    子代理结果汇总器。

    收集多个 AgentResult，去重接口，合并组件，检测冲突。

    用法:
        agg = ResultAggregator()
        agg.add(AgentResult(agent_id="auth_expert", module_name="authentication", ...))
        merged = agg.merge()
        conflicts = agg.detect_conflicts()
    """

    def __init__(self) -> None:
        self._results: list[AgentResult] = []

    def add(self, result: AgentResult) -> None:
        """添加一个子代理结果"""
        self._results.append(result)

    def add_many(self, results: list[AgentResult]) -> None:
        """批量添加"""
        self._results.extend(results)

    def merge(self) -> dict[str, AgentResult]:
        """按模块名合并结果"""
        by_module: dict[str, list[AgentResult]] = {}
        for r in self._results:
            by_module.setdefault(r.module_name, []).append(r)

        merged: dict[str, AgentResult] = {}
        for module, results in by_module.items():
            if len(results) == 1:
                merged[module] = results[0]
            else:
                best = max(results, key=lambda r: r.confidence)
                all_components = list(set(
                    c for r in results for c in r.components
                ))
                all_interfaces = list(set(
                    i for r in results for i in r.interfaces
                ))
                merged[module] = AgentResult(
                    agent_id=best.agent_id,
                    module_name=module,
                    components=all_components,
                    interfaces=all_interfaces,
                    acceptance_criteria=best.acceptance_criteria,
                    confidence=best.confidence,
                    status=best.status,
                    metadata={"merged_from": [r.agent_id for r in results]},
                )

        return merged

    def detect_conflicts(self) -> list[dict]:
        """检测接口冲突"""
        iface_to_modules: dict[str, list[str]] = {}
        for result in self._results:
            for iface in result.interfaces:
                iface_to_modules.setdefault(iface, []).append(result.module_name)

        conflicts = []
        for iface, modules in iface_to_modules.items():
            unique_modules = list(set(modules))
            if len(unique_modules) > 1:
                conflicts.append({
                    "interface": iface,
                    "modules": unique_modules,
                    "severity": "warning",
                    "detail": f"Interface '{iface}' defined in multiple modules: {unique_modules}",
                })

        return conflicts

    def get_summary(self) -> dict:
        """汇总统计"""
        total = len(self._results)
        success = sum(1 for r in self._results if r.status == "success")
        failed = sum(1 for r in self._results if r.status == "failed")
        partial = sum(1 for r in self._results if r.status == "partial")
        avg_confidence = (
            sum(r.confidence for r in self._results) / total if total else 0.0
        )

        return {
            "total_agents": total,
            "success": success,
            "partial": partial,
            "failed": failed,
            "avg_confidence": round(avg_confidence, 2),
            "modules_covered": len(set(r.module_name for r in self._results)),
        }

    @property
    def results(self) -> list[AgentResult]:
        return list(self._results)

    def __len__(self) -> int:
        return len(self._results)


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Circuit breaker 断路异常"""
    pass


class CircuitBreaker:
    """
    Circuit Breaker — 防止持续调用故障服务。

    状态机:
      CLOSED (正常) → 连续 N 次失败 → OPEN (断路)
      OPEN → 等待 recovery_timeout 秒 → HALF_OPEN (试探)
      HALF_OPEN → 成功 → CLOSED
      HALF_OPEN → 失败 → OPEN

    用法:
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        result = await cb.call(some_async_func, *args, **kwargs)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 1,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """通过 circuit breaker 调用函数"""
        async with self._lock:
            self._check_state_transition()

            if self._state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN. "
                    f"Recovery in {self.recovery_timeout}s. "
                    f"Failures: {self._failure_count}"
                )

        # 在锁外执行实际调用
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            async with self._lock:
                self._on_success()

            return result

        except Exception as e:
            async with self._lock:
                self._on_failure()
            raise

    def _check_state_transition(self) -> None:
        """检查是否需要状态转换"""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time is not None:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    logger.info(
                        "[CircuitBreaker] Transitioning to HALF_OPEN "
                        "(recovery_timeout=%.1fs elapsed=%.1fs)",
                        self.recovery_timeout, elapsed,
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0

    def _on_success(self) -> None:
        """调用成功"""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                logger.info("[CircuitBreaker] Transitioning to CLOSED (success in HALF_OPEN)")
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        else:
            self._failure_count = 0

    def _on_failure(self) -> None:
        """调用失败"""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning("[CircuitBreaker] Transitioning to OPEN (failure in HALF_OPEN)")
            self._state = CircuitState.OPEN
            self._success_count = 0
        elif self._failure_count >= self.failure_threshold:
            logger.warning(
                "[CircuitBreaker] Transitioning to OPEN "
                "(failures=%d >= threshold=%d)",
                self._failure_count, self.failure_threshold,
            )
            self._state = CircuitState.OPEN

    def reset(self) -> None:
        """手动重置 circuit breaker"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
