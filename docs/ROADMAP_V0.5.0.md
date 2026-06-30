# V0.5.0 路线图

基于参考项目对比分析，结合本系统 Schema-First 定位，规划 V0.5.0 核心目标。

---

## 总体定位演进

```
V0.4.0: Schema-First 代码生成流水线 + 企业级 HITL + 多渠道消息
V0.5.0: 对话式 Agent Harness（让流水线能被"对话"驱动）+ 插件生态 + 持久化
```

**核心转变**：从"批处理编译器"走向"可对话的 Agent 系统"，同时保留 Schema-First 的独特优势。

---

## Phase 1: 对话式入口（P0，最高优先级）

### 目标
让用户可以用自然语言驱动流水线，而非直接编辑 Schema。

### 功能

#### 1.1 Supervisor Agent（意图路由 + 流水线触发）

参考：codex 的 `supervisor_node` + customer-service-course 的 `ROUTES` 字典

```
用户："帮我构建一个用户登录模块"
  → Supervisor 识别意图：code_generation
  → 路由到 PipelineCompiler + ExpertAgent
  → 返回：编译结果 + 代码 + 质量报告

用户："上次生成的代码有 bug，登录失败"
  → Supervisor 意图：code_fix
  → 加载上次 checkpoint → 触发 fix loop

用户："退款政策是什么？"
  → Supervisor 意图：knowledge_query
  → 路由到 RAG 引擎 → 返回政策文档
```

**新增文件**：
```
agents/supervisor/
  router.py (NEW ~150行)     — 意图分类 + 路由表
  intents.py (NEW ~80行)     — Intent 枚举 + 槽位定义
```

#### 1.2 AgentState（对话状态管理）

参考：codex 的 `AgentState` TypedDict

```python
class AgentState(TypedDict, total=False):
    # 对话上下文
    conversation_id: str
    message: str
    history: list[dict]          # 多轮对话历史

    # 意图路由
    intent: str
    intent_confidence: float
    slots: dict[str, Any]        # 槽位填充（module_name, language, ...）

    # 流水线执行
    pipeline_run_id: str | None
    compiled_pipeline: dict | None
    workflow_result: dict | None

    # RAG
    retrieved_docs: list[dict]
    rag_evidence: list[dict]

    # 审批
    pending_approval: dict | None
    approval_result: dict | None

    # 输出
    reply: str
    cards: list[dict]            # 结构化卡片（代码/质量报告/审批状态）
    trace: list[dict]           # 完整 trace

    # 控制
    stop_reason: str             # answered / need_more_info / waiting_human / error
    step_count: int
```

#### 1.3 ReAct Loop（Agent 主循环）

参考：customer-service-course 的 `AgentLoop` + refund-agent 的 v10 Loop

```
while step_count < max_steps:
    1. 构建 prompt（system + history + available_tools + context）
    2. LLM 调用 → 输出 thought + action
    3. 执行 action（tool_call / pipeline_run / rag_search / request_approval）
    4. 观察结果 → 写入 state
    5. 判断 stop_reason
```

**新增文件**：
```
agents/runtime/
  loop.py (NEW ~200行)        — ReAct 主循环
  state.py (NEW ~100行)       — AgentState + 状态转换
  tools.py (NEW ~150行)       — 工具注册（compile_pipeline / run_quality_check / search_kb / request_refund_approval）
```

---

## Phase 2: 插件生态（P0）

### 目标
让第三方可以注册自定义 Expert、Tool、Skill，无需修改核心代码。

### 功能

#### 2.1 Skill Registry（从 codex 借鉴）

参考：codex 的 `SkillRegistry` + `skill.json` manifest

```
plugins/
  skills/
    code_generator/
      skill.json          # name, intents, tools, entry_agent, risk_level
      prompts/system.md
      workflows/fix_loop.yaml
    code_reviewer/
      skill.json
      prompts/system.md
  tools/
    ast_validator/
      tool.json           # name, risk_level, requires_approval, input_schema
      handler.py
    test_runner/
      tool.json
      handler.py
```

**新增文件**：
```
tools/plugins/
  skill_registry.py (NEW ~150行)   — SkillRegistry 加载器
  tool_registry.py (NEW ~150行)    — ToolRegistry 加载器
  manifest.py (NEW ~80行)          — SkillManifest / ToolManifest 数据类
```

#### 2.2 声明式 Workflow（从 codex 借鉴）

参考：codex 的 `refund_flow.yaml` + `SkillWorkflowRuntime`

```yaml
# plugins/skills/code_generator/workflows/fix_loop.yaml
name: code_fix_workflow
nodes:
  - identify_issue
  - locate_module
  - generate_fix
  - run_tests
  - request_review
```

**新增文件**：
```
tools/plugins/
  workflow_runner.py (NEW ~120行)  — 声明式工作流执行器
```

---

## Phase 3: RAG 增强（P1）

### 目标
让 RAG 检索更精准，支持业务语义。

### 功能

#### 3.1 Query Profile（从 codex 借鉴）

参考：codex 的 `QueryProfile` + `ALIASES` 同义词扩展

```python
@dataclass(frozen=True)
class QueryProfile:
    raw_query: str
    domain: str                    # code_gen / quality_check / documentation
    normalized_query: str
    terms: set[str]
    tags: set[str]                 # 同义词扩展后的标签
    entities: dict[str, Any]       # 提取的实体（模块名、语言、框架）
```

**修改文件**：
```
tools/rag/cognitive.py — 加入 QueryProfile 预处理
```

#### 3.2 证据引用格式化

检索结果附带来源标注：`[BM-01]`、`[VC-02]`、`[GR-03]`

---

## Phase 4: Guardrails 统一（P1）

### 目标
整合 InputGuard + OutputGuard 为统一运行时。

### 功能

#### 4.1 GuardrailRuntime（从 codex 借鉴）

参考：codex 的 `GuardrailRuntime.check_input/check_tool/check_output`

```python
class GuardrailRuntime:
    def check_input(self, message: str, context: dict) -> GuardrailDecision: ...
    def check_tool(self, tool_name: str, args: dict, allowed_tools: list) -> GuardrailDecision: ...
    def check_output(self, output: str, context: dict) -> GuardrailDecision: ...
```

**新增文件**：
```
tools/guardrails/runtime.py (NEW ~150行) — 统一 GuardrailRuntime
```

#### 4.2 代码安全专项检查

在 OutputGuard 中增加：
- 危险代码检测（`os.system`、`eval`、`exec`）
- 密钥泄漏检测（API Key、password 硬编码）
- 注入检测（SQL 注入、命令注入模式）

---

## Phase 5: 持久化存储（P2）

### 目标
支持 PostgreSQL 持久化，替代纯内存存储。

### 功能

#### 5.1 PostgreSQL Store（从 codex 借鉴）

参考：codex 的 `PostgresStore` + `apply_schema()`

```sql
-- 核心表
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    created_at TIMESTAMPTZ,
    state JSONB
);

CREATE TABLE pipeline_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT,
    status TEXT,
    outputs JSONB,
    logs JSONB,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE approval_records (
    approval_id TEXT PRIMARY KEY,
    request JSONB,
    status TEXT,
    audit_chain JSONB
);

-- pgvector 扩展（可选）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    content TEXT,
    embedding vector(768),
    metadata JSONB
);
```

**新增文件**：
```
tools/storage/
  postgres_store.py (NEW ~300行) — PostgreSQL 持久化
  schema.sql (NEW ~80行)         — 数据库 schema
  vector_store.py (NEW ~150行)  — pgvector 适配
```

---

## Phase 6: 前端与部署（P2）

### 功能

#### 6.1 Next.js 聊天界面（从 codex 借鉴）

参考：codex 的 `apps/web/` Next.js 项目

- 流式 SSE 聊天窗口
- 代码高亮展示（Prism.js）
- 结构化卡片（代码质量报告、审批状态、检索结果）
- Pipeline 可视化（D3.js / React Flow）

#### 6.2 Docker Compose 完整部署

```yaml
# docker-compose.yml
services:
  api:
    build: ./infra/docker/api.Dockerfile
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://redis:6379
      - STORAGE_BACKEND=postgres

  web:
    build: ./infra/docker/web.Dockerfile
    ports: ["3000:3000"]

  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

---

## 实现顺序

```
P0-1: AgentState + ReAct Loop + Supervisor Router（对话入口）
P0-2: Skill Registry + Tool Registry（插件生态）
P0-3: 声明式 Workflow Runner
P1-0: Query Profile + RAG 增强
P1-1: GuardrailRuntime 统一
P1-2: 代码安全专项 OutputGuard
P2-0: PostgreSQL Store + pgvector
P2-1: Next.js 前端
P2-2: Docker Compose 完整部署
```

## 成功标准

| 指标 | 目标 |
|------|------|
| 对话驱动流水线 | 用户用自然语言触发编译、修复、检索 |
| 插件注册 | 第三方 Skill/Tool 通过 manifest 注册，零代码修改 |
| RAG 精度 | Query Profile 同义词扩展后召回率提升 20% |
| 安全覆盖 | GuardrailRuntime 三层防护，注入检测覆盖率 >90% |
| 持久化 | PostgreSQL 存储对话历史、Pipeline 运行记录、审批审计 |
| 部署 | Docker Compose 一键启动，Mock 模式无 API Key 可运行 |
| 测试覆盖 | 1600+ tests passed, 0 failed |
