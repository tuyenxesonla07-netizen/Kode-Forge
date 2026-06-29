# tools/eval/runner.py

"""
Eval Runner — 运行所有测试用例并生成报告。

用法:
    from tools.eval import EvalRunner, EVAL_CASES

    runner = EvalRunner()
    report = runner.run_all()
    print(report.render_table())
"""

from __future__ import annotations

import copy
import json
import logging
import random
from dataclasses import dataclass
from typing import Callable

from tools.eval.cases import EVAL_CASES
from tools.eval.assertions import ASSERTION_FUNCTIONS
from tools.eval.report import EvalReport

logger = logging.getLogger(__name__)


class EvalRunner:
    """
    评估运行器。

    运行所有 EVAL_CASES，收集结果，生成 EvalReport。

    隔离模式 (isolate=True):
        每个 case 运行在独立的上下文中，避免前一个 case 的状态污染后一个。
        推荐在测试有副作用的 pipeline 时启用。
    """

    def __init__(self, run_pipeline_fn: Callable = None, verbose: bool = True,
                 isolate: bool = False):
        """
        Args:
            run_pipeline_fn: 运行流水线的函数，接收 input 字符串，返回 result 字典。
                             为 None 时使用 mock 结果（用于测试）。
            verbose: 是否打印进度
            isolate: 是否启用每 case 隔离（深拷贝 context）
        """
        self.run_pipeline_fn = run_pipeline_fn
        self.verbose = verbose
        self.isolate = isolate

    def run_case(self, case: dict, context: dict = None) -> dict:
        """运行单个测试用例"""
        case_id = case["id"]
        user_input = case["input"]

        if self.verbose:
            print(f"  Running: {case_id}...", end=" ")

        try:
            # 隔离模式：深拷贝 context 防止 case 间污染
            if self.isolate and context is not None:
                context = copy.deepcopy(context)

            if self.run_pipeline_fn:
                result = self.run_pipeline_fn(user_input, context=context)
            else:
                result = self._mock_result(case)

            # 执行所有检查
            checks = []
            for check_name in case.get("checks", []):
                check_fn = ASSERTION_FUNCTIONS.get(check_name)
                if check_fn:
                    check_result = check_fn(result, case)
                    checks.append({
                        "name": check_name,
                        "passed": check_result.passed,
                        "detail": check_result.detail,
                    })

            passed = all(c["passed"] for c in checks)
            if self.verbose:
                print("PASS" if passed else "FAIL")

            return {
                "id": case_id,
                "input": user_input[:80],
                "passed": passed,
                "checks": checks,
                "result_summary": result.get("summary", ""),
            }

        except Exception as e:
            if self.verbose:
                print(f"ERROR: {e}")
            return {
                "id": case_id,
                "input": user_input[:80],
                "passed": False,
                "checks": [{"name": "error", "passed": False, "detail": str(e)}],
                "result_summary": "",
            }

    def run_all(self, cases: list = None, verbose: int = None,
                context: dict = None) -> EvalReport:
        """
        运行所有测试用例并生成报告。

        Args:
            cases: 自定义用例列表（默认使用 EVAL_CASES）
            verbose: 是否打印进度
            context: 共享上下文（isolate=True 时会为每个 case 深拷贝）
        """
        if cases is None:
            cases = EVAL_CASES
        if verbose is not None:
            self.verbose = verbose

        if self.verbose:
            print(f"\n{'='*60}")
            print(f"  Running {len(cases)} eval cases...")
            if self.isolate:
                print(f"  Isolation: ON (deep copy per case)")
            print(f"{'='*60}")

        results = []
        for case in cases:
            result = self.run_case(case, context=context)
            results.append(result)

        return EvalReport.from_results(results)

    def _mock_result(self, case: dict) -> dict:
        """
        生成 Mock 结果（用于测试框架本身）。

        根据 case 的 checks 生成合理的 mock 数据。
        """
        result = {
            "generated_modules": [],
            "code_artifact": {},
            "blocked": False,
            "pii_found": [],
            "steps": 0,
            "iterations": 0,
            "max_steps": 10,
            "max_iterations": 3,
            "tools_used": [],
            "intent": "",
            "summary": "mock result",
        }

        # 根据 case 填充 mock 数据
        if "expected_modules" in case:
            result["generated_modules"] = case["expected_modules"]
            result["code_artifact"] = {
                mod: f"# Module: {mod}\nclass {mod.title()}Service:\n    '''{mod} service'''\n    pass\n"
                for mod in case["expected_modules"]
            }

        if case.get("expected_blocked"):
            result["blocked"] = True

        if "expected_pii_found" in case:
            result["pii_found"] = case["expected_pii_found"]

        if "expected_intent" in case:
            result["intent"] = case["expected_intent"]

        if "expected_tools" in case:
            result["tools_used"] = case["expected_tools"]

        result["steps"] = random.randint(3, 8)
        result["iterations"] = random.randint(1, 3)

        return result


class ABTestRunner:
    """
    A/B 对比运行器。

    对同一组测试用例运行两个 pipeline 配置，对比通过率。

    用法:
        runner = ABTestRunner()
        report = runner.compare(
            pipeline_a=run_pipeline_v1,
            pipeline_b=run_pipeline_v2,
            cases=EVAL_CASES,
        )
        print(report.render_table())
    """

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def compare(
        self,
        pipeline_a: Callable,
        pipeline_b: Callable,
        cases: list = None,
        context_a: dict = None,
        context_b: dict = None,
    ) -> "ABTestReport":
        """
        对比两个 pipeline 配置。

        Args:
            pipeline_a: 基准 pipeline 函数
            pipeline_b: 对比 pipeline 函数
            cases: 测试用例列表
            context_a: pipeline A 的共享上下文
            context_b: pipeline B 的共享上下文

        Returns:
            ABTestReport with comparison results
        """
        if cases is None:
            from tools.eval.cases import EVAL_CASES
            cases = EVAL_CASES

        runner_a = EvalRunner(run_pipeline_fn=pipeline_a, verbose=False, isolate=True)
        runner_b = EvalRunner(run_pipeline_fn=pipeline_b, verbose=False, isolate=True)

        results_a = runner_a.run_all(cases, context=context_a, verbose=False)
        results_b = runner_b.run_all(cases, context=context_b, verbose=False)

        return ABTestReport(
            label_a="Pipeline A",
            label_b="Pipeline B",
            results_a=results_a,
            results_b=results_b,
        )


@dataclass
class ABTestReport:
    """A/B 对比报告"""
    label_a: str
    label_b: str
    results_a: "EvalReport"
    results_b: "EvalReport"

    @property
    def winner(self) -> str:
        """返回通过率更高的 pipeline"""
        if self.results_a.pass_percentage >= self.results_b.pass_percentage:
            return self.label_a
        return self.label_b

    @property
    def delta(self) -> float:
        """返回通过率差值"""
        return round(self.results_a.pass_percentage - self.results_b.pass_percentage, 1)

    def render_table(self) -> str:
        """渲染对比表格"""
        lines = [
            "",
            "=" * 70,
            f"  A/B COMPARISON: {self.label_a} vs {self.label_b}",
            "=" * 70,
            f"  {self.label_a}: {self.results_a.pass_rate} ({self.results_a.pass_percentage}%)",
            f"  {self.label_b}: {self.results_b.pass_rate} ({self.results_b.pass_percentage}%)",
            f"  Winner: {self.winner} (delta: {self.delta:+.1f}%)",
            "-" * 70,
        ]

        # Per-case comparison
        a_cases = {r["id"]: r for r in self.results_a.per_case_results}
        b_cases = {r["id"]: r for r in self.results_b.per_case_results}

        for case_id in a_cases:
            a_pass = a_cases[case_id]["passed"]
            b_pass = b_cases.get(case_id, {}).get("passed", False)
            mark = "=" if a_pass == b_pass else ("+" if a_pass else "-")
            status = "same" if a_pass == b_pass else ("A wins" if a_pass else "B wins")
            lines.append(f"    {mark} {case_id:<35} A:{'Y' if a_pass else 'N'} B:{'Y' if b_pass else 'N'} [{status}]")

        lines.append("")
        lines.append("=" * 70)
        return "\n".join(lines)

    def to_json(self) -> str:
        """导出 JSON"""
        return json.dumps({
            "label_a": self.label_a,
            "label_b": self.label_b,
            "summary": {
                "a_pass_rate": self.results_a.pass_rate,
                "a_pass_percentage": self.results_a.pass_percentage,
                "b_pass_rate": self.results_b.pass_rate,
                "b_pass_percentage": self.results_b.pass_percentage,
                "winner": self.winner,
                "delta": self.delta,
            },
        }, ensure_ascii=False, indent=2)
