"""跨 Session 记忆管理器 — 灵感来自 Hermes MemoryManager。

Design:
    pre_turn: 预取相关记忆 → 注入 system prompt
    post_turn: 异步写入新记忆（判断 novelty + importance）
    遗忘曲线: 压缩旧记忆，保留关键信息
    持久化: JSON 文件

Usage:
    mm = MemoryManager(persist_path=".rag_memory.json")

    # 每轮对话前
    context = mm.pre_turn("用户问的是订单模块的认证逻辑")

    # 每轮对话后
    mm.post_turn(query="...", response="...", metadata={"module": "auth"})

    # 跨 session 回忆
    memories = mm.recall("订单认证", limit=5)

    # 压缩旧记忆
    mm.compress()
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Memory item
# ---------------------------------------------------------------------------

@dataclass
class MemoryItem:
    """A single memory entry."""

    content: str
    source: str = ""                             # "conversation", "skill", "document"
    importance: float = 0.5                      # 0-1, higher = keep longer
    created_at: str = ""
    last_accessed: str = ""
    access_count: int = 0
    keywords: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        if not self.created_at:
            self.created_at = now
        if not self.last_accessed:
            self.last_accessed = now

    def touch(self) -> None:
        self.last_accessed = datetime.now().isoformat(timespec="seconds")
        self.access_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "importance": self.importance,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "keywords": self.keywords,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryItem:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Memory Manager
# ---------------------------------------------------------------------------

class MemoryManager:
    """Cross-session memory with pre/post-turn lifecycle.

    Features:
        - Pre-turn prefetch: find relevant memories before the LLM call
        - Post-turn capture: store important information after the LLM call
        - Forgetting curve: compress old/low-importance memories
        - Thread-safe: uses a lock for concurrent access
        - Persistent: saves to JSON on disk
    """

    def __init__(
        self,
        persist_path: str = ".rag_memory.json",
        max_memories: int = 200,
        importance_threshold: float = 0.3,
    ) -> None:
        self.persist_path = Path(persist_path)
        self.max_memories = max_memories
        self.importance_threshold = importance_threshold

        self._memories: list[MemoryItem] = []
        self._lock = threading.RLock()
        self._loaded = False

        self._load()

    # ---- public API --------------------------------------------------------

    def pre_turn(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """Pre-turn: find relevant memories to inject into context.

        Uses keyword overlap to find the most relevant memories.

        Args:
            query: The current query/context.
            limit: Maximum number of memories to return.

        Returns:
            List of relevant MemoryItems, sorted by relevance.
        """
        with self._lock:
            query_tokens = set(_tokenize(query))
            scored: list[tuple[float, MemoryItem]] = []

            for mem in self._memories:
                mem_tokens = set(mem.keywords)
                if not mem_tokens:
                    continue

                overlap = len(query_tokens & mem_tokens)
                if overlap == 0:
                    continue

                # Score: keyword overlap * importance * recency
                base_score = overlap / max(1, len(query_tokens))
                importance_bonus = 0.5 + 0.5 * mem.importance
                recency_bonus = self._recency_score(mem)

                total = base_score * importance_bonus * recency_bonus
                scored.append((total, mem))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = [mem for _, mem in scored[:limit]]

            # Mark as accessed
            for mem in results:
                mem.touch()

            return results

    def post_turn(
        self,
        query: str,
        response: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        """Post-turn: capture important information from this turn.

        Extracts key facts and stores them as memories if they pass
        the novelty and importance thresholds.

        Args:
            query: The user's query.
            response: The agent's response.
            metadata: Additional context (module, intent, etc.)

        Returns:
            List of new MemoryItems stored.
        """
        # Extract key facts from the response
        facts = self._extract_facts(query, response, metadata)

        stored: list[MemoryItem] = []
        with self._lock:
            for fact, importance, keywords in facts:
                # Novelty check: don't store duplicates
                if self._is_duplicate(fact):
                    continue

                item = MemoryItem(
                    content=fact,
                    source=metadata.get("source", "conversation") if metadata else "conversation",
                    importance=importance,
                    keywords=keywords,
                    metadata=metadata or {},
                )
                self._memories.append(item)
                stored.append(item)

            # Enforce memory limit
            if len(self._memories) > self.max_memories:
                self._evict()

        # Async persist
        if stored:
            self._save()

        return stored

    def build_context(self, query: str, token_budget: int = 4000) -> str:
        """
        构建上下文：根据 token 预算动态裁剪记忆。

        优先注入重要且相关的记忆，超出预算时截断。

        Args:
            query: 当前查询
            token_budget: token 预算上限（粗略估算）

        Returns:
            格式化后的上下文字符串
        """
        with self._lock:
            relevant = self.pre_turn(query, limit=20)
            if not relevant:
                return ""

            parts = []
            current_len = 0
            for mem in relevant:
                entry = f"- [{mem.source}] {mem.content}"
                entry_len = len(entry)  # rough char estimate
                if current_len + entry_len > token_budget * 4:  # ~4 chars per token
                    break
                parts.append(entry)
                current_len += entry_len

            if not parts:
                return ""

            return "[Relevant Memory]\n" + "\n".join(parts)

    def compress(self, keep_top_fraction: float = 0.7) -> int:
        """Compress memories using a forgetting curve.

        Keeps the most important/recent memories, compresses the rest
        into summary entries.

        Args:
            keep_top_fraction: Fraction of memories to keep (0-1).

        Returns:
            Number of memories removed.
        """
        with self._lock:
            if len(self._memories) <= 10:
                return 0

            # Score all memories
            scored = [(self._memory_score(mem), mem) for mem in self._memories]
            scored.sort(key=lambda x: x[0], reverse=True)

            keep_count = max(10, int(len(scored) * keep_top_fraction))
            kept = [mem for _, mem in scored[:keep_count]]
            removed_count = len(scored) - keep_count

            # Create a summary from removed memories
            if removed_count > 0:
                removed = [mem for _, mem in scored[keep_count:]]
                summary = self._summarize(removed)
                if summary:
                    summary_item = MemoryItem(
                        content=summary,
                        source="compression",
                        importance=0.4,
                        keywords=list(set(
                            kw for mem in removed for kw in mem.keywords
                        )),
                        metadata={"compressed_count": removed_count},
                    )
                    kept.append(summary_item)

            self._memories = kept
            self._save()

        logger.info("Compressed memories: removed %d, kept %d", removed_count, len(self._memories))
        return removed_count

    def get_all(self) -> list[MemoryItem]:
        """Return all memories."""
        with self._lock:
            return list(self._memories)

    def get_stats(self) -> dict[str, Any]:
        """Return memory statistics."""
        with self._lock:
            if not self._memories:
                return {"total": 0, "sources": {}, "avg_importance": 0.0}

            sources: dict[str, int] = defaultdict(int)
            for mem in self._memories:
                sources[mem.source] += 1

            return {
                "total": len(self._memories),
                "sources": dict(sources),
                "avg_importance": sum(m.importance for m in self._memories) / len(self._memories),
                "avg_access_count": sum(m.access_count for m in self._memories) / len(self._memories),
            }

    def clear(self) -> None:
        """Clear all memories."""
        with self._lock:
            self._memories = []
            self._save()

    # ---- internal: scoring -------------------------------------------------

    def _memory_score(self, mem: MemoryItem) -> float:
        """Composite score for memory retention."""
        recency = self._recency_score(mem)
        return mem.importance * 0.5 + recency * 0.3 + min(1.0, mem.access_count / 10) * 0.2

    @staticmethod
    def _recency_score(mem: MemoryItem) -> float:
        """Score based on how recently the memory was accessed (0-1)."""
        try:
            last = datetime.fromisoformat(mem.last_accessed)
            hours_ago = (datetime.now() - last).total_seconds() / 3600
            # Half-life of 48 hours
            return max(0.0, 2 ** (-hours_ago / 48))
        except (ValueError, TypeError):
            return 0.5

    # ---- internal: fact extraction ----------------------------------------

    def _extract_facts(
        self,
        query: str,
        response: str,
        metadata: dict[str, Any] | None,
    ) -> list[tuple[str, float, list[str]]]:
        """Extract key facts from a query-response pair.

        Returns list of (fact_text, importance, keywords).
        """
        facts: list[tuple[str, float, list[str]]] = []

        # Extract from response sentences
        sentences = _split_sentences(response)

        for sentence in sentences:
            if len(sentence) < 10:
                continue

            # Score importance: longer + contains key terms = higher
            importance = _estimate_importance(sentence)
            if importance < self.importance_threshold:
                continue

            keywords = _extract_keywords(sentence)
            facts.append((sentence.strip(), importance, keywords))

        # Also store the query itself if it contains a question mark
        if "?" in query or "？" in query:
            q_keywords = _extract_keywords(query)
            facts.append((f"User asked: {query}", 0.6, q_keywords))

        return facts

    def _is_duplicate(self, fact: str) -> bool:
        """Check if a fact is already stored (semantic overlap > 0.8)."""
        fact_tokens = set(_tokenize(fact))
        if not fact_tokens:
            return False

        for mem in self._memories:
            # Check against content tokens only (not keywords)
            mem_tokens = set(_tokenize(mem.content))
            if not mem_tokens:
                continue
            overlap = len(fact_tokens & mem_tokens)
            union = len(fact_tokens | mem_tokens)
            if union > 0 and overlap / union > 0.8:
                return True

        return False

    # ---- internal: eviction & compression ---------------------------------

    def _evict(self) -> None:
        """Remove low-scoring memories when over capacity."""
        scored = [(self._memory_score(mem), mem) for mem in self._memories]
        scored.sort(key=lambda x: x[0], reverse=True)
        self._memories = [mem for _, mem in scored[: self.max_memories]]

    @staticmethod
    def _summarize(memories: list[MemoryItem]) -> str:
        """Create a summary from multiple memories."""
        if not memories:
            return ""

        # Take the most common keywords
        all_keywords: dict[str, int] = defaultdict(int)
        for mem in memories:
            for kw in mem.keywords:
                all_keywords[kw] += 1

        top_keywords = sorted(all_keywords, key=all_keywords.get, reverse=True)[:10]

        # Sample representative content
        samples = [mem.content[:100] for mem in memories[:3]]

        return (
            f"[Compressed {len(memories)} memories. "
            f"Key topics: {', '.join(top_keywords)}. "
            f"Samples: {' | '.join(samples)}]"
        )

    # ---- persistence -------------------------------------------------------

    def _load(self) -> None:
        """Load memories from disk."""
        if not self.persist_path.exists():
            return

        try:
            with open(self.persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._memories = [MemoryItem.from_dict(m) for m in data.get("memories", [])]
            logger.info("Loaded %d memories from %s", len(self._memories), self.persist_path)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load memories: %s", e)

    def _save(self) -> None:
        """Persist memories to disk."""
        data = {
            "memories": [m.to_dict() for m in self._memories],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(self.persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Language-aware tokenizer — delegates to pluggable strategy."""
    from tools.rag.tokenizer import tokenize
    return tokenize(text)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    import re
    return [s.strip() for s in re.split(r"[.!?。！？\n]+", text) if s.strip()]


def _extract_keywords(text: str, top_n: int = 8) -> list[str]:
    """Extract keywords from text."""
    import re
    tokens = _tokenize(text)
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "to", "of", "in",
        "for", "on", "with", "at", "by", "from", "as", "and", "but",
        "or", "not", "no", "this", "that", "it", "its",
        "的", "是", "在", "和", "有", "不", "了", "与", "中", "为", "对", "等",
    }
    # Keep tokens with >1 char (Chinese) or >2 chars (English)
    filtered = [t for t in tokens if len(t) > 1 and t not in stopwords]
    return list(dict.fromkeys(filtered))[:top_n]


def _estimate_importance(sentence: str) -> float:
    """Estimate how important a sentence is for memorization (0-1)."""
    score = 0.5

    # Longer sentences tend to carry more information
    words = sentence.split()
    if len(words) > 10:
        score += 0.1
    if len(words) > 20:
        score += 0.1

    # Sentences with specific patterns are more important
    important_markers = [
        "must", "should", "important", "critical", "note", "remember",
        "always", "never", "require", "constraint", "rule",
        "必须", "应该", "重要", "注意", "记住",
    ]
    lower = sentence.lower()
    for marker in important_markers:
        if marker in lower:
            score += 0.15
            break

    # Sentences with code or technical terms
    if any(c in sentence for c in "{}()=[]"):
        score += 0.1

    return min(1.0, score)
