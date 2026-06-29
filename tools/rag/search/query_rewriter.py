"""LLM 查询扩展 / 改写 — Coze 风格的生产级特性。

功能:
    1. Query Rewriting — LLM 将用户原始查询改写为更精确的表达
    2. Query Expansion — 生成多个子查询以扩大召回范围
    3. Query Decomposition — 将复杂查询分解为简单子问题
    4. HyDE (Hypothetical Document Embeddings) — 生成假答案做向量检索

Usage:
    from tools.rag import QueryRewriter

    rewriter = QueryRewriter()

    # 改写
    result = rewriter.rewrite("Python怎么读取CSV?")

    # 扩展
    results = rewriter.expand("机器学习", num_queries=3)

    # HyDE
    result = rewriter.hyde("什么是深度学习?")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from tools.rag.rag_types import RAGConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 改写结果数据结构
# ---------------------------------------------------------------------------

@dataclass
class RewriteResult:
    """查询改写的结果。"""
    original_query: str
    rewritten_query: str
    expansions: list[str] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)
    hypothetical_answer: str = ""
    method: str = "rewrite"                   # "rewrite" | "expand" | "decompose" | "hyde"


# ---------------------------------------------------------------------------
# Query Rewriter
# ---------------------------------------------------------------------------

class QueryRewriter:
    """LLM 驱动的查询改写 / 扩展 / 分解引擎。

    提供 4 种策略:
        rewrite  — 改写用户查询为更精确、完整的表达
        expand   — 生成多个同义/相关查询扩大召回
        decompose — 将复杂查询拆分为子问题
        hyde     — 生成假答案做更好的向量匹配

    支持 mock 模式 (无 API key 时使用规则模板) 和真实 LLM 模式。
    """

    # 规则模板 (mock 模式使用)
    REWRITE_RULES: list[tuple[str, str]] = [
        # 中文口语 → 正式表达
        (r"怎么", "如何实现"),
        (r"咋", "如何"),
        (r"咋样", "怎么样"),
        (r"啥", "什么"),
        (r"咋弄", "怎么处理"),
        (r"咋用", "如何使用"),
        (r"咋办", "怎么办"),
        (r"咋学", "如何学习"),
        (r"咋写", "如何编写"),
        (r"咋调", "如何调试"),
        (r"咋配", "如何配置"),
        (r"咋装", "如何安装"),
        (r"咋跑", "如何运行"),
        (r"咋部署", "如何部署"),
        (r"吗\??", "?"),
    ]

    EXPANSION_TEMPLATES: dict[str, list[str]] = {
        "how_to": [
            "实现{query}的方法",
            "{query}的步骤",
            "{query}的教程",
            "{query}的最佳实践",
        ],
        "what_is": [
            "{query}是什么",
            "{query}的定义",
            "{query}的概念",
            "{query}的介绍",
        ],
        "why": [
            "{query}的原因",
            "为什么{query}",
            "{query}的原理",
        ],
        "compare": [
            "{query}的区别",
            "{query}的对比",
            "{query}的优缺点",
        ],
    }

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()

    # ---- 公共 API ---------------------------------------------------------

    def rewrite(self, query: str) -> RewriteResult:
        """改写用户查询为更精确的表达。

        如果有 LLM，使用 LLM 改写；否则使用规则模板。

        Args:
            query: 原始用户查询。

        Returns:
            RewriteResult 包含改写后的查询。
        """
        if not query.strip():
            return RewriteResult(original_query=query, rewritten_query=query)

        if self.config.llm_provider != "mock":
            return self._llm_rewrite(query)
        return self._rule_rewrite(query)

    def expand(self, query: str, num_queries: int = 3) -> list[RewriteResult]:
        """生成多个扩展查询以扩大召回范围。

        Args:
            query: 原始查询。
            num_queries: 生成数量。

        Returns:
            多个 RewriteResult 列表。
        """
        if not query.strip():
            return []

        if self.config.llm_provider != "mock":
            return self._llm_expand(query, num_queries)
        return self._rule_expand(query, num_queries)

    def decompose(self, query: str) -> RewriteResult:
        """将复杂查询分解为子问题。

        Args:
            query: 复杂查询。

        Returns:
            RewriteResult 包含子查询列表。
        """
        if not query.strip():
            return RewriteResult(original_query=query, rewritten_query=query)

        if self.config.llm_provider != "mock":
            return self._llm_decompose(query)
        return self._rule_decompose(query)

    def hyde(self, query: str) -> RewriteResult:
        """HyDE: 生成假答案做更好的向量检索匹配。

        原理: 查询→LLM 生成假答案→用假答案做 embedding 检索
        比直接用查询做 embedding 检索更准确。

        Args:
            query: 用户查询。

        Returns:
            RewriteResult 包含假答案。
        """
        if not query.strip():
            return RewriteResult(original_query=query, rewritten_query=query)

        if self.config.llm_provider != "mock":
            return self._llm_hyde(query)
        return self._rule_hyde(query)

    def rewrite_for_retrieval(self, query: str) -> list[str]:
        """一站式查询改写: 返回所有可用于检索的查询变体。

        合并 rewrite + expand + hyde 的结果。

        Args:
            query: 原始查询。

        Returns:
            查询字符串列表 (原始 + 改写 + 扩展 + HyDE)。
        """
        queries = [query]

        # Rewrite
        rewritten = self.rewrite(query)
        if rewritten.rewritten_query != query:
            queries.append(rewritten.rewritten_query)

        # Expand
        expansions = self.expand(query, num_queries=2)
        for exp in expansions:
            if exp.rewritten_query != query and exp.rewritten_query not in queries:
                queries.append(exp.rewritten_query)

        # HyDE
        hyde_result = self.hyde(query)
        if hyde_result.hypothetical_answer:
            queries.append(hyde_result.hypothetical_answer)

        return queries

    # ---- LLM 模式 ---------------------------------------------------------

    def _llm_rewrite(self, query: str) -> RewriteResult:
        """使用 LLM 改写查询。"""
        prompt = (
            f"你是一个搜索查询改写助手。将用户的原始查询改写为更精确、"
            f"更完整的搜索查询。只输出改写后的查询，不要解释。\n\n"
            f"原始查询: {query}\n"
            f"改写查询:"
        )
        try:
            response = self._call_llm(prompt, max_tokens=100)
            rewritten = response.strip()
            if rewritten and rewritten != query:
                return RewriteResult(
                    original_query=query,
                    rewritten_query=rewritten,
                    method="rewrite",
                )
        except Exception as e:
            logger.warning("LLM rewrite failed: %s, falling back to rules", e)

        return self._rule_rewrite(query)

    def _llm_expand(self, query: str, num_queries: int) -> list[RewriteResult]:
        """使用 LLM 生成扩展查询。"""
        prompt = (
            f"你是一个搜索查询扩展助手。给定一个查询，生成 {num_queries} 个"
            f"语义相关但表达不同的查询，以扩大搜索召回范围。\n"
            f"每行一个查询，不要编号，不要解释。\n\n"
            f"原始查询: {query}\n"
            f"扩展查询:"
        )
        try:
            response = self._call_llm(prompt, max_tokens=200)
            lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
            results = []
            for line in lines[:num_queries]:
                # 去除可能的编号前缀
                cleaned = re.sub(r"^\d+[\.\)、\s]+", "", line)
                if cleaned and cleaned != query:
                    results.append(RewriteResult(
                        original_query=query,
                        rewritten_query=cleaned,
                        method="expand",
                    ))
            return results if results else self._rule_expand(query, num_queries)
        except Exception as e:
            logger.warning("LLM expand failed: %s, falling back to rules", e)
            return self._rule_expand(query, num_queries)

    def _llm_decompose(self, query: str) -> RewriteResult:
        """使用 LLM 分解复杂查询。"""
        prompt = (
            f"你是一个查询分解助手。将复杂查询分解为 2-3 个简单子问题。\n"
            f"每行一个子问题，不要编号，不要解释。\n\n"
            f"复杂查询: {query}\n"
            f"子问题:"
        )
        try:
            response = self._call_llm(prompt, max_tokens=200)
            lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
            sub_queries = []
            for line in lines[:3]:
                cleaned = re.sub(r"^\d+[\.\)、\s]+", "", line)
                if cleaned:
                    sub_queries.append(cleaned)
            if sub_queries:
                return RewriteResult(
                    original_query=query,
                    rewritten_query=sub_queries[0],
                    sub_queries=sub_queries,
                    method="decompose",
                )
        except Exception as e:
            logger.warning("LLM decompose failed: %s, falling back to rules", e)

        return self._rule_decompose(query)

    def _llm_hyde(self, query: str) -> RewriteResult:
        """使用 LLM 生成假答案 (HyDE)。"""
        prompt = (
            f"你是一个知识助手。给定一个问题，生成一个简洁、准确的"
            f"假答案（100-200字），用于语义检索。只输出答案内容。\n\n"
            f"问题: {query}\n"
            f"假答案:"
        )
        try:
            response = self._call_llm(prompt, max_tokens=300)
            answer = response.strip()
            if answer:
                return RewriteResult(
                    original_query=query,
                    rewritten_query=query,
                    hypothetical_answer=answer,
                    method="hyde",
                )
        except Exception as e:
            logger.warning("LLM HyDE failed: %s, falling back to rules", e)

        return self._rule_hyde(query)

    def _call_llm(self, prompt: str, max_tokens: int = 256) -> str:
        """调用 LLM。"""
        from tools.llm import create_llm_provider

        provider = create_llm_provider(backend=self.config.llm_provider)
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=0.3)
        if response.success:
            return response.content
        raise RuntimeError(f"LLM returned error: {response.error}")

    # ---- 规则模板模式 (fallback) ------------------------------------------

    def _rule_rewrite(self, query: str) -> RewriteResult:
        """使用规则模板改写查询。"""
        result = query
        for pattern, replacement in self.REWRITE_RULES:
            result = re.sub(pattern, replacement, result)
        return RewriteResult(
            original_query=query,
            rewritten_query=result,
            method="rewrite",
        )

    def _rule_expand(self, query: str, num_queries: int) -> list[RewriteResult]:
        """使用模板生成扩展查询。"""
        results = []
        # 检测查询类型
        templates: list[str] = []
        lower = query.lower()
        if any(w in lower for w in ["如何", "怎么", "怎样", "怎么", "how to", "how"]):
            templates = self.EXPANSION_TEMPLATES["how_to"]
        elif any(w in lower for w in ["什么是", "是什么", "啥是", "what is", "what"]):
            templates = self.EXPANSION_TEMPLATES["what_is"]
        elif any(w in lower for w in ["为什么", "为啥", "why"]):
            templates = self.EXPANSION_TEMPLATES["why"]
        elif any(w in lower for w in ["区别", "对比", "比较", "compare", "vs"]):
            templates = self.EXPANSION_TEMPLATES["compare"]
        else:
            # 默认模板
            templates = [f"{query}的方法", f"{query}的教程", f"{query}详解"]

        for tmpl in templates[:num_queries]:
            expanded = tmpl.format(query=query)
            if expanded != query:
                results.append(RewriteResult(
                    original_query=query,
                    rewritten_query=expanded,
                    method="expand",
                ))

        return results

    def _rule_decompose(self, query: str) -> RewriteResult:
        """使用规则分解查询。"""
        # 简单的基于连词的分解
        separators = [
            r"\s*并且\s*", r"\s*和\s*", r"\s*以及\s*",
            r"\s*及\s*", r"\s*与\s*", r"\s*,\s*", r"\s*，\s*",
            r"\s*;\s*", r"\s*；\s*",
        ]
        pattern = "|".join(separators)
        parts = re.split(pattern, query)

        if len(parts) <= 1:
            # 无法分解，返回原查询
            return RewriteResult(
                original_query=query,
                rewritten_query=query,
                sub_queries=[query],
                method="decompose",
            )

        sub_queries = [p.strip() for p in parts if p.strip()]
        return RewriteResult(
            original_query=query,
            rewritten_query=sub_queries[0] if sub_queries else query,
            sub_queries=sub_queries,
            method="decompose",
        )

    def _rule_hyde(self, query: str) -> RewriteResult:
        """规则模式的 HyDE 占位。

        没有 LLM 时无法生成有意义的假答案，返回空。
        """
        return RewriteResult(
            original_query=query,
            rewritten_query=query,
            hypothetical_answer="",
            method="hyde",
        )

    def __repr__(self) -> str:
        return f"QueryRewriter(provider={self.config.llm_provider})"
