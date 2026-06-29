"""Tests for the dual-engine RAG system: SkillLearner, MemoryManager, UserModel, IntentRouter."""

import json
import os
import shutil
import tempfile

import pytest

from tools.rag import (
    RAGConfig,
    Document,
    IntentClassifier,
    IntentResult,
    RAGPipeline,
    LearnedSkill,
    SkillLearner,
    MemoryManager,
    MemoryItem,
    UserModel,
    IntentRouter,
    RetrievalStrategy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DOCS = [
    Document(
        content="Python is a high-level programming language with dynamic semantics. Its high-level built-in data structures make it attractive for rapid application development.",
        source="wiki_python",
        metadata={"category": "programming"},
    ),
    Document(
        content="Machine learning is a subset of artificial intelligence that enables systems to learn and improve from experience without being explicitly programmed.",
        source="wiki_ml",
        metadata={"category": "ai"},
    ),
    Document(
        content="Neural networks are computing systems inspired by biological neural networks. They consist of interconnected nodes that process information using connectionist approaches.",
        source="wiki_nn",
        metadata={"category": "ai"},
    ),
    Document(
        content="Docker is a platform for developing, shipping, and running applications in containers. Containers allow an application to be packaged with all its dependencies.",
        source="docs_docker",
        metadata={"category": "devops"},
    ),
    Document(
        content="Kubernetes is an open-source container orchestration system for automating deployment, scaling, and management of containerized applications.",
        source="docs_k8s",
        metadata={"category": "devops"},
    ),
]


@pytest.fixture
def config():
    return RAGConfig(
        bm25_top_k=5,
        vector_top_k=5,
        graph_top_k=3,
        fusion_top_k=8,
        rerank_top_k=5,
        enable_llm_scorer=False,
    )


@pytest.fixture
def pipeline(config):
    p = RAGPipeline(config)
    p.ingest(SAMPLE_DOCS)
    return p


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="rag_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# SkillLearner tests
# ---------------------------------------------------------------------------

class TestSkillLearner:
    def test_extract_skill_success(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success", "detail": "auth.py"},
            {"action": "run_tests", "result": "success", "detail": "all passed"},
            {"action": "commit", "result": "success", "detail": "feat: add auth"},
        ]
        skill = manager.extract_skill(
            task="实现用户认证模块",
            trajectory=trajectory,
            task_type="code_generation",
        )
        assert skill is not None
        assert skill.task_type == "code_generation"
        assert "write_file" in skill.content
        assert "实现用户认证模块" in skill.content

    def test_extract_skill_fails_on_failure(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success"},
            {"action": "run_tests", "result": "failed"},
        ]
        skill = manager.extract_skill("实现认证", trajectory, "code_generation")
        assert skill is None

    def test_extract_skill_empty_trajectory(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        assert manager.extract_skill("test", []) is None
        assert manager.extract_skill("", [{"action": "x", "result": "success"}]) is None

    def test_match_skill(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success", "detail": "auth module"},
            {"action": "test", "result": "success"},
        ]
        manager.extract_skill("实现用户认证模块", trajectory, "code_generation")

        # Match with same task_type
        matched = manager.match_skill("实现订单管理模块", "code_generation")
        assert matched is not None
        assert matched.task_type == "code_generation"

    def test_match_skill_without_type(self, tmp_dir):
        """Without task_type, matching is stricter but still works for close matches."""
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success", "detail": "auth module"},
        ]
        manager.extract_skill("实现用户认证模块", trajectory, "code_generation")

        # Close match without type filter
        matched = manager.match_skill("实现认证模块设计")
        assert matched is not None

    def test_match_skill_far_apart(self, tmp_dir):
        """Completely unrelated tasks should not match."""
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success"},
        ]
        manager.extract_skill("实现用户认证模块", trajectory, "code_generation")

        # Unrelated task
        matched = manager.match_skill("今天天气怎么样")
        assert matched is None

    def test_match_skill_no_match(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success"},
        ]
        manager.extract_skill("实现用户认证模块", trajectory, "code_generation")

        # Unrelated task should not match
        matched = manager.match_skill("分析销售数据", "analytical", min_score=0.5)
        assert matched is None

    def test_match_skill_increments_usage(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success"},
        ]
        manager.extract_skill("实现用户认证模块", trajectory, "code_generation")

        skill = manager.match_skill("实现用户认证模块", "code_generation")
        assert skill is not None
        assert skill.usage_count >= 1

    def test_improve_skill(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success"},
        ]
        skill = manager.extract_skill("实现认证", trajectory, "code_generation")
        assert skill is not None

        original_len = len(skill.content)
        improved = manager.improve_skill(skill, {"rating": 0.9, "note": "需要添加错误处理"})
        assert len(improved.content) > original_len
        assert improved.avg_rating > 0

    def test_list_skills(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        manager.extract_skill("实现认证", [{"action": "w", "result": "success"}], "code_generation")
        manager.extract_skill("分析数据", [{"action": "w", "result": "success"}], "analytical")

        all_skills = manager.list_skills()
        assert len(all_skills) == 2

        code_skills = manager.list_skills("code_generation")
        assert len(code_skills) == 1

    def test_get_stats(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        manager.extract_skill("实现认证", [{"action": "w", "result": "success"}], "code_generation")

        stats = manager.get_stats()
        assert stats["total"] == 1
        assert "code_generation" in stats["types"]

    def test_persistence(self, tmp_dir):
        # Create and save
        manager1 = SkillLearner(skills_dir=tmp_dir)
        manager1.extract_skill("实现认证", [{"action": "w", "result": "success"}], "code_generation")

        # Load in new instance
        manager2 = SkillLearner(skills_dir=tmp_dir)
        skills = manager2.list_skills()
        assert len(skills) == 1

    def test_record_usage(self, tmp_dir):
        manager = SkillLearner(skills_dir=tmp_dir)
        skill = manager.extract_skill("test", [{"action": "w", "result": "success"}])
        assert skill is not None

        initial_count = skill.usage_count
        manager.record_usage(skill, success=True)
        assert skill.usage_count == initial_count + 1
        assert skill.success_count >= 1


# ---------------------------------------------------------------------------
# MemoryManager tests
# ---------------------------------------------------------------------------

class TestMemoryManager:
    def test_post_turn_stores_facts(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path)
        mm.post_turn(
            query="What is Python?",
            response="Python is a high-level programming language. It is widely used for web development.",
        )
        all_mem = mm.get_all()
        assert len(all_mem) > 0

    def test_pre_turn_recall(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path)
        mm.post_turn("What is Python?", "Python is a high-level programming language.")

        memories = mm.pre_turn("Tell me about Python")
        assert len(memories) > 0

    def test_no_duplicates(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path)
        mm.post_turn("What is Python?", "Python is a programming language.")
        # Exact same call again should not create duplicates
        mm.post_turn("What is Python?", "Python is a programming language.")

        all_mem = mm.get_all()
        # Should not have exact duplicate content
        contents = [m.content for m in all_mem]
        assert len(contents) == len(set(contents))

    def test_persistence(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm1 = MemoryManager(persist_path=path)
        mm1.post_turn("test query", "test response with important information")

        mm2 = MemoryManager(persist_path=path)
        assert len(mm2.get_all()) > 0

    def test_compress(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path, max_memories=50, importance_threshold=0.2)

        for i in range(30):
            mm.post_turn(
                f"What is topic {i}?",
                f"Topic {i} is an important concept in computer science with many practical applications.",
            )

        original_count = len(mm.get_all())
        assert original_count > 10, f"Expected >10 memories, got {original_count}"

        removed = mm.compress(keep_top_fraction=0.5)
        assert removed > 0
        assert len(mm.get_all()) < original_count

    def test_clear(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path)
        mm.post_turn("What is Python?", "Python is a high-level programming language with dynamic semantics.")
        assert len(mm.get_all()) > 0

        mm.clear()
        assert len(mm.get_all()) == 0

    def test_get_stats(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path)
        mm.post_turn("Python is great", "Python is a programming language")

        stats = mm.get_stats()
        assert stats["total"] > 0
        assert "avg_importance" in stats

    def test_max_memories_enforced(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path, max_memories=5)

        for i in range(20):
            mm.post_turn(f"query {i}", f"response {i}")

        assert len(mm.get_all()) <= 5

    def test_importance_threshold(self, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path, importance_threshold=0.9)

        # Low importance response should not be stored
        stored = mm.post_turn("ok", "yes")
        assert len(stored) == 0


# ---------------------------------------------------------------------------
# UserModel tests
# ---------------------------------------------------------------------------

class TestUserModel:
    def test_update_detects_language(self):
        model = UserModel()
        model.update("请帮我写一个 Python 函数")
        assert model.preferred_language == "zh"

    def test_update_detects_topics(self):
        model = UserModel()
        model.update("Write a Python function to sort a list")
        assert "code" in model.common_topics

    def test_update_expertise_expert(self):
        model = UserModel()
        for _ in range(15):
            model.update("Design a microservices architecture with Docker and Kubernetes")
        assert model.expertise_level == "expert"

    def test_update_expertise_beginner(self):
        model = UserModel()
        for _ in range(5):
            model.update("What is Python? How do I install it?")
        assert model.expertise_level == "beginner"

    def test_to_dict_and_back(self):
        model = UserModel()
        model.update("test query", "success")
        data = model.to_dict()

        restored = UserModel.from_dict(data)
        assert restored.expertise_level == model.expertise_level
        assert restored.total_interactions == model.total_interactions

    def test_topic_counts(self):
        model = UserModel()
        model.update("Write Python code")
        model.update("Debug Python code")
        model.update("Deploy Python code")
        assert model.topic_counts["code"] >= 2

    def test_feedback_positive(self):
        model = UserModel()
        model.update("test", "success")
        assert model.total_interactions == 1

    def test_repr(self):
        model = UserModel()
        r = repr(model)
        assert "UserModel" in r


# ---------------------------------------------------------------------------
# IntentRouter tests
# ---------------------------------------------------------------------------

class TestIntentRouter:
    def test_code_generation_routes_to_cognitive(self, config):
        router = IntentRouter(config)
        intent = IntentResult(
            primary_intent="code_generation",
            confidence=0.8,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("实现认证模块", intent)
        assert strategy.mode == "cognitive"
        assert strategy.use_graph is True
        assert strategy.use_skill is True
        assert strategy.use_memory is True

    def test_factual_routes_to_search(self, config):
        router = IntentRouter(config)
        intent = IntentResult(
            primary_intent="factual",
            confidence=0.9,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("What is Python?", intent)
        assert strategy.mode == "search"
        assert strategy.use_bm25 is True
        assert strategy.use_vector is True
        assert strategy.use_graph is False

    def test_analytical_routes_to_hybrid(self, config):
        router = IntentRouter(config)
        intent = IntentResult(
            primary_intent="analytical",
            confidence=0.7,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("Why does this happen?", intent)
        assert strategy.mode == "hybrid"
        assert strategy.use_graph is True
        assert strategy.use_memory is True

    def test_creative_routes_to_search(self, config):
        router = IntentRouter(config)
        intent = IntentResult(
            primary_intent="creative",
            confidence=0.6,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("Write a poem", intent)
        assert strategy.mode == "search"
        assert strategy.use_bm25 is False
        assert strategy.use_vector is True

    def test_low_confidence_uses_all(self, config):
        router = IntentRouter(config)
        intent = IntentResult(
            primary_intent="factual",
            confidence=0.1,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("something", intent)
        # Low confidence should enable all retrievers
        assert strategy.use_bm25 is True
        assert strategy.use_vector is True

    def test_personalize_expert(self, config):
        router = IntentRouter(config)
        model = UserModel()
        for _ in range(10):
            model.update("Design a microservices architecture")
        intent = IntentResult(
            primary_intent="factual",
            confidence=0.9,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("What is Python?", intent, user_model=model)
        # Expert gets fewer results (base 5 - 2 = 3)
        assert strategy.rerank_top_k <= 3

    def test_personalize_beginner(self, config):
        router = IntentRouter(config)
        model = UserModel()
        # Create a beginner user (multiple simple queries, no expert topics)
        for _ in range(5):
            model.update("What is Python?")
        intent = IntentResult(
            primary_intent="factual",
            confidence=0.9,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("What is Python?", intent, user_model=model)
        # Beginner gets more results (base 5 + 2 = 7)
        assert strategy.rerank_top_k >= 5

    def test_strategy_to_dict(self, config):
        router = IntentRouter(config)
        intent = IntentResult(
            primary_intent="code_generation",
            confidence=0.8,
            all_scores={},
            entities=[],
            keywords=[],
        )
        strategy = router.route("test", intent)
        d = strategy.to_dict()
        assert "mode" in d
        assert "use_graph" in d


# ---------------------------------------------------------------------------
# Cognitive Pipeline integration tests
# ---------------------------------------------------------------------------

class TestCognitivePipeline:
    def test_query_cognitive_basic(self, pipeline, config):
        result = pipeline.query_cognitive("实现用户认证模块")
        assert result.query == "实现用户认证模块"
        assert result.metadata["mode"] == "cognitive"
        assert result.intent.primary_intent == "code_generation"

    def test_query_cognitive_with_skill_manager(self, pipeline, tmp_dir):
        sm = SkillLearner(skills_dir=tmp_dir)
        # Pre-register a skill
        sm.extract_skill(
            "实现认证模块",
            [{"action": "write_file", "result": "success"}, {"action": "test", "result": "success"}],
            "code_generation",
        )

        result = pipeline.query_cognitive("实现订单认证模块", skill_manager=sm)
        assert result.metadata["skill_matched"] is not None

    def test_query_cognitive_with_memory(self, pipeline, tmp_dir):
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path)
        mm.post_turn("用户上次问了认证逻辑", "认证逻辑使用了 JWT token")

        result = pipeline.query_cognitive("实现认证", memory_manager=mm)
        assert result.metadata["memory_hits"] > 0

    def test_query_cognitive_with_user_model(self, pipeline, tmp_dir):
        model = UserModel()
        for _ in range(15):
            model.update("Design microservices architecture")

        result = pipeline.query_cognitive("实现认证模块", user_model=model)
        assert result.metadata["mode"] == "cognitive"

    def test_query_cognitive_with_all(self, pipeline, tmp_dir):
        sm = SkillLearner(skills_dir=tmp_dir)
        path = os.path.join(tmp_dir, "memory.json")
        mm = MemoryManager(persist_path=path)
        model = UserModel()
        model.update("test")

        result = pipeline.query_cognitive(
            "实现认证模块",
            skill_manager=sm,
            memory_manager=mm,
            user_model=model,
        )
        assert result.metadata["mode"] == "cognitive"
        assert "strategy" in result.metadata

    def test_query_cognitive_extract_skill(self, pipeline, tmp_dir):
        sm = SkillLearner(skills_dir=tmp_dir)
        trajectory = [
            {"action": "write_file", "result": "success", "detail": "auth.py"},
            {"action": "test", "result": "success"},
        ]

        result = pipeline.query_cognitive(
            "实现认证模块",
            skill_manager=sm,
            extract_skill=True,
            trajectory=trajectory,
        )

        skills = sm.list_skills("code_generation")
        assert len(skills) == 1

    def test_query_unchanged(self, pipeline):
        # Original query() should still work
        result = pipeline.query("What is machine learning?")
        assert result.query == "What is machine learning?"
        assert len(result.reranked_documents) > 0

    def test_cognitive_vs_search_different_mode(self, pipeline):
        # Same query, different modes
        result_search = pipeline.query("实现认证")
        result_cognitive = pipeline.query_cognitive("实现认证")

        # Search mode uses all retrievers
        # Cognitive mode uses strategy-based selective retrieval
        assert result_search.intent.primary_intent == result_cognitive.intent.primary_intent
