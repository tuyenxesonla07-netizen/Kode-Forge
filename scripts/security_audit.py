#!/usr/bin/env python3
"""
scripts/security_audit.py — 部署前安全检查清单。

用法:
    python scripts/security_audit.py
    python scripts/security_audit.py --json  # JSON 格式输出

检查项:
    - API Key 是否已设置
    - CORS 是否为通配符
    - Debug 模式是否关闭
    - TLS 证书是否存在
    - 敏感文件是否被 .gitignore
    - 依赖是否有已知漏洞 (需要 pip-audit)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import List


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str  # "critical", "warning", "info"


def check(name: str, passed: bool, message: str, severity: str = "warning") -> CheckResult:
    return CheckResult(name=name, passed=passed, message=message, severity=severity)


def run_checks() -> List[CheckResult]:
    """运行所有安全检查"""
    results = []

    # ── 1. API Key 设置 ─────────────────────────────────────
    api_keys = os.environ.get("CC_API_KEYS", "")
    if api_keys:
        results.append(check(
            "api_keys_set", True,
            f"API Keys 已配置 ({len(api_keys.split(','))} 个)",
            "critical"
        ))
    else:
        results.append(check(
            "api_keys_set", False,
            "CC_API_KEYS 未设置 — 任何人都可以访问 API",
            "critical"
        ))

    # ── 2. CORS 配置 ────────────────────────────────────────
    cors = os.environ.get("CC_CORS_ORIGINS", "")
    if cors and cors != "*":
        results.append(check(
            "cors_not_wildcard", True,
            f"CORS 已限制为: {cors}",
            "warning"
        ))
    else:
        results.append(check(
            "cors_not_wildcard", False,
            "CORS 为通配符 * — 任何网站都可以跨域访问",
            "warning"
        ))

    # ── 3. Debug 模式 ───────────────────────────────────────
    debug = os.environ.get("CC_DEBUG", "").lower()
    if debug not in ("1", "true", "yes"):
        results.append(check(
            "debug_off", True,
            "Debug 模式已关闭",
            "critical"
        ))
    else:
        results.append(check(
            "debug_off", False,
            "Debug 模式开启 — 会泄露堆栈跟踪等敏感信息",
            "critical"
        ))

    # ── 4. TLS 证书 ─────────────────────────────────────────
    tls_cert = os.environ.get("CC_TLS_CERT_PATH", "")
    tls_key = os.environ.get("CC_TLS_KEY_PATH", "")
    if tls_cert and tls_key:
        if os.path.exists(tls_cert) and os.path.exists(tls_key):
            results.append(check(
                "tls_cert_exists", True,
                f"TLS 证书已配置: {tls_cert}",
                "critical"
            ))
        else:
            results.append(check(
                "tls_cert_exists", False,
                f"TLS 证书文件不存在: {tls_cert}",
                "critical"
            ))
    else:
        results.append(check(
            "tls_cert_exists", False,
            "TLS 证书未配置 — 流量未加密",
            "critical"
        ))

    # ── 5. .gitignore 保护 ──────────────────────────────────
    if os.path.exists(".gitignore"):
        with open(".gitignore", encoding="utf-8") as f:
            gitignore = f.read()
        if ".env" in gitignore:
            results.append(check(
                "gitignore_env", True,
                ".gitignore 排除了 .env",
                "warning"
            ))
        else:
            results.append(check(
                "gitignore_env", False,
                ".gitignore 未排除 .env — 密钥可能泄露",
                "warning"
            ))
    else:
        results.append(check(
            "gitignore_env", False,
            ".gitignore 不存在",
            "warning"
        ))

    # ── 6. 敏感文件未被跟踪 ─────────────────────────────────
    sensitive_files = [".env", ".env.local", "credentials.json", "*.pem", "*.key"]
    tracked_sensitive = []
    for pattern in sensitive_files:
        if pattern.startswith("*"):
            # 简单检查
            import glob
            for f in glob.glob(pattern):
                if os.path.exists(f):
                    tracked_sensitive.append(f)
        elif os.path.exists(pattern):
            tracked_sensitive.append(pattern)

    if not tracked_sensitive:
        results.append(check(
            "no_sensitive_files", True,
            "未检测到敏感文件",
            "info"
        ))
    else:
        results.append(check(
            "no_sensitive_files", False,
            f"检测到敏感文件: {', '.join(tracked_sensitive)}",
            "warning"
        ))

    # ── 7. 依赖漏洞扫描 (可选) ─────────────────────────────
    try:
        import pip_audit  # noqa: F401
        results.append(check(
            "pip_audit_available", True,
            "pip-audit 可用 — 运行 'pip-audit' 检查依赖漏洞",
            "info"
        ))
    except ImportError:
        results.append(check(
            "pip_audit_available", False,
            "pip-audit 未安装 — 运行 'pip install pip-audit' 检查依赖漏洞",
            "info"
        ))

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="部署前安全检查")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    results = run_checks()

    if args.json:
        output = [
            {
                "name": r.name,
                "passed": r.passed,
                "message": r.message,
                "severity": r.severity,
            }
            for r in results
        ]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("  Security Audit Checklist")
        print("=" * 60)

        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)
        critical = sum(1 for r in results if not r.passed and r.severity == "critical")

        for r in results:
            icon = "[PASS]" if r.passed else "[FAIL]"
            sev = f"({r.severity.upper()})" if not r.passed else ""
            print(f"  {icon} {r.message} {sev}")

        print()
        print(f"  Result: {passed} passed, {failed} failed")
        if critical:
            print(f"  [!] {critical} critical issues — DO NOT deploy to production!")
        print("=" * 60)
        print("=" * 60)

        if critical:
            sys.exit(1)


if __name__ == "__main__":
    main()
