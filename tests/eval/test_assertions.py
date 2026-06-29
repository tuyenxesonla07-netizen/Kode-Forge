# tests/eval/test_assertions.py
"""Tests for behavioral assertions: intent, tools_used, forbid_tools, blocked, modules_generated."""

import pytest

from tools.eval.assertions import (
    assert_intent, assert_tools_used, assert_forbid_tools,
    assert_blocked, assert_modules_generated, BehavioralCheckResult,
    ASSERTION_FUNCTIONS,
)


class TestAssertIntent:
    def test_matching_intent(self):
        result = {"intent": "code_generation"}
        case = {"expected_intent": "code_generation"}
        check = assert_intent(result, case)
        assert check.passed is True
        assert check.actual == "code_generation"

    def test_mismatching_intent(self):
        result = {"intent": "code_review"}
        case = {"expected_intent": "code_generation"}
        check = assert_intent(result, case)
        assert check.passed is False
        assert "code_generation" in check.detail

    def test_no_expected_intent(self):
        result = {"intent": "anything"}
        case = {}
        check = assert_intent(result, case)
        assert check.passed is True


class TestAssertToolsUsed:
    def test_matching_tool(self):
        result = {"tools_used": ["generate_code", "search_kb"]}
        case = {"expected_tools": ["generate_code"]}
        check = assert_tools_used(result, case)
        assert check.passed is True

    def test_no_matching_tool(self):
        result = {"tools_used": ["search_kb"]}
        case = {"expected_tools": ["generate_code", "write_file"]}
        check = assert_tools_used(result, case)
        assert check.passed is False

    def test_empty_expected(self):
        result = {"tools_used": []}
        case = {}
        check = assert_tools_used(result, case)
        assert check.passed is True

    def test_partial_match(self):
        result = {"tools_used": ["generate_code"]}
        case = {"expected_tools": ["generate_code", "write_file"]}
        check = assert_tools_used(result, case)
        assert check.passed is True


class TestAssertForbidTools:
    def test_no_violation(self):
        result = {"tools_used": ["search_kb"]}
        case = {"forbidden_tools": ["execute_code", "write_file"]}
        check = assert_forbid_tools(result, case)
        assert check.passed is True

    def test_violation(self):
        result = {"tools_used": ["execute_code"]}
        case = {"forbidden_tools": ["execute_code", "write_file"]}
        check = assert_forbid_tools(result, case)
        assert check.passed is False
        assert "execute_code" in check.detail

    def test_empty_forbidden(self):
        result = {"tools_used": ["anything"]}
        case = {}
        check = assert_forbid_tools(result, case)
        assert check.passed is True


class TestAssertBlocked:
    def test_expected_blocked_and_blocked(self):
        result = {"blocked": True}
        case = {"expected_blocked": True}
        check = assert_blocked(result, case)
        assert check.passed is True

    def test_expected_blocked_but_not(self):
        result = {"blocked": False}
        case = {"expected_blocked": True}
        check = assert_blocked(result, case)
        assert check.passed is False

    def test_not_expected_blocked_and_not(self):
        result = {"blocked": False}
        case = {"expected_blocked": False}
        check = assert_blocked(result, case)
        assert check.passed is True


class TestAssertionRegistry:
    def test_intent_registered(self):
        assert "intent" in ASSERTION_FUNCTIONS

    def test_tools_used_registered(self):
        assert "tools_used" in ASSERTION_FUNCTIONS

    def test_forbid_tools_registered(self):
        assert "forbid_tools" in ASSERTION_FUNCTIONS

    def test_blocked_registered(self):
        assert "blocked" in ASSERTION_FUNCTIONS

    def test_modules_generated_registered(self):
        assert "modules_generated" in ASSERTION_FUNCTIONS
