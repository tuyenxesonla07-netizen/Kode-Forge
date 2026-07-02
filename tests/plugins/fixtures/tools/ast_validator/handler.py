"""
AST Validator handler — test fixture.
"""
from __future__ import annotations


def validate_ast(context: dict, code: str) -> dict:
    """Validate Python AST for syntax errors (mock implementation for testing)."""
    import ast
    try:
        ast.parse(code)
        return {"valid": True, "errors": []}
    except SyntaxError as e:
        return {"valid": False, "errors": [str(e)]}
