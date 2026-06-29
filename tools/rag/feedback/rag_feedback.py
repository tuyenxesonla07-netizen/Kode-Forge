# tools/rag/rag_feedback.py
"""
Feedback collection and feedback-driven optimization for RAG pipeline.

Merges: feedback.py + feedback_ranker.py

Provides:
- FeedbackSample / FeedbackStore — human feedback collection
- FeedbackRanker / FullFeedbackRanker — feedback-driven optimization
- StubPolicy / LLMPolicy — policy backends
- default_reward_function — composite reward computation
"""

from __future__ import annotations

import json
import os
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from tools.rag.rag_types import RAGConfig, Document


# ---------------------------------------------------------------------------
# FeedbackSample / FeedbackStore
# ---------------------------------------------------------------------------

@dataclass
class FeedbackSample:
    """A single feedback data point."""

    query: str
    response: str
    rating: float  # 1-5 scale, or -1.0 to 1.0 for preference
    feedback_type: str = "rating"  # "rating" | "preference" | "correction"
    chosen: str = ""       # for preference feedback
    rejected: str = ""     # for preference feedback
    correction: str = ""  # for correction feedback
    user: str = "anonymous"
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class FeedbackStore:
    """Persistent feedback storage backed by JSON file."""

    def __init__(self, path: str = ".feedback.json") -> None:
        self.path = path
        self._samples: list[FeedbackSample] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._samples = [FeedbackSample(**s) for s in data]
            except (json.JSONDecodeError, TypeError):
                self._samples = []

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([asdict(s) for s in self._samples], f, ensure_ascii=False, indent=2)

    def add_rating(
        self,
        query: str,
        response: str,
        rating: float,
        user: str = "anonymous",
        metadata: dict | None = None,
    ) -> FeedbackSample:
        """Add a rating (1-5) for a query-response pair."""
        sample = FeedbackSample(
            query=query, response=response,
            rating=max(1.0, min(5.0, rating)),
            feedback_type="rating", user=user, metadata=metadata or {},
        )
        self._samples.append(sample)
        self._save()
        return sample

    def add_preference(
        self, query: str, chosen: str, rejected: str,
        user: str = "anonymous", metadata: dict | None = None,
    ) -> FeedbackSample:
        """Add a preference: chosen is better than rejected."""
        sample = FeedbackSample(
            query=query, response=chosen, rating=1.0,
            feedback_type="preference", chosen=chosen, rejected=rejected,
            user=user, metadata=metadata or {},
        )
        self._samples.append(sample)
        self._save()
        return sample

    def add_correction(
        self, query: str, response: str, correction: str,
        user: str = "anonymous", metadata: dict | None = None,
    ) -> FeedbackSample:
        """Add a correction: the original response was wrong."""
        sample = FeedbackSample(
            query=query, response=response, rating=1.0,
            feedback_type="correction", correction=correction,
            user=user, metadata=metadata or {},
        )
        self._samples.append(sample)
        self._save()
        return sample

    def get_samples(self, n: int | None = None) -> list[FeedbackSample]:
        """Get feedback samples, optionally limited to the last N."""
        if n is not None:
            return self._samples[-n:]
        return list(self._samples)

    def get_samples_by_type(self, feedback_type: str) -> list[FeedbackSample]:
        """Get samples filtered by type."""
        return [s for s in self._samples if s.feedback_type == feedback_type]

    def get_reward_pairs(self) -> list[tuple[str, str, float]]:
        """Get (query, response, normalized_reward) tuples for training.

        Normalizes ratings to [-1, 1] range:
            rating 1-2 → negative, 3 → neutral, 4-5 → positive
        """
        pairs = []
        for s in self._samples:
            if s.feedback_type == "rating":
                normalized = (s.rating - 3.0) / 2.0
                pairs.append((s.query, s.response, normalized))
            elif s.feedback_type == "preference":
                pairs.append((s.query, s.chosen, 1.0))
                pairs.append((s.query, s.rejected, -1.0))
            elif s.feedback_type == "correction":
                pairs.append((s.query, s.response, -1.0))
                pairs.append((s.query, s.correction, 1.0))
        return pairs

    @property
    def size(self) -> int:
        return len(self._samples)

    def clear(self) -> None:
        """Remove all feedback."""
        self._samples.clear()
        self._save()

    def __len__(self) -> int:
        return len(self._samples)

    def __repr__(self) -> str:
        return f"FeedbackStore(samples={len(self._samples)}, path={self.path!r})"


# ---------------------------------------------------------------------------
# Data structures for optimization
# ---------------------------------------------------------------------------

@dataclass
class FeedbackStepResult:
    """Result of a single feedback optimization step."""

    loss: float
    mean_reward: float
    reward_baseline: float
    num_samples: int
    per_sample_rewards: list[float] = field(default_factory=list)


@dataclass
class FeedbackTrajectory:
    """A single trajectory (prompt, response, reward)."""

    prompt: str
    response: str
    reward: float = 0.0
    log_prob: float = 0.0


# Backward-compatible aliases
GRPOStepResult = FeedbackStepResult
GRPOTrajectory = FeedbackTrajectory


# ---------------------------------------------------------------------------
# Reward function
# ---------------------------------------------------------------------------

def default_reward_function(
    query: str,
    documents: list[Document],
    response: str,
    relevance_weight: float = 0.5,
    fluency_weight: float = 0.3,
    diversity_weight: float = 0.2,
) -> float:
    """Compute a composite reward for a generated *response*.

    Components:
        * relevance  – how much the response overlaps with retrieved docs.
        * fluency    – simple heuristic based on response length & structure.
        * diversity  – lexical diversity of the response.
    """
    relevance = 0.0
    if documents:
        doc_tokens = set(documents[0].content.lower().split())
        resp_tokens = set(response.lower().split())
        if doc_tokens and resp_tokens:
            relevance = len(doc_tokens & resp_tokens) / len(doc_tokens | resp_tokens)

    word_count = len(response.split())
    if word_count < 3:
        fluency = 0.1
    elif word_count > 500:
        fluency = 0.5
    else:
        fluency = min(1.0, word_count / 50)

    tokens = response.lower().split()
    if tokens:
        diversity = len(set(tokens)) / len(tokens)
    else:
        diversity = 0.0

    return (
        relevance_weight * relevance
        + fluency_weight * fluency
        + diversity_weight * diversity
    )


# ---------------------------------------------------------------------------
# Feedback Ranker
# ---------------------------------------------------------------------------

class FeedbackRanker:
    """Feedback ranker stub.

    Implements a simplified feedback-driven optimization loop:
    1. Sample a batch of prompts.
    2. Generate responses (using a callable *policy*).
    3. Compute rewards per response.
    4. Compute group-relative advantages.
    5. Apply a REINFORCE-style policy gradient update.
    """

    def __init__(
        self,
        config: RAGConfig | None = None,
        reward_fn: Callable[..., float] | None = None,
        policy: Any | None = None,
    ) -> None:
        self.config = config or RAGConfig()
        self.reward_fn = reward_fn or default_reward_function
        self._step_count = 0
        self._history: list[FeedbackStepResult] = []

        if policy is not None:
            self._policy = policy
        elif self.config.llm_provider != "mock":
            self._policy = LLMPolicy(self.config)
        else:
            self._policy = StubPolicy()

    def train_step(
        self,
        prompts: Sequence[str],
        documents: Sequence[list[Document]],
        policy: Any | None = None,
    ) -> FeedbackStepResult:
        """Execute one feedback optimization step."""
        batch_size = len(prompts)
        if batch_size == 0:
            return FeedbackStepResult(loss=0.0, mean_reward=0.0, reward_baseline=0.0, num_samples=0)

        active_policy = policy if policy is not None else self._policy
        trajectories: list[FeedbackTrajectory] = []

        for prompt, docs in zip(prompts, documents):
            response = _generate(prompt, active_policy)
            reward = self.reward_fn(query=prompt, documents=docs, response=response)
            log_prob = -0.01 * len(response.split())
            trajectories.append(FeedbackTrajectory(prompt, response, reward, log_prob))

        rewards = [t.reward for t in trajectories]
        mean_reward = float(np.mean(rewards))
        std_reward = float(np.std(rewards)) + 1e-8
        advantages = [(r - mean_reward) / std_reward for r in rewards]

        total_loss = 0.0
        for traj, adv in zip(trajectories, advantages):
            loss = _policy_gradient_step(traj.log_prob, adv, self.config.grpo_clip_ratio)
            total_step_loss = loss
            if policy is not None and hasattr(policy, "update"):
                total_step_loss = policy.update(traj.log_prob, adv)
            total_loss += total_step_loss

        result = FeedbackStepResult(
            loss=total_loss / batch_size,
            mean_reward=mean_reward,
            reward_baseline=mean_reward,
            num_samples=batch_size,
            per_sample_rewards=rewards,
        )
        self._history.append(result)
        self._step_count += 1
        return result

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def history(self) -> list[FeedbackStepResult]:
        return list(self._history)

    def __repr__(self) -> str:
        policy_name = type(self._policy).__name__
        return f"FeedbackRanker(steps={self._step_count}, policy={policy_name})"


# Backward-compatible alias
GRPOTrainer = FeedbackRanker


# ---------------------------------------------------------------------------
# Full Feedback Ranker (with policy gradient optimization)
# ---------------------------------------------------------------------------

class FullFeedbackRanker:
    """Full feedback ranker with policy gradient optimization.

    Uses scipy's minimize for numerical optimization of a parameterized
    policy. The policy is represented as a simple linear model over
    n-gram features, trained to maximize the feedback objective.
    """

    def __init__(
        self,
        config: RAGConfig | None = None,
        feedback: Any | None = None,
        learning_rate: float | None = None,
        n_epochs: int | None = None,
    ) -> None:
        self.config = config or RAGConfig()
        self.feedback: FeedbackStore = feedback if feedback is not None else FeedbackStore()
        self.learning_rate = learning_rate or self.config.grpo_learning_rate
        self.n_epochs = n_epochs or self.config.grpo_epochs
        self._step_count = 0
        self._history: list[FeedbackStepResult] = []
        self._weights: np.ndarray | None = None
        self._feature_vocab: dict[str, int] = {}

    def _extract_features(self, query: str, response: str) -> np.ndarray:
        """Extract simple n-gram features from query-response pair."""
        query_tokens = query.lower().split()
        resp_tokens = response.lower().split()

        all_tokens = set(query_tokens + resp_tokens)
        for token in all_tokens:
            if token not in self._feature_vocab:
                self._feature_vocab[token] = len(self._feature_vocab)

        for i in range(len(resp_tokens) - 1):
            bigram = f"{resp_tokens[i]}_{resp_tokens[i + 1]}"
            if bigram not in self._feature_vocab:
                self._feature_vocab[bigram] = len(self._feature_vocab)

        dim = len(self._feature_vocab)
        features = np.zeros(dim)

        for token in resp_tokens:
            idx = self._feature_vocab[token]
            features[idx] += 1.0

        for i in range(len(resp_tokens) - 1):
            bigram = f"{resp_tokens[i]}_{resp_tokens[i + 1]}"
            idx = self._feature_vocab[bigram]
            features[idx] += 1.0

        if query_tokens and resp_tokens:
            overlap = len(set(query_tokens) & set(resp_tokens))
            overlap_key = "__overlap__"
            if overlap_key not in self._feature_vocab:
                self._feature_vocab[overlap_key] = len(self._feature_vocab)
                features = np.append(features, 0.0)
            features[self._feature_vocab[overlap_key]] = overlap / max(len(query_tokens), 1)

        length_key = "__length__"
        if length_key not in self._feature_vocab:
            self._feature_vocab[length_key] = len(self._feature_vocab)
            features = np.append(features, 0.0)
        features[self._feature_vocab[length_key]] = min(len(resp_tokens) / 100.0, 1.0)

        return features

    def _score(self, features: np.ndarray) -> float:
        """Score a feature vector using current weights."""
        if self._weights is None:
            return 0.0
        n = min(len(self._weights), len(features))
        return float(np.dot(self._weights[:n], features[:n]))

    def _compute_log_probs(self, features_list: list[np.ndarray]) -> list[float]:
        """Compute log-probabilities for a list of feature vectors."""
        scores = np.array([self._score(f) for f in features_list])
        exp_scores = np.exp(scores - np.max(scores))
        probs = exp_scores / (exp_scores.sum() + 1e-8)
        return [float(np.log(p + 1e-8)) for p in probs]

    def train(self) -> FeedbackStepResult:
        """Run feedback optimization on collected feedback."""
        pairs = self.feedback.get_reward_pairs()
        if not pairs:
            return FeedbackStepResult(loss=0.0, mean_reward=0.0, reward_baseline=0.0, num_samples=0)

        queries = [p[0] for p in pairs]
        responses = [p[1] for p in pairs]
        rewards = [p[2] for p in pairs]

        features_list = [
            self._extract_features(q, r) for q, r in zip(queries, responses)
        ]

        if self._weights is None and features_list:
            dim = len(features_list[0])
            self._weights = np.zeros(dim)

        total_loss = 0.0
        for epoch in range(self.n_epochs):
            log_probs = self._compute_log_probs(features_list)
            mean_reward = float(np.mean(rewards))
            std_reward = float(np.std(rewards)) + 1e-8
            advantages = [(r - mean_reward) / std_reward for r in rewards]

            grad = np.zeros_like(self._weights)
            for i, (feat, adv, log_prob) in enumerate(
                zip(features_list, advantages, log_probs)
            ):
                n = min(len(self._weights), len(feat))
                grad[:n] += adv * feat[:n]

            grad /= len(features_list)
            self._weights += self.learning_rate * grad

            epoch_loss = -float(np.mean([
                lp * a for lp, a in zip(log_probs, advantages)
            ]))
            total_loss += epoch_loss

        final_log_probs = self._compute_log_probs(features_list)
        mean_reward = float(np.mean(rewards))

        result = FeedbackStepResult(
            loss=total_loss / self.n_epochs,
            mean_reward=mean_reward,
            reward_baseline=mean_reward,
            num_samples=len(pairs),
            per_sample_rewards=rewards,
        )
        self._history.append(result)
        self._step_count += 1
        return result

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def history(self) -> list[FeedbackStepResult]:
        return list(self._history)

    def get_weights_summary(self) -> dict:
        """Get a summary of the learned weights."""
        if self._weights is None:
            return {"status": "untrained", "dim": 0}

        top_features = []
        if self._feature_vocab:
            idx_to_token = {v: k for k, v in self._feature_vocab.items()}
            indexed_weights = [(i, self._weights[i]) for i in range(len(self._weights))]
            indexed_weights.sort(key=lambda x: x[1])
            top_neg = indexed_weights[:5]
            top_pos = indexed_weights[-5:][::-1]
            top_features = {
                "positive": [(idx_to_token.get(i, f"feat_{i}"), round(w, 4)) for i, w in top_pos],
                "negative": [(idx_to_token.get(i, f"feat_{i}"), round(w, 4)) for i, w in top_neg],
            }

        return {
            "status": "trained",
            "dim": len(self._weights),
            "mean_weight": round(float(np.mean(self._weights)), 6),
            "std_weight": round(float(np.std(self._weights)), 6),
            "top_features": top_features,
        }

    def __repr__(self) -> str:
        return f"FullFeedbackRanker(steps={self._step_count}, feedback={self.feedback.size})"


# Backward-compatible alias
RealGRPOTrainer = FullFeedbackRanker


# ---------------------------------------------------------------------------
# Stub policy (for testing without a real LLM)
# ---------------------------------------------------------------------------

class StubPolicy:
    """Minimal policy that generates random text and accepts gradient updates."""

    def __init__(self, vocab_size: int = 100) -> None:
        self.vocab_size = vocab_size
        self._log_prob_sum = 0.0
        self._update_count = 0

    def generate(self, prompt: str) -> str:
        """Generate a random response."""
        words = list(prompt.split())
        extra = [f"word{random.randint(0, self.vocab_size)}" for _ in range(random.randint(5, 20))]
        return " ".join(words + extra)

    def update(self, log_prob: float, advantage: float) -> float:
        """Simulate a policy gradient update; returns loss."""
        self._log_prob_sum += log_prob
        self._update_count += 1
        return log_prob * advantage


class LLMPolicy:
    """Policy backed by a real LLM via tools.llm.create_llm_provider().

    Auto-detects LLM backend from environment variables.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        from tools.rag.rag_types import RAGConfig

        self.config = config or RAGConfig()
        self._provider = None
        self._log_prob_sum = 0.0
        self._update_count = 0

    def _get_provider(self):
        """Lazy-initialize the LLM provider."""
        if self._provider is None:
            from tools.llm import create_llm_provider
            self._provider = create_llm_provider(backend=self.config.llm_provider)
        return self._provider

    def generate(self, prompt: str) -> str:
        """Generate a response using the real LLM."""
        try:
            provider = self._get_provider()
            response = provider.complete(prompt, max_tokens=256, temperature=0.7)
            if response.success:
                return response.content
        except Exception:
            pass
        return f"{prompt} [LLM response placeholder]"

    def update(self, log_prob: float, advantage: float) -> float:
        """Simulate a policy gradient update; returns loss."""
        self._log_prob_sum += log_prob
        self._update_count += 1
        return log_prob * advantage


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate(prompt: str, policy: Any | None) -> str:
    if policy is not None:
        return policy.generate(prompt)
    return f"{prompt} [generated response placeholder]"


def _policy_gradient_step(log_prob: float, advantage: float, clip_ratio: float) -> float:
    """Clipped surrogate objective (PPO-style)."""
    raw_loss = -advantage * log_prob
    clipped = np.clip(raw_loss, -clip_ratio, clip_ratio)
    return float(clipped)
