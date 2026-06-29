# tools/eval/assertions.py

"""
行为检查函数。

每个检查函数接收 AgentResult + Eval Case，返回 BehavioralCheckResult。
检查类型: intent | tool | blocked | compilable | safety | convergence
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


@dataclass
class BehavioralCheckResult:
    """单个行为检查的结果"""
    check_type: str
    passed: bool
    detail: str
    expected: Any = None
    actual: Any = None


def assert_modules_generated(result: dict, case: dict) -> BehavioralCheckResult:
    """检查是否生成了期望模块"""
    expected = case.get("expected_modules", [])
    generated = result.get("generated_modules", [])
    missing = [m for m in expected if m not in generated]
    passed = len(missing) == 0
    return BehavioralCheckResult(
        check_type="modules_generated",
        passed=passed,
        detail=f"Expected: {expected}, Generated: {generated}, Missing: {missing}" if not passed else "All expected modules generated",
        expected=expected,
        actual=generated,
    )


def assert_code_compiles(result: dict, case: dict) -> BehavioralCheckResult:
    """检查生成的代码是否可编译"""
    code_artifact = result.get("code_artifact", {})
    if not code_artifact:
        return BehavioralCheckResult("code_compiles", False, "No code artifact")

    errors = []
    for module_name, code in code_artifact.items():
        if isinstance(code, str) and code.strip():
            try:
                ast.parse(code)
            except SyntaxError as e:
                errors.append(f"{module_name}: line {e.lineno}: {e.msg}")

    passed = len(errors) == 0
    return BehavioralCheckResult(
        check_type="code_compiles",
        passed=passed,
        detail="All code compiles" if passed else f"Compile errors: {'; '.join(errors)}",
    )


def assert_intent(result: dict, case: dict) -> BehavioralCheckResult:
    """检查路由到的意图是否正确"""
    expected_intent = case.get("expected_intent")
    actual_intent = result.get("intent", "")
    if not expected_intent:
        return BehavioralCheckResult("intent", True, "No intent check required")
    passed = actual_intent == expected_intent
    return BehavioralCheckResult(
        check_type="intent",
        passed=passed,
        detail=f"Intent: {actual_intent}" if passed else f"Expected intent '{expected_intent}', got '{actual_intent}'",
        expected=expected_intent,
        actual=actual_intent,
    )


def assert_tools_used(result: dict, case: dict) -> BehavioralCheckResult:
    """检查是否使用了期望的工具（至少用一个）"""
    expected_tools = case.get("expected_tools", [])
    used_tools = result.get("tools_used", [])
    if not expected_tools:
        return BehavioralCheckResult("tools_used", True, "No tool check required")
    matched = [t for t in expected_tools if t in used_tools]
    passed = len(matched) > 0 if len(expected_tools) > 0 else True
    return BehavioralCheckResult(
        check_type="tools_used",
        passed=passed,
        detail=f"Tools matched: {matched}" if passed else f"Expected one of {expected_tools}, used {used_tools}",
        expected=expected_tools,
        actual=used_tools,
    )


def assert_forbid_tools(result: dict, case: dict) -> BehavioralCheckResult:
    """检查是否没有使用被禁止的工具（负路径测试）"""
    forbidden = case.get("forbidden_tools", [])
    used_tools = result.get("tools_used", [])
    if not forbidden:
        return BehavioralCheckResult("forbid_tools", True, "No forbidden tool check")
    violated = [t for t in forbidden if t in used_tools]
    passed = len(violated) == 0
    return BehavioralCheckResult(
        check_type="forbid_tools",
        passed=passed,
        detail="No forbidden tools used" if passed else f"Forbidden tools used: {violated}",
        expected=f"none of {forbidden}",
        actual=used_tools,
    )


def assert_blocked(result: dict, case: dict) -> BehavioralCheckResult:
    """检查输入是否被拦截"""
    blocked = result.get("blocked", False)
    passed = blocked == case.get("expected_blocked", False)
    return BehavioralCheckResult(
        check_type="blocked",
        passed=passed,
        detail=f"Blocked: {blocked}, Expected: {case.get('expected_blocked', False)}",
        expected=case.get("expected_blocked"),
        actual=blocked,
    )


def assert_has_interfaces(result: dict, case: dict) -> BehavioralCheckResult:
    """检查是否生成了接口定义"""
    code_artifact = result.get("code_artifact", {})
    has_interface = False
    for code in code_artifact.values():
        if isinstance(code, str) and ("def " in code or "interface" in code.lower() or "@app." in code):
            has_interface = True
            break
    return BehavioralCheckResult(
        check_type="has_interfaces",
        passed=has_interface,
        detail="Interfaces found" if has_interface else "No interfaces detected",
    )


def assert_has_components(result: dict, case: dict) -> BehavioralCheckResult:
    """检查是否生成了组件定义"""
    code_artifact = result.get("code_artifact", {})
    has_component = False
    for code in code_artifact.values():
        if isinstance(code, str) and ("class " in code or "Component" in code):
            has_component = True
            break
    return BehavioralCheckResult(
        check_type="has_components",
        passed=has_component,
        detail="Components found" if has_component else "No components detected",
    )


def assert_pii_detected(result: dict, case: dict) -> BehavioralCheckResult:
    """检查是否检测到了 PII"""
    pii_found = result.get("pii_found", [])
    expected = case.get("expected_pii_found", [])
    detected = [p for p in expected if p in pii_found]
    passed = len(detected) == len(expected) if expected else True
    return BehavioralCheckResult(
        check_type="pii_detected",
        passed=passed,
        detail=f"PII detected: {pii_found}, Expected: {expected}",
        expected=expected,
        actual=pii_found,
    )


def assert_within_budget(result: dict, case: dict) -> BehavioralCheckResult:
    """检查是否在预算内完成"""
    steps = result.get("steps", 0)
    max_steps = result.get("max_steps", 10)
    passed = steps <= max_steps
    return BehavioralCheckResult(
        check_type="within_budget",
        passed=passed,
        detail=f"Steps: {steps}/{max_steps}",
        expected=f"<= {max_steps}",
        actual=steps,
    )


def assert_convergence(result: dict, case: dict) -> BehavioralCheckResult:
    """检查修复循环是否收敛"""
    iterations = result.get("iterations", 0)
    max_iterations = result.get("max_iterations", 3)
    passed = iterations <= max_iterations
    return BehavioralCheckResult(
        check_type="convergence",
        passed=passed,
        detail=f"Iterations: {iterations}/{max_iterations}",
        expected=f"<= {max_iterations}",
        actual=iterations,
    )


# 检查函数映射
ASSERTION_FUNCTIONS = {
    "modules_generated": assert_modules_generated,
    "code_compiles": assert_code_compiles,
    "intent": assert_intent,
    "tools_used": assert_tools_used,
    "forbid_tools": assert_forbid_tools,
    "blocked": assert_blocked,
    "has_interfaces": assert_has_interfaces,
    "has_components": assert_has_components,
    "pii_detected": assert_pii_detected,
    "within_budget": assert_within_budget,
    "converges": assert_convergence,
}
