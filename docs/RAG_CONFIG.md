# RAG 双引擎配置指南

CC 的 RAG 系统有两个引擎模式，通过 `RAGConfig` 配置。

## 快速配置

```python
from tools.rag import RAGConfig, RAGPipeline

# 最小配置（使用默认值）
config = RAGConfig()
pipeline = RAGPipeline(config)

# 自定义配置
config = RAGConfig(
    # 检索
    bm25_top_k=10,
    vector_top_k=10,
    graph_top_k=5,

    # 重排序
    rerank_top_k=5,
    cross_encoder_weight=0.4,
    llm_scorer_weight=0.3,

    # GRPO 训练
    grpo_learning_rate=1e-5,
    grpo_epochs=3,
)
pipeline = RAGPipeline(config)
```

## 引擎模式

### Search Engine（搜索引擎模式）

三路召回 → RRF 融合 → Rerank 排序：

```
Query
  ├─ BM25 Retriever (关键词)
  ├─ Vector Retriever (语义)
  └─ Graph Retriever (知识图谱)
         ↓
      RRF Fusion（倒数排名融合）
         ↓
      Rerank（CrossEncoder + LLM + Vector 加权）
         ↓
      Top-K Results
```

**何时使用**：纯信息检索、文档搜索、不需要上下文记忆的场景。

```python
result = pipeline.query("什么是机器学习？", top_k=5)
# result.reranked_documents  — 最终排序结果
# result.retrieved_documents — 召回阶段所有文档
```

### Cognitive Engine（认知引擎模式）

意图识别 → 记忆检索 → 技能注入 → GRPO 优化生成：

```
Query
  ↓
Intent Classifier（factual / analytical / creative / code_generation）
  ↓
User Model → 确定专业级别（beginner / intermediate / expert）
  ↓
IntentRouter → 选择检索策略（12 种策略）
  ↓
Memory Manager → 检索相关历史上下文
  ↓
Skill Manager → 注入相关技能指令
  ↓
Context Builder → 组装完整上下文
  ↓
GRPO-Trained Answer Generator
  ↓
Answer + Context
```

**何时使用**：代码生成、需要领域知识、需要持续改进的场景。

```python
from tools.rag import SkillLearner, MemoryManager, UserModel

skills = SkillLearner(".skills")
memory = MemoryManager(".rag_memory.json")
user = UserModel(expertise_level="intermediate")

result = pipeline.query_with_cognitive(
    query="实现订单认证模块",
    skill_manager=skills,
    memory_manager=memory,
    user_model=user,
)
```

## 配置参数详解

### 检索配置

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `bm25_top_k` | 10 | BM25 召回数量 |
| `vector_top_k` | 10 | 向量检索召回数量 |
| `graph_top_k` | 5 | 图谱检索召回数量 |
| `fusion_top_k` | 15 | RRF 融合后保留数量 |
| `rerank_top_k` | 10 | 最终返回数量 |

### Reranker 配置

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `cross_encoder_model` | ms-marco-MiniLM-L-6-v2 | 交叉编码器模型 |
| `cross_encoder_weight` | 0.4 | 交叉编码器分数权重 |
| `llm_scorer_weight` | 0.3 | LLM 评分器权重 |
| `vector_score_weight` | 0.3 | 向量相似度权重 |
| `enable_llm_scorer` | False | 是否启用 LLM 评分（慢但更准） |

**权重归一化**：三个权重自动归一化为总和 1.0。

### GRPO 训练配置

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `grpo_learning_rate` | 1e-5 | 学习率 |
| `grpo_epochs` | 3 | 训练轮数 |
| `grpo_batch_size` | 8 | 批次大小 |
| `grpo_clip_ratio` | 0.2 | PPO 裁剪比 |
| `grpo_temperature` | 0.7 | 采样温度 |
| `reward_relevance_weight` | 0.5 | 相关性奖励权重 |
| `reward_fluency_weight` | 0.3 | 流畅度奖励权重 |
| `reward_diversity_weight` | 0.2 | 多样性奖励权重 |

### Pipeline 开关

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `enable_bm25` | True | 启用 BM25 检索 |
| `enable_vector` | True | 启用向量检索 |
| `enable_graph` | True | 启用图谱检索 |
| `enable_reranker` | True | 启用重排序 |

**性能 vs 质量权衡**：
- 追求速度：`enable_graph=False, enable_llm_scorer=False`
- 追求质量：`enable_llm_scorer=True, rerank_top_k=5`

### 图谱配置

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `graph_similarity_threshold` | 0.3 | 节点连接相似度阈值 |
| `graph_max_depth` | 3 | 图谱遍历最大深度 |

## 环境变量

RAG 系统还受以下环境影响：

```bash
# LLM 提供商（影响 Cognitive Engine 的生成质量）
export ANTHROPIC_API_KEY="sk-..."
export OPENAI_API_KEY="sk-..."

# 向量存储后端（可选，默认内存）
export MILVUS_HOST="localhost"
export MILVUS_PORT="19530"
```

## 反馈收集（用于 GRPO 训练）

```python
from tools.rag import FeedbackStore

store = FeedbackStore(".feedback.json")

# 收集评分
store.add_rating(query="...", answer="...", rating=4.5, user="user1")

# 收集纠正（比评分更有价值）
store.add_correction(query="...", wrong_answer="...", correct_answer="...", user="user1")

# 训练
from tools.rag import RealGRPOTrainer

trainer = RealGRPOTrainer(config, feedback=store)
result = trainer.train()
print(f"Mean reward: {result.mean_reward:.4f}")
```
