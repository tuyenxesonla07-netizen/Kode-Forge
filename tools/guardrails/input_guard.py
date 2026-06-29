# tools/guardrails/input_guard.py

"""
输入护栏 — 模型调用前的第一道防线。

参考 customer-service-agent 的 InputGuard：
- 拦截: 提示词注入、危险指令、超长输入
- 脱敏: 手机号/身份证/邮箱/银行卡 → 掩码处理后再进入模型与日志

保障敏感数据不出现在 prompt、trace、audit log 中。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Pattern

# ─── 注入/越权模式（预编译） ─────────────────────────────────────────
INJECTION_PATTERNS: List[Pattern] = [
    re.compile(r"忽略(之前|上面|以上|前面)?的?(所有)?(指令|提示|规则|设定)", re.IGNORECASE),
    re.compile(r"ignore (all )?(previous|above) (instructions|prompts)", re.IGNORECASE),
    re.compile(r"(打印|输出|告诉我|透露).{0,8}(system prompt|系统提示词|系统指令)", re.IGNORECASE),
    re.compile(r"你(现在|从现在起)?(是|扮演|假装)", re.IGNORECASE),
    re.compile(r"进入开发者模式", re.IGNORECASE),
    re.compile(r"DROP\s+TABLE", re.IGNORECASE),
    re.compile(r"rm\s+-rf", re.IGNORECASE),
    re.compile(r"(给我|发我|输出).{0,10}(api[_\s]?key|密钥|秘钥)", re.IGNORECASE),
    re.compile(r"(把|将)?(所有|全部)?(用户|客户)(数据|信息|名单)(都)?(给|发|导出)", re.IGNORECASE),
    re.compile(r"(reveal|show|print).{0,10}(your )?(system|instruction|prompt)", re.IGNORECASE),
]

# ─── PII 脱敏模式 ─────────────────────────────────────────────
PII_PATTERNS: List[tuple] = [
    ("phone",
     re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
     lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:]),
    ("id_card",
     re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
     lambda m: m.group(0)[:4] + "*" * 10 + m.group(0)[-4:]),
    ("email",
     re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
     lambda m: m.group(0)[0] + "***@" + m.group(0).split("@")[1]),
    ("bank_card",
     re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
     lambda m: "**** **** **** " + m.group(0)[-4:]),
]


def mask_pii(text: str) -> tuple:
    """
    脱敏文本中的 PII。

    Returns:
        (脱敏后文本, 命中的 PII 类型列表)
    """
    found: list[str] = []
    for pii_type, pattern, replacer in PII_PATTERNS:
        if pattern.search(text):
            found.append(pii_type)
            text = pattern.sub(replacer, text)
    return text, found


@dataclass
class InputCheckResult:
    """输入检查结果"""
    passed: bool
    text: str                       # 通过时为脱敏后的安全文本
    reason: str = ""
    pii_found: list[str] = field(default_factory=list)


class InputGuard:
    """
    输入护栏。

    检查流程:
    1. 长度检查 — 超长输入直接拦截（防上下文填充攻击）
    2. 注入检测 — 正则匹配已知注入模式
    3. PII 脱敏 — 掩码处理后再进入模型

    用法:
        guard = InputGuard(max_length=5000)
        result = guard.check("用户输入...")
        if not result.passed:
            print(f"Blocked: {result.reason}")
        else:
            safe_text = result.text
    """

    def __init__(self, max_length: int = 5000):
        self.max_length = max_length
        self.blocked_count = 0

    def check(self, text: str) -> InputCheckResult:
        """
        检查输入文本。

        Returns:
            InputCheckResult with passed, sanitized text, reason, pii_found
        """
        # 1. 长度检查
        if len(text) > self.max_length:
            self.blocked_count += 1
            return InputCheckResult(
                passed=False,
                text="",
                reason=f"输入超长（>{self.max_length} 字符），疑似上下文填充攻击",
            )

        # 2. 注入检测
        for pattern in INJECTION_PATTERNS:
            if pattern.search(text):
                self.blocked_count += 1
                return InputCheckResult(
                    passed=False,
                    text="",
                    reason="检测到疑似提示词注入/危险指令",
                )

        # 3. PII 脱敏
        safe_text, pii_found = mask_pii(text)
        return InputCheckResult(
            passed=True,
            text=safe_text,
            pii_found=pii_found,
        )
