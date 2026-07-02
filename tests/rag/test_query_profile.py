# tests/rag/test_query_profile.py

"""
tests/rag/test_query_profile.py — QueryProfiler 单元测试。

覆盖：领域分类、同义词扩展、实体提取、检索策略选择、完整管道。
"""

from __future__ import annotations

import pytest
from tools.rag.search.query_profile import QueryProfiler, QueryProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def profiler() -> QueryProfiler:
    """创建默认 QueryProfiler（无外部依赖）。"""
    return QueryProfiler()


@pytest.fixture
def profiler_with_classifier() -> QueryProfiler:
    """创建带 IntentClassifier 的 QueryProfiler。"""
    from tools.rag.cognitive.rag_cognitive import IntentClassifier, IntentRouter
    return QueryProfiler(
        intent_classifier=IntentClassifier(),
        intent_router=IntentRouter(),
    )


# ---------------------------------------------------------------------------
# Tests: Domain Classification
# ---------------------------------------------------------------------------

class TestDomainClassification:
    def test_build_profile_code_gen(self, profiler: QueryProfiler):
        """code_gen 领域识别。"""
        profile = profiler.build_profile("帮我生成用户登录模块")
        assert profile.domain == "code_gen"

    def test_build_profile_quality_check(self, profiler: QueryProfiler):
        """quality_check 领域识别。"""
        profile = profiler.build_profile("检查代码质量")
        assert profile.domain == "quality_check"

    def test_build_profile_documentation(self, profiler: QueryProfiler):
        """documentation 领域识别。"""
        profile = profiler.build_profile("帮助文档在哪里？")
        assert profile.domain == "documentation"

    def test_build_profile_unknown_domain(self, profiler: QueryProfiler):
        """未知领域 fallback。"""
        profile = profiler.build_profile("asdf qwer zxcv")
        assert profile.domain == "unknown"

    def test_build_profile_english_code_gen(self, profiler: QueryProfiler):
        """英文 code_gen 查询。"""
        profile = profiler.build_profile("generate a user authentication module")
        assert profile.domain == "code_gen"


# ---------------------------------------------------------------------------
# Tests: Synonym Expansion
# ---------------------------------------------------------------------------

class TestSynonymExpansion:
    def test_synonyms_expansion_code_gen(self, profiler: QueryProfiler):
        """code_gen 领域同义词扩展。"""
        profile = profiler.build_profile("生成代码")
        # tags 应包含匹配的同义词
        assert len(profile.tags) > 0
        # "生成" 或 "代码" 应在 tags 中
        assert any("生成" in tag or "代码" in tag or "code" in tag.lower()
                   for tag in profile.tags)

    def test_synonyms_expansion_quality(self, profiler: QueryProfiler):
        """quality_check 领域同义词扩展。"""
        profile = profiler.build_profile("检查质量")
        assert len(profile.tags) > 0

    def test_tags_include_query_terms(self, profiler: QueryProfiler):
        """tags 包含查询中的关键词。"""
        profile = profiler.build_profile("用户登录模块")
        # "登录" 或 "模块" 应该作为 term 出现在 tags 中
        all_tags_lower = " ".join(t.lower() for t in profile.tags)
        assert "登录" in all_tags_lower or "模块" in all_tags_lower


# ---------------------------------------------------------------------------
# Tests: Entity Extraction
# ---------------------------------------------------------------------------

class TestEntityExtraction:
    def test_entities_extraction_url(self, profiler: QueryProfiler):
        """URL 实体提取。"""
        profile = profiler.build_profile("查看 https://example.com 的文档")
        assert "URL" in profile.entities
        assert "https://example.com" in profile.entities["URL"]

    def test_entities_extraction_email(self, profiler: QueryProfiler):
        """Email 实体提取。"""
        profile = profiler.build_profile("联系 test@example.com")
        assert "EMAIL" in profile.entities

    def test_entities_extraction_date(self, profiler: QueryProfiler):
        """日期实体提取。"""
        profile = profiler.build_profile("查看 2025-01-15 的记录")
        assert "DATE" in profile.entities

    def test_entities_extraction_acronym(self, profiler: QueryProfiler):
        """缩写实体提取。"""
        profile = profiler.build_profile("JWT 认证实现")
        assert "ACRONYM" in profile.entities
        assert "JWT" in profile.entities["ACRONYM"]

    def test_no_entities(self, profiler: QueryProfiler):
        """无实体时返回空 dict。"""
        profile = profiler.build_profile("用户登录模块")
        assert profile.entities == {}


# ---------------------------------------------------------------------------
# Tests: Retrieval Strategy
# ---------------------------------------------------------------------------

class TestRetrievalStrategy:
    def test_retrieval_strategy_code_gen(self, profiler: QueryProfiler):
        """code_gen 领域选择 cognitive 策略。"""
        profile = profiler.build_profile("生成代码")
        assert profile.retrieval_strategy is not None
        assert profile.retrieval_strategy.mode == "cognitive"

    def test_retrieval_strategy_quality_check(self, profiler: QueryProfiler):
        """quality_check 领域选择 search 策略。"""
        profile = profiler.build_profile("检查质量")
        assert profile.retrieval_strategy is not None
        assert profile.retrieval_strategy.mode == "search"

    def test_retrieval_strategy_documentation(self, profiler: QueryProfiler):
        """documentation 领域选择 search 策略。"""
        profile = profiler.build_profile("查看文档")
        assert profile.retrieval_strategy is not None
        assert profile.retrieval_strategy.mode == "search"

    def test_retrieval_strategy_unknown(self, profiler: QueryProfiler):
        """未知领域 fallback 到 search 策略。"""
        profile = profiler.build_profile("random query")
        assert profile.retrieval_strategy is not None
        assert profile.retrieval_strategy.mode == "search"


# ---------------------------------------------------------------------------
# Tests: Full Pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_profile_immutable_fields(self, profiler: QueryProfiler):
        """QueryProfile 字段类型正确。"""
        profile = profiler.build_profile("生成用户登录模块")
        assert isinstance(profile.raw_query, str)
        assert isinstance(profile.normalized_query, str)
        assert isinstance(profile.terms, frozenset)
        assert isinstance(profile.tags, frozenset)
        assert isinstance(profile.entities, dict)

    def test_normalized_query(self, profiler: QueryProfiler):
        """标准化查询正确。"""
        profile = profiler.build_profile("  用户  登录  模块  ")
        # 多余空格被去除
        assert "   " not in profile.normalized_query

    def test_terms_extracted(self, profiler: QueryProfiler):
        """查询词被正确提取。"""
        profile = profiler.build_profile("用户登录模块")
        assert len(profile.terms) > 0
        # 停用词被去除
        assert "的" not in profile.terms

    def test_with_injected_classifier(self, profiler_with_classifier: QueryProfiler):
        """使用注入的 IntentClassifier。"""
        profile = profiler_with_classifier.build_profile("生成代码")
        assert profile.intent_result is not None
        assert profile.retrieval_strategy is not None

    def test_rewritten_query_fallback(self, profiler: QueryProfiler):
        """无 QueryRewriter 时 rewritten_query 等于 normalized。"""
        profile = profiler.build_profile("test query")
        assert profile.rewritten_query == profile.normalized_query


# ---------------------------------------------------------------------------
# Tests: Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_query(self, profiler: QueryProfiler):
        """空查询不崩溃。"""
        profile = profiler.build_profile("")
        assert profile.raw_query == ""
        assert profile.domain == "unknown"

    def test_single_char_query(self, profiler: QueryProfiler):
        """单字符查询不崩溃。"""
        profile = profiler.build_profile("a")
        assert profile.raw_query == "a"

    def test_mixed_language(self, profiler: QueryProfiler):
        """中英文混合查询。"""
        profile = profiler.build_profile("实现 user authentication 模块")
        assert profile.domain == "code_gen"
        assert len(profile.terms) > 0

    def test_aliases_class_attribute(self):
        """ALIASES 类属性包含预期领域。"""
        assert "code_gen" in QueryProfiler.ALIASES
        assert "quality_check" in QueryProfiler.ALIASES
        assert "documentation" in QueryProfiler.ALIASES
