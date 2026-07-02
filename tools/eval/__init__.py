# tools/eval/__init__.py

"""
Eval — 自动化评估系统。

参考 wsk-agent 的课程评估设计：
- Eval Cases: 25 个测试用例（模块生成、安全、预算、收敛）
- Behavioral Assertions: 行为检查函数
- Eval Runner: 运行所有用例，收集结果
- Eval Report: 生成评估报告

用法:
    from tools.eval import EvalRunner, EVAL_CASES

    runner = EvalRunner()
    report = runner.run_all()
    print(report.render_table())

CLI:
    python -m tools.eval                # 运行全部用例
    python -m tools.eval --json         # 输出 JSON 格式
    python -m tools.eval --cases module_gen_basic code_compiles  # 运行指定用例
"""

from tools.eval.cases import EVAL_CASES
from tools.eval.assertions import BehavioralCheckResult
from tools.eval.runner import EvalRunner
from tools.eval.report import EvalReport

__all__ = ["EVAL_CASES", "BehavioralCheckResult", "EvalRunner", "EvalReport"]


def _cli() -> None:
    """CLI entry point: python -m tools.eval"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Eval Suite — behavioral test runner")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--cases", nargs="+", metavar="ID", help="Run specific case IDs only")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    # Filter cases if requested
    cases = None
    if args.cases:
        case_set = set(args.cases)
        cases = [c for c in EVAL_CASES if c["id"] in case_set]
        if not cases:
            print("No matching cases found. Available IDs:", file=sys.stderr)
            for c in EVAL_CASES:
                print(f"  {c['id']}", file=sys.stderr)
            sys.exit(1)

    runner = EvalRunner(verbose=not args.quiet)
    report = runner.run_all(cases=cases)

    if args.json:
        print(report.to_json())
    else:
        print(report.render_table())
        print(f"\nPass rate: {report.pass_rate} ({report.pass_percentage}%)")

    sys.exit(0 if report.pass_percentage >= 60 else 1)


if __name__ == "__main__":
    _cli()
