"""Phase 3 tests: AST dangerous import detection."""

import pytest
from tools.quality.ast_validator import ASTValidator, DANGEROUS_MODULES, ValidationIssue


class TestDangerousImports:
    """Gap 10: AST validator should detect dangerous module imports."""

    def test_os_import_flagged(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("import os\nos.system('ls')")
        assert len(issues) > 0
        assert issues[0].severity == "critical"
        assert "os" in issues[0].message.lower() or "Dangerous" in issues[0].message

    def test_subprocess_import_flagged(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("import subprocess\nsubprocess.call(['ls'])")
        assert len(issues) > 0
        assert issues[0].severity == "critical"

    def test_socket_import_flagged(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("import socket\nsocket.gethostname()")
        assert len(issues) > 0

    def test_ctypes_import_flagged(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("import ctypes\nctypes.CDLL(None)")
        assert len(issues) > 0

    def test_import_from_os_flagged(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("from os import system\nsystem('ls')")
        assert len(issues) > 0
        assert issues[0].severity == "critical"

    def test_import_from_subprocess_flagged(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("from subprocess import call\ncall(['ls'])")
        assert len(issues) > 0

    def test_multiple_dangerous_imports(self):
        code = "import os\nimport subprocess\nimport socket"
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports(code)
        assert len(issues) >= 3

    def test_safe_imports_pass(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("import json\nimport typing\nimport ast")
        assert len(issues) == 0

    def test_standard_library_passes(self):
        code = "import sys\nimport os.path\nimport pathlib"
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports(code)
        # os.path is split by "." → "os" which IS dangerous
        # This is by design: conservative blocking
        assert len(issues) >= 1

    def test_syntax_error_returns_empty(self):
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("import os\n broken")
        assert len(issues) == 0

    def test_dangerous_modules_set_not_empty(self):
        assert len(DANGEROUS_MODULES) > 0
        assert "os" in DANGEROUS_MODULES
        assert "subprocess" in DANGEROUS_MODULES


class TestValidateDangerousImportsIntegration:
    """Test that validate() also calls validate_dangerous_imports when requested."""

    def test_validate_does_not_auto_check_dangerous(self):
        """validate() alone does NOT call validate_dangerous_imports.
        Caller must explicitly call validate_dangerous_imports()."""
        validator = ASTValidator()
        result = validator.validate("import os\nos.system('ls')")
        # validate() itself doesn't flag dangerous imports
        # (caller must use validate_dangerous_imports explicitly)
        assert result.valid is True  # syntax is fine, no structural issues

    def test_validate_dangerous_imports_explicit(self):
        """Explicit call to validate_dangerous_imports flags the issue."""
        validator = ASTValidator()
        issues = validator.validate_dangerous_imports("import os\nos.system('ls')")
        assert any(i.severity == "critical" for i in issues)
