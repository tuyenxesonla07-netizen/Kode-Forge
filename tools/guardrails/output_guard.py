# tools/guardrails/output_guard.py

"""
输出护栏 — 模型回复出口前的最后一道检查。

参考 customer-service-agent 的 OutputGuard：
- 泄漏拦截: API key 样式字符串、系统提示词片段
- 越权承诺改写: "保证退款" → "按政策为您申请退款"
- PII 回流清理: 输出中不应出现未脱敏的敏感信息
- 空输出兜底: 模型返回空/过短时使用安全回复
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tools.guardrails.input_guard import mask_pii

# ─── 泄漏模式（预编译） ─────────────────────────────────────────
LEAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"sk-[A-Za-z0-9]{10,}", re.IGNORECASE),
    re.compile(r"(系统提示词|system prompt)[:：]", re.IGNORECASE),
    re.compile(r"\[INTERNAL\]", re.IGNORECASE),
    re.compile(r"(my|the) system (prompt|instruction)", re.IGNORECASE),
]

# ─── 越权承诺模式 (模式 → 替换) ──────────────────────────────
OVERPROMISE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"(保证|确保|承诺)[^。，,]{0,6}(全额)?退款"),
        "按政策为您申请退款",
    ),
    (
        re.compile(r"(百分之?百|100%)[^。，,]{0,6}(成功|解决|退款)"),
        "尽快为您处理",
    ),
    (
        re.compile(r"(一定|肯定)(能|会)[^。，,]{0,4}(退|赔|解决)"),
        "会按政策为您争取",
    ),
]

# ─── 代码输出安全检查 ─────────────────────────────────────────
CODE_DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"os\.system\s*\(",
    r"subprocess\.call\s*\(.+shell\s*=\s*True",
    r"eval\s*\(\s*(input|exec)",
    r"exec\s*\(\s*(input|eval)",
    r"__import__\s*\(\s*['\"]os['\"]",
]

# ─── 兜底回复 ─────────────────────────────────────────────────
FALLBACK_REPLY = "抱歉，系统处理出现异常，已为您记录，请稍后再试或联系人工客服。"


@dataclass
class OutputCheckResult:
    """输出检查结果"""
    passed: bool
    text: str
    issues: list[str] = field(default_factory=list)


class OutputGuard:
    """
    输出护栏。

    检查流程:
    1. 空输出兜底 — 模型返回空/过短时使用安全回复
    2. 泄漏拦截 — API key、系统提示词替换为兜底回复
    3. 越权承诺改写 — 将绝对化表述改为合规表述
    4. PII 回流清理 — 输出中不应出现未脱敏的敏感信息
    5. 代码安全检查 — 标记生成代码中的危险模式（仅警告，不阻断）
    """

    def __init__(self, strict: bool = False):
        """
        Args:
            strict: 严格模式下，越权承诺会阻断输出而非改写
        """
        self.strict = strict

    def check(self, text: str, is_code: bool = False) -> OutputCheckResult:
        """
        检查输出文本。

        Args:
            text: 模型输出文本
            is_code: 是否为代码输出（启用代码安全检查）

        Returns:
            OutputCheckResult with passed, cleaned text, issues
        """
        issues: list[str] = []

        # 1. 空输出兜底
        if not text or len(text.strip()) < 3:
            return OutputCheckResult(
                passed=False,
                text=FALLBACK_REPLY,
                issues=["输出为空或过短，使用兜底回复"],
            )

        # 2. 泄漏拦截 — 直接替换为兜底回复
        for pattern in LEAK_PATTERNS:
            if pattern.search(text):
                return OutputCheckResult(
                    passed=False,
                    text=FALLBACK_REPLY,
                    issues=[f"检测到敏感信息泄漏风险（{pattern.pattern}），已替换为兜底回复"],
                )

        # 3. 越权承诺改写/阻断
        for pattern, replacement in OVERPROMISE_PATTERNS:
            if pattern.search(text):
                if self.strict:
                    return OutputCheckResult(
                        passed=False,
                        text=FALLBACK_REPLY,
                        issues=[f"严格模式：检测到越权承诺（{pattern.pattern}），已阻断输出"],
                    )
                text = pattern.sub(replacement, text)
                issues.append(f"检测到越权承诺（{pattern.pattern}），已改写为合规表述")

        # 4. PII 回流清理
        masked, pii_found = mask_pii(text)
        if pii_found:
            text = masked
            issues.append(f"回复中包含 PII（{'/'.join(pii_found)}），已脱敏")

        # 5. 代码安全检查
        if is_code:
            for pattern in CODE_DANGEROUS_PATTERNS:
                if re.search(pattern, text):
                    if self.strict:
                        # 严格模式：危险代码直接阻断
                        return OutputCheckResult(
                            passed=False,
                            text=FALLBACK_REPLY,
                            issues=[f"严格模式：代码包含危险模式（{pattern}），已阻断输出"],
                        )
                    issues.append(f"代码中包含危险模式（{pattern}），建议人工复核")

        return OutputCheckResult(passed=True, text=text, issues=issues)
