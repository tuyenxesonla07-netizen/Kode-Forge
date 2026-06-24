"""
tools/quality/convergence_detector.py

收敛检测器 — 检测修复循环是否收敛

核心逻辑: 不仅检查迭代次数，还检查质量趋势。
如果连续 2 次修复后质量未提升，提前终止。
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class ConvergenceResult:
    """收敛检测结果"""
    should_continue: bool          # 是否继续修复
    reason: str                    # 终止/继续原因
    iteration: int                 # 当前迭代
    quality_score: float           # 当前质量
    trend: str                     # "improving", "stagnant", "declining"


class ConvergenceDetector:
    """收敛检测器"""

    def __init__(self, max_iterations: int = 3, min_improvement: float = 0.02):
        self.max_iterations = max_iterations
        self.min_improvement = min_improvement  # 最小改进幅度
        self._score_history: List[float] = []

    def record_score(self, score: float) -> None:
        """记录质量评分"""
        self._score_history.append(score)

    def should_continue(
        self,
        iteration: int,
        quality_score: float,
        has_critical: bool,
    ) -> Tuple[bool, str]:
        """
        判定是否继续修复循环

        终止条件（满足任一即终止）:
          1. 质量达标 AND 无 critical 问题 → 交付
          2. 迭代次数 >= max → 挂起，人工介入
          3. 出现 critical 问题且无法自动修复 → 挂起
          4. 连续 2 次质量未提升 → 挂起
        """
        self.record_score(quality_score)

        # 条件 1: 质量达标
        if quality_score >= 0.8 and not has_critical:
            return False, "质量达标，终止循环，准备交付"

        # 条件 2: 达到最大迭代
        if iteration >= self.max_iterations:
            return False, f"达到最大迭代次数 {self.max_iterations}，挂起人工介入"

        # 条件 3: critical 问题
        if has_critical:
            return False, "存在 critical 级别问题，挂起人工介入"

        # 条件 4: 连续 2 次未提升
        if len(self._score_history) >= 3:
            last_3 = self._score_history[-3:]
            if last_3[-1] <= last_3[-2] and last_3[-2] <= last_3[-3]:
                return False, f"连续 2 次质量未提升 ({last_3})，挂起人工介入"

        # 继续修复
        trend = self._calculate_trend()
        return True, f"继续修复 (迭代 {iteration + 1}, 趋势: {trend})"

    def _calculate_trend(self) -> str:
        """计算质量趋势"""
        if len(self._score_history) < 2:
            return "unknown"

        recent = self._score_history[-3:]
        if recent[-1] > recent[0] + self.min_improvement:
            return "improving"
        elif recent[-1] < recent[0] - self.min_improvement:
            return "declining"
        else:
            return "stagnant"

    def get_history(self) -> List[float]:
        """获取评分历史"""
        return list(self._score_history)

    def reset(self):
        """重置检测器"""
        self._score_history.clear()
