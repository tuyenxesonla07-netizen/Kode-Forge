# tools/rag/search/query_profile.py

"""
QueryProfiler — 结构化 RAG 查询预处理管道。

借鉴 codex 的 QueryProfile + ALIASES 同义词扩展模式。
管道：classify → rewrite → expand → route。

用法:
    from tools.rag.search.query_profile import QueryProfiler

    profiler = QueryProfiler()
    profile = profiler.build_profile("帮我生成用户登录模块")
    print(profile.domain)              # "code_gen"
    print(profile.retrieval_strategy)  # RetrievalStrategy(...)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# QueryProfile — 结构化查询画像
# ---------------------------------------------------------------------------

@dataclass
class QueryProfile:
    """结构化查询画像 — RAG 检索前的完整预处理结果。"""
    raw_query: str
    domain: str = ""                   # code_gen / quality_check / documentation / unknown
    normalized_query: str = ""
    terms: frozenset[str] = field(default_factory=frozenset)
    tags: frozenset[str] = field(default_factory=frozenset)
    entities: dict[str, Any] = field(default_factory=dict)
    intent_result: Any = None
    rewritten_query: str = ""
    retrieval_strategy: Any = None


# ---------------------------------------------------------------------------
# QueryProfiler — 查询预处理管道
# ---------------------------------------------------------------------------

class QueryProfiler:
    """结构化 RAG 查询预处理管道。

    处理流程：
        1. classify  — 意图分类（使用注入的 IntentClassifier 或规则）
        2. rewrite   — 查询改写（使用注入的 QueryRewriter 或简单标准化）
        3. expand    — 同义词扩展（ALIASES 字典）
        4. route     — 检索策略路由（使用注入的 IntentRouter）
    """

    # 领域关键词字典 — 用于 domain 分类和同义词扩展
    ALIASES: dict[str, list[str]] = {
        "code_gen": [
            "代码生成", "编写", "实现", "开发", "创建", "构建",
            "build", "create", "generate", "implement", "write", "code",
            "编写代码", "编程", "程序", "模块", "函数", "类", "代码",
        ],
        "quality_check": [
            "质量", "检查", "审查", "测试", "review",
            "check", "test", "quality", "inspect", "audit",
            "验证", "评估", "evaluate", "门禁", "gate",
        ],
        "documentation": [
            "文档", "说明", "帮助", "如何使用", "教程",
            "help", "doc", "how to", "documentation", "guide", "tutorial",
            "手册", "参考", "reference", "指南",
        ],
    }

    def __init__(
        self,
        intent_classifier: Any = None,
        query_rewriter: Any = None,
        intent_router: Any = None,
    ) -> None:
        self._intent_classifier = intent_classifier
        self._query_rewriter = query_rewriter
        self._intent_router = intent_router

    def build_profile(self, query: str) -> QueryProfile:
        """管道：classify → rewrite → expand → route。

        Args:
            query: 用户原始查询

        Returns:
            完整的 QueryProfile
        """
        profile = QueryProfile(raw_query=query)

        # 1. Normalize
        profile.normalized_query = self._normalize(query)
        profile.terms = self._extract_terms(query)

        # 2. Classify domain
        profile.domain = self._classify_domain(query)

        # 3. Intent classification
        profile.intent_result = self._classify_intent(query)

        # 4. Rewrite query
        profile.rewritten_query = self._rewrite(query)

        # 5. Expand synonyms (tags)
        profile.tags = self._expand_synonyms(query, profile.domain)

        # 6. Extract entities
        profile.entities = self._extract_entities(query)

        # 7. Route to retrieval strategy
        profile.retrieval_strategy = self._route(query, profile)

        return profile

    # -------------------------------------------------------------------
    # Step 1: Normalize
    # -------------------------------------------------------------------

    def _normalize(self, query: str) -> str:
        """标准化查询：去多余空格、统一标点。"""
        # 去除首尾空格，统一内部空格
        normalized = " ".join(query.split())
        # 统一全角/半角标点
        normalized = normalized.replace("？", "?").replace("，", ",")
        return normalized

    def _extract_terms(self, query: str) -> frozenset[str]:
        """提取查询词集合（去停用词）。"""
        stopwords = {"的", "了", "在", "是", "我", "有", "和", "就",
                      "the", "a", "an", "is", "are", "do", "does", "to", "of"}
        # 简单分词：按空格和标点分割
        tokens = re.findall(r"[\w一-鿿]+", query.lower())
        return frozenset(t for t in tokens if t not in stopwords and len(t) > 1)

    # -------------------------------------------------------------------
    # Step 2: Domain Classification
    # -------------------------------------------------------------------

    def _classify_domain(self, query: str) -> str:
        """基于 ALIASES 字典分类领域。"""
        query_lower = query.lower()

        best_domain = "unknown"
        best_score = 0

        for domain, keywords in self.ALIASES.items():
            score = sum(1 for kw in keywords if kw.lower() in query_lower)
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain

    # -------------------------------------------------------------------
    # Step 3: Intent Classification
    # -------------------------------------------------------------------

    def _classify_intent(self, query: str) -> Any:
        """意图分类。"""
        if self._intent_classifier is not None:
            try:
                return self._intent_classifier(query)
            except Exception as e:
                logger.warning("[QueryProfiler] Intent classification error: %s", e)
        return None

    # -------------------------------------------------------------------
    # Step 4: Query Rewriting
    # -------------------------------------------------------------------

    def _rewrite(self, query: str) -> str:
        """查询改写。"""
        if self._query_rewriter is not None:
            try:
                result = self._query_rewriter.rewrite(query)
                if hasattr(result, "rewritten_query") and result.rewritten_query:
                    return result.rewritten_query
            except Exception as e:
                logger.warning("[QueryProfiler] Query rewrite error: %s", e)

        # 简单标准化作为 fallback
        return self._normalize(query)

    # -------------------------------------------------------------------
    # Step 5: Synonym Expansion
    # -------------------------------------------------------------------

    def _expand_synonyms(self, query: str, domain: str) -> frozenset[str]:
        """基于领域同义词扩展标签。"""
        tags: set[str] = set()

        # 添加匹配领域的同义词
        if domain in self.ALIASES:
            query_lower = query.lower()
            for kw in self.ALIASES[domain]:
                if kw.lower() in query_lower:
                    tags.add(kw)

        # 添加查询中的关键词
        terms = self._extract_terms(query)
        tags.update(terms)

        return frozenset(tags)

    # -------------------------------------------------------------------
    # Step 6: Entity Extraction
    # -------------------------------------------------------------------

    _ENTITY_PATTERNS = [
        (r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", "PERSON"),
        (r"\b[A-Z]{2,}\b", "ACRONYM"),
        (r"\b\d{4}-\d{2}-\d{2}\b", "DATE"),
        (r"https?://\S+", "URL"),
        (r"\b[\w.-]+@[\w.-]+\.\w+\b", "EMAIL"),
    ]

    def _extract_entities(self, query: str) -> dict[str, list[str]]:
        """提取查询中的命名实体。"""
        entities: dict[str, list[str]] = {}
        for pattern, label in self._ENTITY_PATTERNS:
            matches = re.findall(pattern, query)
            if matches:
                entities.setdefault(label, []).extend(matches)
        return entities

    # -------------------------------------------------------------------
    # Step 7: Retrieval Strategy Routing
    # -------------------------------------------------------------------

    def _route(self, query: str, profile: QueryProfile) -> Any:
        """选择检索策略。"""
        if self._intent_router is not None and profile.intent_result is not None:
            try:
                return self._intent_router.route(
                    query=query,
                    intent=profile.intent_result,
                )
            except Exception as e:
                logger.warning("[QueryProfiler] Intent routing error: %s", e)

        # 基于 domain 的简单路由
        from tools.rag.cognitive.rag_cognitive import RetrievalStrategy

        if profile.domain == "code_gen":
            return RetrievalStrategy(
                mode="cognitive", use_bm25=True, use_vector=True,
                use_graph=True, use_skill=True, use_memory=True,
            )
        elif profile.domain == "quality_check":
            return RetrievalStrategy(
                mode="search", use_bm25=True, use_vector=True,
                rerank_top_k=5,
            )
        else:
            return RetrievalStrategy(
                mode="search", use_bm25=True, use_vector=True,
                rerank_top_k=5,
            )
