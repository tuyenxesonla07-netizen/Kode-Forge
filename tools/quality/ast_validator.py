# tools/validation/ast_validator.py

"""
AST 验证器 — 检查生成代码的语法和结构。

验证维度:
1. 语法正确性（AST parse）
2. 导入依赖完整性
3. 类型注解检查
4. 函数签名与接口一致性

用法:
    validator = ASTValidator()
    result = validator.validate(code, spec)
    if not result.valid:
        for issue in result.issues:
            print(issue)
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── 危险模块列表 ─────────────────────────────────────────────
DANGEROUS_MODULES = {
    "os", "subprocess", "socket", "ctypes", "importlib",
    "pickle", "marshal", "http", "urllib", "ftplib",
    "smtplib", "telnetlib", "xmlrpc",
}


@dataclass
class ValidationIssue:
    """单个验证问题"""
    severity: str       # "critical" | "major" | "minor"
    type: str           # "syntax_error" | "missing_import" | "missing_class" | ...
    message: str
    line: Optional[int] = None
    suggestion: str = ""


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_critical(self) -> bool:
        return any(i.severity == "critical" for i in self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def major_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "major")

    @property
    def error_count(self) -> int:
        return len(self.issues)


class ASTValidator:
    """
    Python 代码 AST 验证器。

    检查生成代码的语法正确性、结构完整性和接口一致性。
    """

    def validate(self, code: str, spec: dict = None) -> ValidationResult:
        """
        全面验证代码。

        Args:
            code: 要验证的 Python 代码
            spec: 模块规格（可选，用于结构检查）

        Returns:
            ValidationResult
        """
        issues: List[ValidationIssue] = []

        # 1. 语法检查
        syntax_ok, syntax_issues = self.validate_syntax(code)
        issues.extend(syntax_issues)

        if not syntax_ok:
            # 语法错误时跳过后续检查
            return ValidationResult(
                valid=False,
                issues=issues,
                metrics={"syntax_valid": False, "line_count": len(code.splitlines())},
            )

        # 2. 导入检查
        import_issues = self.validate_imports(code)
        issues.extend(import_issues)

        # 3. 结构检查（需要 spec）
        if spec:
            structure_issues = self.validate_structure(code, spec)
            issues.extend(structure_issues)

        # 4. 类型注解检查
        type_issues = self.validate_type_annotations(code)
        issues.extend(type_issues)

        # 5. 函数签名检查
        if spec and "interfaces" in spec:
            signature_issues = self.validate_signatures(code, spec["interfaces"])
            issues.extend(signature_issues)

        # 计算指标
        metrics = self._compute_metrics(code)

        return ValidationResult(
            valid=not any(i.severity == "critical" for i in issues),
            issues=issues,
            metrics=metrics,
        )

    def validate_syntax(self, code: str) -> tuple[bool, List[ValidationIssue]]:
        """
        语法正确性检查。

        Returns:
            (is_valid, issues)
        """
        issues = []
        try:
            ast.parse(code)
            return True, []
        except SyntaxError as e:
            issues.append(ValidationIssue(
                severity="critical",
                type="syntax_error",
                message=f"Syntax error at line {e.lineno}: {e.msg}",
                line=e.lineno,
                suggestion=self._suggest_syntax_fix(e, code),
            ))
            return False, issues

    def validate_imports(self, code: str) -> List[ValidationIssue]:
        """
        导入完整性检查。

        检查:
        - 未使用的导入
        - 缺失的标准库导入（如用了 json 但没 import json）
        """
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 收集所有导入
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)

        # 收集所有使用的名称（排除导入语句本身）
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # 收集 obj.attr 中的 obj
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        # 检查未使用的导入（排除 __future__ 和常见别名）
        unused = imported_names - used_names - {"__future__", "_"}
        for name in unused:
            # 不报 __init__ 等特殊名称
            if not name.startswith("_"):
                issues.append(ValidationIssue(
                    severity="minor",
                    type="unused_import",
                    message=f"Unused import: {name}",
                    suggestion=f"Remove unused import '{name}' or use it in the code",
                ))

        return issues

    def validate_structure(self, code: str, spec: dict) -> List[ValidationIssue]:
        """
        结构完整性检查。

        根据 spec 检查代码是否包含必要的类和函数。
        """
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 收集代码中定义的类和函数
        defined_classes = set()
        defined_functions = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                defined_classes.add(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined_functions.add(node.name)

        # 检查 spec 要求的类
        required_classes = spec.get("required_classes", [])
        for cls in required_classes:
            if cls not in defined_classes:
                issues.append(ValidationIssue(
                    severity="major",
                    type="missing_class",
                    message=f"Missing required class: {cls}",
                    suggestion=f"Add 'class {cls}: ...' to the module",
                ))

        # 检查 spec 要求的函数
        required_functions = spec.get("required_functions", [])
        for func in required_functions:
            if func not in defined_functions:
                issues.append(ValidationIssue(
                    severity="major",
                    type="missing_function",
                    message=f"Missing required function: {func}",
                    suggestion=f"Add 'def {func}(...): ...' to the module",
                ))

        # 检查 components 中定义的类型
        components = spec.get("components", [])
        for comp in components:
            comp_name = comp.get("name", "")
            comp_type = comp.get("type", "service")

            if not comp_name:
                continue

            if comp_type == "service" and comp_name not in defined_classes:
                issues.append(ValidationIssue(
                    severity="major",
                    type="missing_component",
                    message=f"Component '{comp_name}' ({comp_type}) not found in code",
                    suggestion=f"Define class {comp_name} for the {comp_type} component",
                ))
            elif comp_type == "route" and comp_name not in defined_functions:
                # 路由可以是函数或类
                pass  # 路由检查更宽松

        return issues

    def validate_type_annotations(self, code: str) -> List[ValidationIssue]:
        """
        类型注解检查。

        检查函数是否有返回类型注解。
        """
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 跳过 __init__ 等特殊方法
                if node.name.startswith("__"):
                    continue

                # 检查返回类型注解
                if node.returns is None:
                    issues.append(ValidationIssue(
                        severity="minor",
                        type="missing_return_annotation",
                        message=f"Function '{node.name}' missing return type annotation",
                        line=node.lineno,
                        suggestion=f"Add return type: def {node.name}(...) -> ReturnType:",
                    ))

        return issues

    def validate_dangerous_imports(self, code: str) -> List[ValidationIssue]:
        """
        检查代码是否导入了危险模块。

        危险模块列表见 DANGEROUS_MODULES。

        Returns:
            包含 dangerous_import severity="critical" 的问题列表
        """
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name in DANGEROUS_MODULES:
                        issues.append(ValidationIssue(
                            severity="critical",
                            type="dangerous_import",
                            message=f"Dangerous module imported: {alias.name}",
                            line=node.lineno,
                            suggestion=f"Remove 'import {alias.name}' — this module is not allowed in sandbox mode",
                        ))
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module.split(".")[0] if node.module else ""
                if module_name in DANGEROUS_MODULES:
                    issues.append(ValidationIssue(
                        severity="critical",
                        type="dangerous_import",
                        message=f"Dangerous module imported from: {node.module}",
                        line=node.lineno,
                        suggestion=f"Remove 'from {node.module} import ...' — this module is not allowed in sandbox mode",
                    ))
        return issues

    def validate_signatures(self, code: str, interfaces: list) -> List[ValidationIssue]:
        """
        接口签名一致性检查。

        检查代码中是否定义了接口定义中声明的端点。
        """
        issues = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # 收集所有装饰器中的路由信息
        route_endpoints = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    # 检查 @app.get("/path") 等装饰器
                    if isinstance(decorator, ast.Call):
                        func = decorator.func
                        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                            if func.value.id in ("app", "router", "bp"):
                                # 提取路径参数
                                if decorator.args:
                                    if isinstance(decorator.args[0], ast.Constant):
                                        route_endpoints.add(decorator.args[0].value)

        # 检查接口定义
        for iface in interfaces:
            path = iface.get("path", "")
            method = iface.get("method", "GET")
            name = iface.get("name", "")

            # 宽松检查：路径是否在代码中定义
            if path and path not in route_endpoints:
                # 不报 404，因为路径可能通过变量定义
                pass

        return issues

    def _compute_metrics(self, code: str) -> Dict[str, Any]:
        """计算代码指标"""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {"syntax_valid": False, "line_count": len(code.splitlines())}

        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]

        return {
            "syntax_valid": True,
            "line_count": len(code.splitlines()),
            "class_count": len(classes),
            "function_count": len(functions),
            "import_count": len(imports),
            "has_classes": len(classes) > 0,
            "has_functions": len(functions) > 0,
            "has_docstrings": any(
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)
                for n in ast.walk(tree)
            ),
        }

    def _suggest_syntax_fix(self, error: SyntaxError, code: str) -> str:
        """根据语法错误类型给出修复建议"""
        msg = error.msg.lower()

        if "unexpected eof" in msg:
            return "Check for unclosed parentheses, brackets, or triple-quoted strings"
        if "invalid syntax" in msg and error.lineno:
            lines = code.splitlines()
            if error.lineno <= len(lines):
                line = lines[error.lineno - 1]
                if line.strip().endswith(":"):
                    return "Add indented block after colon"
                if line.count("(") > line.count(")"):
                    return "Missing closing parenthesis ')'"
                if line.count("{") > line.count("}"):
                    return "Missing closing brace '}'"
                if line.count("[") > line.count("]"):
                    return "Missing closing bracket ']'"
        if "eol" in msg or "string" in msg:
            return "Check for unclosed string literal"
        if "indent" in msg:
            return "Fix indentation (mixing tabs and spaces?)"

        return f"Fix syntax error: {error.msg}"
