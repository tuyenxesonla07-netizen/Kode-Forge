"""
tools/quality/quality_evaluator.py

质量评估器 — 评估代码审查结果，判定是否通过

整合质量门禁和收敛检测，输出完整的评估报告。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from tools.quality.convergence_detector import ConvergenceDetector
from tools.compiler.quality_gate_gen import QualityGateSuite


@dataclass
class ReviewResult:
    """单个模块的审查结果"""
    module: str
    verdict: str                   # "pass" | "fail" | "conditional"
    issues: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def has_critical(self) -> bool:
        return any(i.get("severity") == "critical" for i in self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.get("severity") == "critical")

    @property
    def major_count(self) -> int:
        return sum(1 for i in self.issues if i.get("severity") == "major")


@dataclass
class QualityReport:
    """完整的质量评估报告"""
    passed: bool
    quality_score: float
    has_critical: bool
    gate_results: List[Dict[str, Any]]
    failed_gates: List[Dict[str, Any]]
    module_results: Dict[str, ReviewResult]
    convergence_status: str
    recommendation: str


class QualityEvaluator:
    """质量评估器"""

    def __init__(self, message_bus=None, quality_gates: Optional[QualityGateSuite] = None) -> None:
        self.message_bus = message_bus
        self.convergence_detector = ConvergenceDetector()
        self.quality_gates = quality_gates

    def evaluate(self, review_results: List[ReviewResult],
                 iteration: int = 0) -> QualityReport:
        """
        评估审查结果

        评估维度:
          1. 各模块审查是否通过
          2. 跨模块接口是否一致
          3. 是否有 critical 问题
          4. 质量门禁是否通过
          5. 收敛检测
        """
        # 汇总指标
        module_results = {r.module: r for r in review_results}
        has_critical = any(r.has_critical for r in review_results)
        all_passed = all(r.verdict == "pass" for r in review_results)

        # 计算质量评分
        quality_score = self._calculate_quality_score(review_results)

        # 质量门禁评估
        gate_results = []
        failed_gates = []
        if self.quality_gates:
            metrics = self._build_metrics(review_results)
            gate_eval = self.quality_gates.evaluate(metrics)
            gate_results = gate_eval["gate_results"]
            failed_gates = gate_eval["failed_gates"]
            gates_passed = gate_eval["passed"]
        else:
            # 无门禁时：仍需满足基本质量标准（score >= 0.5）
            gates_passed = (all_passed and not has_critical
                            and quality_score >= 0.5)
        # 收敛检测
        should_continue, convergence_status = self.convergence_detector.should_continue(
            iteration=iteration,
            quality_score=quality_score,
            has_critical=has_critical,
        )

        # 综合判定
        overall_passed = all_passed and not has_critical and gates_passed

        # 建议
        if overall_passed:
            recommendation = "审查通过，可以交付"
        elif not should_continue:
            recommendation = "修复循环终止，需要人工介入"
        else:
            recommendation = f"需要继续修复 (迭代 {iteration + 1})"

        return QualityReport(
            passed=overall_passed,
            quality_score=quality_score,
            has_critical=has_critical,
            gate_results=gate_results,
            failed_gates=failed_gates,
            module_results=module_results,
            convergence_status=convergence_status,
            recommendation=recommendation,
        )

    def _calculate_quality_score(self, review_results: List[ReviewResult]) -> float:
        """
        计算综合质量评分 (0.0 ~ 1.0)

        算法:
          - 基础分: 通过模块数 / 总模块数
          - 扣分: critical 问题 * 0.2, major 问题 * 0.1, minor 问题 * 0.02
          - 加权: 平均置信度
        """
        if not review_results:
            return 0.0

        total = len(review_results)
        passed = sum(1 for r in review_results if r.verdict == "pass")
        base_score = passed / total

        # 问题扣分
        penalty = 0.0
        for r in review_results:
            penalty += r.critical_count * 0.2
            penalty += r.major_count * 0.1
            penalty += len([i for i in r.issues if i.get("severity") == "minor"]) * 0.02

        # 置信度加权
        avg_confidence = sum(r.confidence for r in review_results) / total

        score = max(0.0, base_score - penalty * 0.5)
        score = score * 0.7 + avg_confidence * 0.3

        return min(1.0, score)

    def _build_metrics(self, review_results: List[ReviewResult]) -> Dict[str, Any]:
        """构建质量门禁评估用的指标"""
        metrics = {
            "all_modules_passed": all(r.verdict == "pass" for r in review_results),
            "critical_issues_count": sum(r.critical_count for r in review_results),
            "interface_consistency": self._check_interface_consistency(review_results),
            "quality_score": self._calculate_quality_score(review_results),
            "test_coverage": self._estimate_coverage(review_results),
            "security_score": self._estimate_security_score(review_results),
        }

        # 各模块的验收标准
        for r in review_results:
            metrics[f"{r.module}_acceptance_met"] = r.verdict == "pass"
            metrics[f"{r.module}_state_machine_complete"] = (
                r.verdict == "pass" or "state_machine" not in str(r.metrics)
            )
            metrics[f"{r.module}_compliant"] = r.verdict != "fail"

        return metrics

    def _check_interface_consistency(self, review_results: List[ReviewResult]) -> bool:
        """检查跨模块接口一致性"""
        # 简化：如果所有模块都通过，认为接口一致
        # 实际应该检查各模块引用的接口签名是否一致
        return all(r.verdict == "pass" for r in review_results)

    def _estimate_coverage(self, review_results: List[ReviewResult]) -> float:
        """估算测试覆盖率"""
        # 简化：从审查结果中取平均覆盖率
        coverages = [
            r.metrics.get("coverage", 0.0)
            for r in review_results
            if "coverage" in r.metrics
        ]
        return sum(coverages) / len(coverages) if coverages else 0.7

    def _estimate_security_score(self, review_results: List[ReviewResult]) -> float:
        """估算安全评分"""
        # 简化：如果有安全相关模块，检查其审查结果
        security_modules = ["authentication", "api_integration"]
        sec_results = [r for r in review_results if r.module in security_modules]
        if not sec_results:
            return 0.9  # 默认
        return min(r.confidence for r in sec_results)
