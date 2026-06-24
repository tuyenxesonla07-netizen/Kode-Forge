# tools/quality/__init__.py

"""
Quality Gate — 质量门禁评估

  QualityEvaluator  — 评估审查结果，判定是否通过
  ConvergenceDetector — 检测修复循环是否收敛
  ReviewResult      — 审查结果数据结构
"""

from tools.quality.quality_evaluator import QualityEvaluator, ReviewResult
from tools.quality.convergence_detector import ConvergenceDetector

__all__ = ["QualityEvaluator", "ReviewResult", "ConvergenceDetector"]
