"""P1-2 security tests: expanded OutputGuard CODE_DANGEROUS_PATTERNS.

The original 6 patterns only caught literal eval(input)/eval(exec) etc.
Attackers bypassed with eval(variable), exec(compile()), __import__(var), etc.
"""

import pytest

from tools.guardrails.output_guard import OutputGuard


# ---------------------------------------------------------------------------
# Blocked in strict + is_code mode (red-team confirmed bypass → now fixed)
# ---------------------------------------------------------------------------

class TestOutputGuardStrictExpanded:
    """Strict mode must block all eval/exec/__import__ variants."""

    @pytest.fixture
    def guard(self):
        return OutputGuard(strict=True)

    # --- eval() any argument ---
    def test_eval_variable_blocked(self, guard):
        result = guard.check("eval(user_input)", is_code=True)
        assert not result.passed, "eval(variable) must be blocked"

    def test_eval_request_attr_blocked(self, guard):
        result = guard.check("eval(request.json['expression'])", is_code=True)
        assert not result.passed

    def test_eval_ctx_key_blocked(self, guard):
        result = guard.check("eval(ctx['expression'])", is_code=True)
        assert not result.passed

    def test_eval_literal_still_blocked(self, guard):
        result = guard.check("eval(input('code:'))", is_code=True)
        assert not result.passed

    # --- exec() any argument ---
    def test_exec_compile_blocked(self, guard):
        result = guard.check("exec(compile(user_code, '<sandbox>', 'exec'))", is_code=True)
        assert not result.passed

    def test_exec_string_blocked(self, guard):
        result = guard.check("exec('import os; os.system(\"ls\")')", is_code=True)
        assert not result.passed

    # --- compile() with exec mode ---
    def test_compile_exec_mode_blocked(self, guard):
        result = guard.check("compile(user_input, 'user', 'exec')", is_code=True)
        assert not result.passed

    # --- __import__ any argument ---
    def test_dunder_import_variable_blocked(self, guard):
        result = guard.check("__import__(module_name)", is_code=True)
        assert not result.passed

    def test_dunder_import_literal_still_blocked(self, guard):
        result = guard.check("__import__('os').system('ls')", is_code=True)
        assert not result.passed

    # --- class-hierarchy escape ---
    def test_dunder_subclasses_blocked(self, guard):
        result = guard.check("object.__subclasses__()[40]", is_code=True)
        assert not result.passed

    # --- globals/locals escape ---
    def test_globals_blocked(self, guard):
        result = guard.check("globals()['__builtins__']", is_code=True)
        assert not result.passed

    def test_locals_blocked(self, guard):
        result = guard.check("locals()['__builtins__']", is_code=True)
        assert not result.passed

    # --- getattr to builtins ---
    def test_getattr_builtins_blocked(self, guard):
        result = guard.check("getattr(__builtins__, 'eval')", is_code=True)
        assert not result.passed

    # --- safe code that must NOT be blocked ---
    def test_safe_hello_world_not_blocked(self, guard):
        result = guard.check("def hello():\n    return 'world'", is_code=True)
        assert result.passed

    def test_safe_function_not_blocked(self, guard):
        result = guard.check(
            "def sort_list(items):\n    return sorted(items)\n", is_code=True
        )
        assert result.passed

    def test_safe_import_not_blocked(self, guard):
        result = guard.check("import json\ndata = json.loads(raw)", is_code=True)
        assert result.passed

    # --- non-code skips code check ---
    def test_plain_text_with_eval_word_not_blocked_for_non_code(self, guard):
        """When is_code=False, dangerous code patterns are not checked."""
        result = guard.check("This text mentions eval() in prose.", is_code=False)
        assert result.passed

    # --- warn mode: logs issue but doesn't block ---
    def test_eval_warned_not_blocked(self):
        guard = OutputGuard(strict=False)
        result = guard.check("eval(user_input)", is_code=True)
        assert result.passed
        assert len(result.issues) > 0
        assert any("eval" in issue for issue in result.issues)
