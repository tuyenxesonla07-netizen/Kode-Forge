"""Tests for QualityEvaluator and ConvergenceDetector."""

import pytest

from tools.quality.quality_evaluator import (
    QualityEvaluator,
    ReviewResult,
    QualityReport,
)
from tools.quality.convergence_detector import (
    ConvergenceDetector,
    ConvergenceResult,
)


# ---------------------------------------------------------------------------
# QualityEvaluator
# ---------------------------------------------------------------------------

class TestQualityEvaluator:
    def _make_review(self, module: str, verdict: str = "pass",
                     issues: list = None, confidence: float = 0.9) -> ReviewResult:
        return ReviewResult(
            module=module,
            verdict=verdict,
            issues=issues or [],
            confidence=confidence,
        )

    def test_all_pass(self):
        evaluator = QualityEvaluator()
        results = [
            self._make_review("auth", "pass"),
            self._make_review("payment", "pass"),
        ]
        report = evaluator.evaluate(results)
        assert report.passed is True
        assert report.has_critical is False

    def test_one_fails(self):
        evaluator = QualityEvaluator()
        results = [
            self._make_review("auth", "pass"),
            self._make_review("payment", "fail"),
        ]
        report = evaluator.evaluate(results)
        assert report.passed is False

    def test_critical_issue_fails(self):
        evaluator = QualityEvaluator()
        results = [
            self._make_review("auth", "pass", issues=[{"severity": "critical"}]),
            self._make_review("payment", "pass"),
        ]
        report = evaluator.evaluate(results)
        assert report.passed is False
        assert report.has_critical is True

    def test_quality_score_all_pass(self):
        evaluator = QualityEvaluator()
        results = [
            self._make_review("auth", "pass", confidence=0.95),
            self._make_review("payment", "pass", confidence=0.9),
        ]
        report = evaluator.evaluate(results)
        assert report.quality_score > 0.8

    def test_quality_score_with_issues(self):
        evaluator = QualityEvaluator()
        results = [
            self._make_review("auth", "pass", issues=[
                {"severity": "major"},
                {"severity": "minor"},
            ]),
        ]
        report = evaluator.evaluate(results)
        assert report.quality_score < 1.0

    def test_empty_results(self):
        evaluator = QualityEvaluator()
        report = evaluator.evaluate([])
        assert report.quality_score == 0.0

    def test_module_results_dict(self):
        evaluator = QualityEvaluator()
        results = [
            self._make_review("auth", "pass"),
            self._make_review("payment", "fail"),
        ]
        report = evaluator.evaluate(results)
        assert "auth" in report.module_results
        assert "payment" in report.module_results
        assert report.module_results["auth"].verdict == "pass"
        assert report.module_results["payment"].verdict == "fail"

    def test_recommendation_pass(self):
        evaluator = QualityEvaluator()
        results = [self._make_review("auth", "pass", confidence=0.9)]
        report = evaluator.evaluate(results)
        assert "通过" in report.recommendation or "pass" in report.recommendation.lower()

    def test_recommendation_fix(self):
        evaluator = QualityEvaluator()
        results = [self._make_review("auth", "fail")]
        report = evaluator.evaluate(results)
        assert "修复" in report.recommendation or "fix" in report.recommendation.lower()

    def test_convergence_status_in_report(self):
        evaluator = QualityEvaluator()
        results = [self._make_review("auth", "pass", confidence=0.9)]
        report = evaluator.evaluate(results)
        assert report.convergence_status != ""


# ---------------------------------------------------------------------------
# ReviewResult
# ---------------------------------------------------------------------------

class TestReviewResult:
    def test_has_critical_true(self):
        r = ReviewResult(module="auth", verdict="pass", issues=[{"severity": "critical"}])
        assert r.has_critical is True

    def test_has_critical_false(self):
        r = ReviewResult(module="auth", verdict="pass", issues=[{"severity": "major"}])
        assert r.has_critical is False

    def test_has_critical_empty(self):
        r = ReviewResult(module="auth", verdict="pass")
        assert r.has_critical is False

    def test_critical_count(self):
        r = ReviewResult(module="auth", verdict="pass", issues=[
            {"severity": "critical"},
            {"severity": "critical"},
            {"severity": "major"},
        ])
        assert r.critical_count == 2

    def test_major_count(self):
        r = ReviewResult(module="auth", verdict="pass", issues=[
            {"severity": "major"},
            {"severity": "major"},
            {"severity": "minor"},
        ])
        assert r.major_count == 2


# ---------------------------------------------------------------------------
# ConvergenceDetector
# ---------------------------------------------------------------------------

class TestConvergenceDetector:
    def test_quality_sufficient_stops(self):
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.9, has_critical=False
        )
        assert should_continue is False
        assert "达标" in reason or "达标" in reason

    def test_max_iterations_stops(self):
        detector = ConvergenceDetector(max_iterations=3)
        should_continue, reason = detector.should_continue(
            iteration=3, quality_score=0.5, has_critical=False
        )
        assert should_continue is False
        assert "最大迭代" in reason or "迭代" in reason

    def test_critical_stops(self):
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.5, has_critical=True
        )
        assert should_continue is False
        assert "critical" in reason.lower() or "Critical" in reason

    def test_continue_improving(self):
        detector = ConvergenceDetector()
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.5, has_critical=False
        )
        assert should_continue is True

    def test_stagnant_stops(self):
        detector = ConvergenceDetector()
        # Record 3 scores that are flat
        detector.record_score(0.5)
        detector.record_score(0.5)
        detector.record_score(0.5)
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.5, has_critical=False
        )
        assert should_continue is False
        assert "未提升" in reason or "stagnant" in reason.lower()

    def test_declining_stops(self):
        detector = ConvergenceDetector()
        detector.record_score(0.7)
        detector.record_score(0.6)
        detector.record_score(0.5)
        should_continue, reason = detector.should_continue(
            iteration=0, quality_score=0.4, has_critical=False
        )
        assert should_continue is False

    def test_history_tracking(self):
        detector = ConvergenceDetector()
        detector.record_score(0.5)
        detector.record_score(0.6)
        assert detector.get_history() == [0.5, 0.6]

    def test_reset(self):
        detector = ConvergenceDetector()
        detector.record_score(0.5)
        detector.reset()
        assert detector.get_history() == []

    def test_trend_improving(self):
        detector = ConvergenceDetector()
        detector.record_score(0.3)
        detector.record_score(0.5)
        assert detector._calculate_trend() == "improving"

    def test_trend_declining(self):
        detector = ConvergenceDetector()
        detector.record_score(0.7)
        detector.record_score(0.5)
        assert detector._calculate_trend() == "declining"

    def test_trend_stagnant(self):
        detector = ConvergenceDetector()
        detector.record_score(0.5)
        detector.record_score(0.5)
        assert detector._calculate_trend() == "stagnant"

    def test_trend_unknown(self):
        detector = ConvergenceDetector()
        assert detector._calculate_trend() == "unknown"

    def test_custom_max_iterations(self):
        detector = ConvergenceDetector(max_iterations=5)
        assert detector.max_iterations == 5

    def test_custom_min_improvement(self):
        detector = ConvergenceDetector(min_improvement=0.05)
        assert detector.min_improvement == 0.05


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestQualityIntegration:
    def test_full_evaluation_cycle(self):
        """Test a complete evaluate → convergence → decide cycle."""
        evaluator = QualityEvaluator()
        detector = ConvergenceDetector(max_iterations=3)

        # Round 1: low quality
        results = [
            ReviewResult(module="auth", verdict="fail", issues=[{"severity": "major", "description": "missing interface"}]),
        ]
        report = evaluator.evaluate(results, iteration=0)
        assert report.passed is False

        should_continue, _ = detector.should_continue(
            iteration=0, quality_score=report.quality_score, has_critical=report.has_critical
        )
        assert should_continue is True

        # Round 2: improved
        results = [
            ReviewResult(module="auth", verdict="pass", confidence=0.9),
        ]
        report = evaluator.evaluate(results, iteration=1)
        should_continue, _ = detector.should_continue(
            iteration=1, quality_score=report.quality_score, has_critical=report.has_critical
        )
        # May or may not continue depending on score

    def test_convergence_triggers_after_improvement(self):
        """Once quality is high enough, convergence should trigger."""
        detector = ConvergenceDetector()
        detector.record_score(0.85)
        detector.record_score(0.9)
        should_continue, reason = detector.should_continue(
            iteration=2, quality_score=0.9, has_critical=False
        )
        assert should_continue is False
        assert "达标" in reason or "达标" in reason
