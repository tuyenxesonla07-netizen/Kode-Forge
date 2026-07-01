# tools/rag/rag_cognitive.py
"""
Intent classification, user modeling, and intent routing for RAG pipeline.

Merges: intent.py + user_model.py

Provides:
- IntentResult / IntentClassifier — query intent classification
- UserModel — cross-session user preference tracking
- RetrievalStrategy / IntentRouter — dynamic retrieval strategy selection
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tools.rag.rag_types import RAGConfig


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

_INTENT_KEYWORDS: dict[str, set[str]] = {
    "factual": {
        "what", "when", "where", "who", "which", "define", "definition",
        "fact", "date", "year", "name", "list", "statistics", "how many",
        "capital", "population", "meaning", "abbreviation",
        "什么", "何时", "哪里", "谁", "哪个", "定义", "多少",
        "日期", "年份", "名字", "列表", "统计", "人口", "意思",
    },
    "analytical": {
        "why", "how", "analyze", "compare", "contrast", "difference",
        "reason", "cause", "effect", "impact", "pros", "cons", "evaluate",
        "assess", "implications", "trend", "pattern", "relationship",
        "为什么", "怎么", "分析", "比较", "对比", "区别", "原因",
        "影响", "优缺点", "评估", "趋势", "模式", "关系", "区别",
    },
    "creative": {
        "create", "write", "story", "poem", "imagine", "design", "creative",
        "brainstorm", "invent", "compose", "generate ideas", "fiction",
        "narrative", "art", "music", "innovative",
        "创作", "写", "故事", "诗", "想象", "设计", "创意",
        "头脑风暴", "发明", "编写", "小说", "叙述", "艺术", "音乐",
    },
    "code_generation": {
        "code", "function", "class", "implement", "script", "program",
        "algorithm", "debug", "refactor", "api", "module", "library",
        "python", "javascript", "typescript", "java", "rust", "sql",
        "html", "css", "react", "docker", "kubernetes", "deploy",
        "test", "unit test", "error", "exception", "compile",
        "代码", "函数", "类", "实现", "脚本", "程序", "算法",
        "调试", "重构", "模块", "库", "编写代码", "编程", "开发",
        "异常", "编译", "部署", "接口", "服务", "组件",
    },
}

_ENTITY_PATTERNS = [
    (r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", "PERSON"),
    (r"\b[A-Z]{2,}\b", "ACRONYM"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "DATE"),
    (r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "DATE"),
    (r"https?://\S+", "URL"),
    (r"\b[\w.-]+@[\w.-]+\.\w+\b", "EMAIL"),
    (r"\b\d+(?:\.\d+)?\b", "NUMBER"),
]


@dataclass
class IntentResult:
    """Result of intent classification.

    Attributes:
        primary_intent: The most likely intent label.
        confidence: Confidence score in [0, 1].
        all_scores: Scores for every candidate intent.
        entities: Extracted entities as (text, label) pairs.
        keywords: Top keywords extracted from the query.
    """

    primary_intent: str
    confidence: float
    all_scores: dict[str, float] = field(default_factory=dict)
    entities: list[tuple[str, str]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


class IntentClassifier:
    """Rule-based intent classifier with entity and keyword extraction.

    Uses keyword overlap heuristics — no external API required.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self._intent_keywords = _INTENT_KEYWORDS

    def classify(self, query: str) -> IntentResult:
        """Classify *query* into an intent label."""
        tokens = _tokenize(query)
        if not tokens:
            return IntentResult(
                primary_intent=self.config.intent_labels[0],
                confidence=0.0,
                all_scores={label: 0.0 for label in self.config.intent_labels},
            )

        token_set = set(tokens)
        scores: dict[str, float] = {}
        for label in self.config.intent_labels:
            kw_set = self._intent_keywords.get(label, set())
            overlap = token_set & kw_set
            denom = max(1, (len(token_set) * len(kw_set)) ** 0.5)
            scores[label] = len(overlap) / denom

        max_score = max(scores.values()) if scores else 0.0
        if max_score > 0:
            scores = {k: v / max_score for k, v in scores.items()}

        primary = max(scores, key=scores.get)
        confidence = scores[primary]

        entities = _extract_entities(query)
        keywords = _extract_keywords(tokens)

        return IntentResult(
            primary_intent=primary,
            confidence=confidence,
            all_scores=scores,
            entities=entities,
            keywords=keywords,
        )

    __call__ = classify


# ---------------------------------------------------------------------------
# User Model
# ---------------------------------------------------------------------------

@dataclass
class UserModel:
    """Lightweight user model that evolves across sessions.

    Tracks expertise level, preferred language, common topics,
    and interaction style to personalize retrieval and responses.
    """

    user_id: str = "default"
    expertise_level: str = "intermediate"
    preferred_language: str = "zh"
    interaction_style: str = "detailed"
    common_topics: list[str] = field(default_factory=list)
    topic_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_interactions: int = 0
    last_interaction: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def update(self, query: str | None = None, feedback: str | None = None) -> None:
        """Update the user model from a new interaction."""
        self.total_interactions += 1
        self.last_interaction = datetime.now().isoformat(timespec="seconds")

        if query:
            self._update_from_query(query)
        if feedback:
            self._update_from_feedback(feedback)

        self._update_expertise()

    def _update_from_query(self, query: str) -> None:
        """Extract topics and signals from the query."""
        chinese_chars = len(re.findall(r"[一-鿿]", query))
        total_chars = max(1, len(query))
        if chinese_chars / total_chars > 0.3:
            self.preferred_language = "zh"

        topic_keywords = {
            "code": ["code", "function", "class", "implement", "script", "写", "代码", "函数", "实现"],
            "debug": ["debug", "error", "fix", "bug", "issue", "错", "调试", "修复"],
            "architecture": ["architecture", "design", "pattern", "module", "系统", "架构", "设计", "模块"],
            "data": ["data", "database", "sql", "query", "数据", "数据库"],
            "deploy": ["deploy", "docker", "kubernetes", "ci", "部署", "容器"],
            "auth": ["auth", "login", "token", "permission", "认证", "登录", "权限"],
        }

        query_lower = query.lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in query_lower for kw in keywords):
                self.topic_counts[topic] += 1
                if topic not in self.common_topics:
                    self.common_topics.append(topic)

        if len(self.common_topics) > 10:
            self.common_topics = sorted(
                self.common_topics, key=lambda t: self.topic_counts.get(t, 0), reverse=True
            )[:10]

    def _update_from_feedback(self, feedback: str) -> None:
        """Update based on feedback signals."""
        positive_signals = {"success", "thumbs_up", "good", "helpful", "ok", "yes", "好", "对"}
        negative_signals = {"failure", "thumbs_down", "bad", "wrong", "unhelpful", "no", "错", "不行"}

        feedback_lower = feedback.lower()

        if feedback_lower in positive_signals:
            pass  # current style works
        elif feedback_lower in negative_signals:
            if self.interaction_style == "detailed":
                pass  # try more concise next time

    def _update_expertise(self) -> None:
        """Infer expertise level from interaction patterns."""
        if self.total_interactions < 3:
            return

        expert_topics = {"architecture", "debug", "deploy"}
        expert_topic_count = sum(
            1 for t in self.common_topics if t in expert_topics
        )

        if expert_topic_count >= 1 and self.total_interactions >= 5:
            self.expertise_level = "expert"
        elif self.total_interactions > 3 and expert_topic_count == 0:
            self.expertise_level = "beginner"

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "expertise_level": self.expertise_level,
            "preferred_language": self.preferred_language,
            "interaction_style": self.interaction_style,
            "common_topics": self.common_topics,
            "topic_counts": dict(self.topic_counts),
            "total_interactions": self.total_interactions,
            "last_interaction": self.last_interaction,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserModel:
        if "topic_counts" in data:
            data["topic_counts"] = defaultdict(int, data["topic_counts"])
        field_names = set(cls.__dataclass_fields__.keys())
        return cls(**{k: v for k, v in data.items() if k in field_names})

    def __repr__(self) -> str:
        return (
            f"UserModel(level={self.expertise_level!r}, "
            f"topics={self.common_topics[:3]}, "
            f"interactions={self.total_interactions})"
        )


# ---------------------------------------------------------------------------
# Intent Router
# ---------------------------------------------------------------------------

@dataclass
class RetrievalStrategy:
    """Defines how retrieval should be performed for a given query."""

    mode: str = "search"              # "search" / "cognitive" / "hybrid"
    use_bm25: bool = True
    use_vector: bool = True
    use_graph: bool = False
    use_skill: bool = False
    use_memory: bool = False
    rerank_top_k: int = 5
    explain: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "use_bm25": self.use_bm25,
            "use_vector": self.use_vector,
            "use_graph": self.use_graph,
            "use_skill": self.use_skill,
            "use_memory": self.use_memory,
            "rerank_top_k": self.rerank_top_k,
        }


class IntentRouter:
    """Routes queries to the appropriate retrieval strategy based on
    intent classification and user model.

    Routing rules:
        - factual + beginner     → search mode (BM25 + Vector, simple)
        - factual + expert       → search mode (Vector priority)
        - code_generation        → cognitive mode (Graph + Skill + Memory)
        - analytical              → hybrid mode (all paths)
        - creative                → search mode (Vector priority)
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()

    def route(
        self,
        query: str,
        intent: IntentResult,
        user_model: UserModel | None = None,
    ) -> RetrievalStrategy:
        """Determine the best retrieval strategy for a query."""
        primary = intent.primary_intent

        if primary == "code_generation":
            strategy = self._route_code_generation(query, intent, user_model)
        elif primary == "factual":
            strategy = self._route_factual(query, intent, user_model)
        elif primary == "analytical":
            strategy = self._route_analytical(query, intent, user_model)
        elif primary == "creative":
            strategy = self._route_creative(query, intent, user_model)
        else:
            strategy = RetrievalStrategy()

        if user_model:
            strategy = self._personalize(strategy, user_model)

        if intent.confidence < 0.3:
            strategy.use_bm25 = True
            strategy.use_vector = True
            strategy.mode = "hybrid"

        return strategy

    def _route_code_generation(self, query, intent, user_model) -> RetrievalStrategy:
        """Code generation queries benefit from graph + skill + memory."""
        return RetrievalStrategy(
            mode="cognitive", use_bm25=True, use_vector=True,
            use_graph=True, use_skill=True, use_memory=True, rerank_top_k=5,
        )

    def _route_factual(self, query, intent, user_model) -> RetrievalStrategy:
        """Factual queries: BM25 + Vector is sufficient."""
        top_k = 3 if user_model and user_model.expertise_level == "expert" else 5
        return RetrievalStrategy(
            mode="search", use_bm25=True, use_vector=True,
            use_graph=False, use_skill=False, use_memory=False, rerank_top_k=top_k,
        )

    def _route_analytical(self, query, intent, user_model) -> RetrievalStrategy:
        """Analytical queries: need all retrieval paths."""
        return RetrievalStrategy(
            mode="hybrid", use_bm25=True, use_vector=True,
            use_graph=True, use_skill=False, use_memory=True, rerank_top_k=7,
        )

    def _route_creative(self, query, intent, user_model) -> RetrievalStrategy:
        """Creative queries: vector priority, no graph."""
        return RetrievalStrategy(
            mode="search", use_bm25=False, use_vector=True,
            use_graph=False, use_skill=False, use_memory=True, rerank_top_k=5,
        )

    def _personalize(self, strategy: RetrievalStrategy, user_model: UserModel) -> RetrievalStrategy:
        """Adjust strategy based on user model."""
        if user_model.expertise_level == "expert":
            strategy.rerank_top_k = max(3, strategy.rerank_top_k - 2)
        if user_model.expertise_level == "beginner":
            strategy.rerank_top_k += 2
        if user_model.total_interactions > 5:
            strategy.use_memory = True
        return strategy


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Language-aware tokenizer — delegates to pluggable strategy."""
    from tools.rag.tokenizer import tokenize
    return tokenize(text)


def _extract_entities(text: str) -> list[tuple[str, str]]:
    """Extract simple entities using regex patterns."""
    entities: list[tuple[str, str]] = []
    for pattern, label in _ENTITY_PATTERNS:
        for match in re.finditer(pattern, text):
            entities.append((match.group(), label))
    return entities


def _extract_keywords(tokens: list[str], top_n: int = 10) -> list[str]:
    """Extract top keywords by frequency, filtering out very short tokens."""
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "and",
        "but", "or", "not", "no", "this", "that", "it", "its",
        "i", "you", "he", "she", "we", "they", "me", "him", "her",
        "us", "them", "my", "your", "his", "our", "their",
    }
    filtered = [t for t in tokens if len(t) > 2 and t not in stopwords]
    counter = Counter(filtered)
    return [word for word, _ in counter.most_common(top_n)]
