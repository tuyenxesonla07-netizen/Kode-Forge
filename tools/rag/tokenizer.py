# tools/rag/tokenizer.py
"""Pluggable tokenizer strategy for RAG — Chinese/English/mixed text."""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Tokenizer(Protocol):
    """Tokenizer strategy interface."""

    def tokenize(self, text: str) -> list[str]:
        """Split *text* into tokens suitable for keyword overlap scoring."""
        ...


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

_UNICODE_WORD_RE = re.compile(r"[a-z0-9]+|[一-鿿㐀-䶿]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\S+")


class SimpleTokenizer:
    """Fallback tokenizer — extracts ASCII words + individual CJK characters.

    No external dependencies. Suitable for CI / offline environments.
    Works because CJK ideographs are meaningful at the single-character level
    (unlike Latin words which need context). Single-char CJK tokens are enough
    for keyword overlap matching and BM25 scoring.
    """

    def tokenize(self, text: str) -> list[str]:
        return _UNICODE_WORD_RE.findall(text.lower())


class JiebaTokenizer:
    """Jieba-based tokenizer for Chinese text (optional dependency).

    Falls back to SimpleTokenizer if jieba is not installed.
    """

    def __init__(self) -> None:
        try:
            import jieba as _jieba
            self._jieba = _jieba
        except ImportError:
            self._jieba = None

    @property
    def available(self) -> bool:
        return self._jieba is not None

    def tokenize(self, text: str) -> list[str]:
        if self._jieba is None:
            return SimpleTokenizer().tokenize(text)
        tokens = list(self._jieba.cut(text, cut_all=False))
        expanded: list[str] = []
        for tok in tokens:
            sub = tok.lower().split()
            expanded.extend(t for t in sub if t)
        return expanded if expanded else SimpleTokenizer().tokenize(text)


# ---------------------------------------------------------------------------
# Module-level default (singleton, lazy)
# ---------------------------------------------------------------------------

_default: Tokenizer | None = None


def get_default_tokenizer() -> Tokenizer:
    """Return the best available tokenizer (jieba if installed, else simple)."""
    global _default
    if _default is None:
        candidate = JiebaTokenizer()
        _default = candidate if candidate.available else SimpleTokenizer()
    return _default


def tokenize(text: str) -> list[str]:
    """Tokenize *text* using the default tokenizer."""
    return get_default_tokenizer().tokenize(text)
