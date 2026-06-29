"""Tests for FeedbackStore and RealGRPOTrainer."""

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from tools.rag.rag_types import RAGConfig, Document
from tools.rag.feedback.rag_feedback import (
    FeedbackSample,
    FeedbackStore,
    GRPOTrainer,
    GRPOStepResult,
    GRPOTrajectory,
    RealGRPOTrainer,
    StubPolicy,
    LLMPolicy,
    default_reward_function,
)


# ---------------------------------------------------------------------------
# FeedbackSample
# ---------------------------------------------------------------------------

class TestFeedbackSample:
    def test_defaults(self):
        s = FeedbackSample(query="q", response="r", rating=4.0)
        assert s.query == "q"
        assert s.response == "r"
        assert s.rating == 4.0
        assert s.feedback_type == "rating"
        assert s.user == "anonymous"
        assert s.timestamp > 0

    def test_all_fields(self):
        s = FeedbackSample(
            query="How to sort?",
            response="Use sorted()",
            rating=5.0,
            feedback_type="rating",
            user="user_1",
            metadata={"source": "cli"},
        )
        assert s.user == "user_1"
        assert s.metadata["source"] == "cli"


# ---------------------------------------------------------------------------
# FeedbackStore
# ---------------------------------------------------------------------------

class TestFeedbackStore:
    @pytest.fixture
    def store(self, tmp_path):
        return FeedbackStore(path=str(tmp_path / "test_feedback.json"))

    def test_add_rating(self, store):
        s = store.add_rating("q1", "r1", 4.5)
        assert s.rating == 4.5
        assert s.feedback_type == "rating"
        assert store.size == 1

    def test_rating_clamped(self, store):
        s = store.add_rating("q", "r", 10.0)
        assert s.rating == 5.0
        s2 = store.add_rating("q", "r", -1.0)
        assert s2.rating == 1.0

    def test_add_preference(self, store):
        s = store.add_preference("q", "chosen", "rejected")
        assert s.feedback_type == "preference"
        assert s.chosen == "chosen"
        assert s.rejected == "rejected"

    def test_add_correction(self, store):
        s = store.add_correction("q", "wrong", "correct")
        assert s.feedback_type == "correction"
        assert s.correction == "correct"

    def test_get_samples(self, store):
        store.add_rating("q1", "r1", 4.0)
        store.add_rating("q2", "r2", 3.0)
        samples = store.get_samples()
        assert len(samples) == 2

    def test_get_samples_limited(self, store):
        for i in range(10):
            store.add_rating(f"q{i}", f"r{i}", 3.0)
        samples = store.get_samples(n=3)
        assert len(samples) == 3

    def test_get_samples_by_type(self, store):
        store.add_rating("q1", "r1", 4.0)
        store.add_preference("q2", "chosen", "rejected")
        store.add_rating("q3", "r3", 5.0)
        ratings = store.get_samples_by_type("rating")
        assert len(ratings) == 2
        prefs = store.get_samples_by_type("preference")
        assert len(prefs) == 1

    def test_get_reward_pairs_rating(self, store):
        store.add_rating("q1", "r1", 4.0)
        store.add_rating("q2", "r2", 2.0)
        pairs = store.get_reward_pairs()
        assert len(pairs) == 2
        # rating 4 -> (4-3)/2 = 0.5
        assert abs(pairs[0][2] - 0.5) < 1e-6
        # rating 2 -> (2-3)/2 = -0.5
        assert abs(pairs[1][2] - (-0.5)) < 1e-6

    def test_get_reward_pairs_preference(self, store):
        store.add_preference("q", "chosen", "rejected")
        pairs = store.get_reward_pairs()
        assert len(pairs) == 2
        assert pairs[0][2] == 1.0   # chosen
        assert pairs[1][2] == -1.0  # rejected

    def test_get_reward_pairs_correction(self, store):
        store.add_correction("q", "wrong", "correct")
        pairs = store.get_reward_pairs()
        assert len(pairs) == 2
        assert pairs[0][2] == -1.0  # original wrong
        assert pairs[1][2] == 1.0   # correction

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "persist_feedback.json")
        store1 = FeedbackStore(path=path)
        store1.add_rating("q1", "r1", 5.0)

        store2 = FeedbackStore(path=path)
        assert store2.size == 1
        samples = store2.get_samples()
        assert samples[0].rating == 5.0

    def test_corrupted_file(self, tmp_path):
        path = tmp_path / "corrupt_feedback.json"
        path.write_text("{invalid", encoding="utf-8")
        store = FeedbackStore(path=str(path))
        assert store.size == 0

    def test_clear(self, store):
        store.add_rating("q", "r", 3.0)
        store.add_rating("q2", "r2", 4.0)
        assert store.size == 2
        store.clear()
        assert store.size == 0

    def test_len(self, store):
        assert len(store) == 0
        store.add_rating("q", "r", 3.0)
        assert len(store) == 1

    def test_repr(self, store):
        store.add_rating("q", "r", 3.0)
        r = repr(store)
        assert "1" in r


# ---------------------------------------------------------------------------
# RealGRPOTrainer
# ---------------------------------------------------------------------------

class TestRealGRPOTrainer:
    @pytest.fixture
    def trainer(self, tmp_path):
        import uuid
        config = RAGConfig(grpo_epochs=3, grpo_learning_rate=0.01)
        path = str(tmp_path / f"grpo_{uuid.uuid4().hex}.json")
        store = FeedbackStore(path=path)
        return RealGRPOTrainer(config, feedback=store)

    def test_init(self, trainer):
        assert trainer.step_count == 0
        assert trainer.feedback is not None

    def test_train_empty_feedback(self, trainer):
        result = trainer.train()
        assert result.num_samples == 0
        assert result.loss == 0.0

    def test_train_with_ratings(self, trainer):
        trainer.feedback.add_rating("How to sort?", "Use sorted()", 5.0)
        trainer.feedback.add_rating("How to loop?", "Use for loop", 4.0)
        trainer.feedback.add_rating("Bad answer", "I don't know", 1.0)

        result = trainer.train()
        assert result.num_samples > 0
        assert result.mean_reward != 0.0
        assert trainer.step_count == 1

    def test_train_with_preferences(self, trainer):
        trainer.feedback.add_preference(
            "Best sorting method?",
            "Use sorted() for simplicity",
            "Use bubble sort",
        )
        result = trainer.train()
        # 1 preference = 2 reward pairs (chosen + rejected)
        assert result.num_samples >= 2
        assert trainer.step_count == 1

    def test_train_with_corrections(self, trainer):
        trainer.feedback.add_correction(
            "What is Python?",
            "A snake",
            "A programming language",
        )
        result = trainer.train()
        # 1 correction = 2 reward pairs (wrong + correct)
        assert result.num_samples >= 2

    def test_train_multiple_epochs(self, trainer):
        trainer.feedback.add_rating("q1", "r1", 5.0)
        trainer.feedback.add_rating("q2", "r2", 1.0)
        result = trainer.train()
        assert trainer.step_count == 1

    def test_history(self, trainer):
        trainer.feedback.add_rating("q", "r", 4.0)
        trainer.train()
        assert len(trainer.history) == 1
        assert trainer.history[0].num_samples > 0

    def test_weights_summary_before_train(self, trainer):
        summary = trainer.get_weights_summary()
        assert summary["status"] == "untrained"
        assert summary["dim"] == 0

    def test_weights_summary_after_train(self, trainer):
        trainer.feedback.add_rating("How to sort?", "Use sorted()", 5.0)
        trainer.feedback.add_rating("How to loop?", "Use for loop", 4.0)
        trainer.train()
        summary = trainer.get_weights_summary()
        assert summary["status"] == "trained"
        assert summary["dim"] > 0

    def test_extract_features(self, trainer):
        features = trainer._extract_features("How to sort?", "Use sorted() function")
        assert isinstance(features, np.ndarray)
        assert len(features) > 0
        assert features.sum() > 0  # some features should be non-zero

    def test_extract_features_empty(self, trainer):
        features = trainer._extract_features("", "")
        assert isinstance(features, np.ndarray)

    def test_score_before_train(self, trainer):
        features = trainer._extract_features("q", "r")
        score = trainer._score(features)
        assert score == 0.0

    def test_score_after_train(self, trainer):
        trainer.feedback.add_rating("q", "r", 5.0)
        trainer.train()
        features = trainer._extract_features("q", "r")
        # After training, score should be computed (may be 0 if no overlap)
        score = trainer._score(features)
        assert isinstance(score, float)

    def test_repr(self, trainer):
        r = repr(trainer)
        assert "FullFeedbackRanker" in r
        assert "steps=0" in r


# ---------------------------------------------------------------------------
# GRPOTrainer (stub) backward compatibility
# ---------------------------------------------------------------------------

class TestGRPOTrainerStub:
    def test_with_stub_policy(self):
        config = RAGConfig()
        trainer = GRPOTrainer(config, policy=StubPolicy())
        result = trainer.train_step(
            prompts=["test prompt"],
            documents=[[]],
        )
        assert result.num_samples == 1
        assert isinstance(result.loss, float)

    def test_empty_prompts(self):
        trainer = GRPOTrainer()
        result = trainer.train_step(prompts=[], documents=[])
        assert result.num_samples == 0
        assert result.loss == 0.0

    def test_history_tracking(self):
        trainer = GRPOTrainer(policy=StubPolicy())
        trainer.train_step(["p1"], [[]])
        trainer.train_step(["p2"], [[]])
        assert len(trainer.history) == 2
        assert trainer.step_count == 2

    def test_repr(self):
        trainer = GRPOTrainer(policy=StubPolicy())
        r = repr(trainer)
        assert "FeedbackRanker" in r
        assert "StubPolicy" in r


# ---------------------------------------------------------------------------
# Reward function
# ---------------------------------------------------------------------------

class TestRewardFunction:
    def test_with_relevant_doc(self):
        from tools.rag.rag_types import Document
        doc = Document(content="Python is a programming language with dynamic typing", source="test")
        reward = default_reward_function(
            query="What is Python?",
            documents=[doc],
            response="Python is a programming language",
        )
        assert reward > 0

    def test_with_empty_documents(self):
        reward = default_reward_function("q", [], "some response")
        assert reward >= 0

    def test_short_response(self):
        from tools.rag.rag_types import Document
        doc = Document(content="test content here", source="test")
        reward = default_reward_function("q", [doc], "hi")
        assert reward < 0.5  # short response penalized


# ---------------------------------------------------------------------------
# GRPOTrajectory & GRPOStepResult
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_trajectory_defaults(self):
        t = GRPOTrajectory(prompt="q", response="r")
        assert t.reward == 0.0
        assert t.log_prob == 0.0

    def test_step_result_defaults(self):
        r = GRPOStepResult(loss=0.5, mean_reward=0.3, reward_baseline=0.3, num_samples=10)
        assert r.per_sample_rewards == []


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestGRPOIntegration:
    def test_feedback_to_training_flow(self, tmp_path):
        """Full flow: add feedback -> train -> check weights."""
        config = RAGConfig(grpo_epochs=5, grpo_learning_rate=0.05)
        path = str(tmp_path / "integration_feedback.json")
        store = FeedbackStore(path=path)

        # Add diverse feedback
        store.add_rating("How to sort a list?", "Use sorted() or list.sort()", 5.0)
        store.add_rating("How to read a file?", "Use open() with context manager", 4.5)
        store.add_rating("Bad response", "I don't know", 1.0)
        store.add_preference("Best loop?", "for loop", "while loop with manual index")

        trainer = RealGRPOTrainer(config, feedback=store)
        result = trainer.train()

        assert result.num_samples > 0
        assert trainer.step_count == 1
        summary = trainer.get_weights_summary()
        assert summary["status"] == "trained"

    def test_feedback_persistence_across_sessions(self, tmp_path):
        """Feedback persists between CLI invocations."""
        path = str(tmp_path / "persist.json")

        store1 = FeedbackStore(path=path)
        store1.add_rating("q", "r", 5.0)

        store2 = FeedbackStore(path=path)
        assert store2.size == 1
        samples = store2.get_samples()
        assert samples[0].rating == 5.0
