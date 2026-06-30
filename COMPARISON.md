# 参考项目对比分析

本文档对比分析三个参考项目（codex、refund-agent、customer-service-course）与本系统的架构差异，提取可借鉴的模式。

---

## 1. 项目概览

| 维度 | **codex** (wsk-agent.xyz) | **refund-agent** (v01-v30) | **customer-service-course** | **本系统** (CC Pipeline) |
|------|--------------------------|---------------------------|-----------------------------|--------------------------|
| **定位** | 企业级电商客服 Agent 教学实战 | 渐进式 Agent 工程教程（30 个版本） | 电商客服 Agent 课程项目 | Schema-First 多智能体代码生成流水线 |
| **核心场景** | 退款/物流/政策问答 | 退款 Agent 贯穿教学 | 客服全场景（订单/退款/物流/退换货/商品/优惠/政策/投诉） | 代码生成、模块编译、RAG 检索 |
| **前端** | Next.js + Tailwind | 无（CLI） | 无（CLI） | Streamlit GUI |
| **后端** | FastAPI | 无（直接调用） | 无（Python Harness） | FastAPI |
| **Agent 框架** | LangGraph StateGraph | v29 LangGraph / v30 Final | 自研 ReAct Loop | 自研 WorkflowEngine + LangGraph 适配器 |
| **存储** | PostgreSQL + pgvector + Redis + MinIO | 内存 Mock | 内存 Mock | 内存 + 可选 Milvus/Chroma |
| **部署** | Docker Compose + Nginx | 本地脚本 | 本地脚本 | Docker Compose |

---

## 2. 架构模式对比

### 2.1 Agent 编排模式

| 项目 | 编排模式 | 核心抽象 | 意图路由 |
|------|---------|---------|---------|
| **codex** | LangGraph StateGraph + Supervisor | `AgentState` (TypedDict) + `supervisor_node` | `model_provider.classify_intent()` → `skill_registry.get_by_intent()` |
| **refund-agent** | 渐进式：ReAct → Workflow → LangGraph | 从简单 dict → `AgentState` → LangGraph State | 规则匹配 → LLM 分类 |
| **customer-service-course** | Agent Harness + ReAct Loop | `SessionState` + `AgentLoop` | `classify_intent_by_rules()` → `ROUTES` 字典 |
| **本系统** | Schema-First Compiler → WorkflowEngine | `CompiledPipeline` + `Workflow` + `WorkflowNode` | PipelineCompiler 从 Schema 推导拓扑序 |

**关键差异**：
- codex 和 customer-service-course 都使用**意图路由表**（intent → skill/tools），但 codex 用 LangGraph 的 conditional edges，customer-service-course 用 Python 字典
- 本系统**没有意图路由**——执行顺序完全由 Schema 依赖图推导，适合代码生成而非对话场景
- codex 的 `supervisor_node` 是真正的 LLM 调用，本系统用编译器替代了 LLM 路由

### 2.2 Tool/Skill 架构

| 项目 | Tool 注册 | Skill 定义 | 权限控制 | 审批流 |
|------|----------|-----------|---------|--------|
| **codex** | `ToolRegistry` 从 `plugins/tools/*/tool.json` 动态加载 | `SkillRegistry` 从 `plugins/skills/*/skill.json` 加载 | `ToolDefinition.requires_auth` + `requires_approval` | `guardrail_runtime` 检查 + 高风险人工审批 |
| **refund-agent** | v06+ `ToolRegistry` 类注册 | 无（单个 Agent） | v08+ `ToolRuntime` 权限检查 | v14+ HITL 审批 |
| **customer-service-course** | `ToolRegistry` + `ToolRuntime` | 无（ROUTES 字典替代） | `allowed_tools` 最小权限 | `approval_handler` 可插拔 |
| **本系统** | `ToolNode` 在 WorkflowEngine 中执行 | `agents/experts/` 目录自动发现 | `node.permissions` 列表 | `ApprovalHandler` 三级（auto/manual/enterprise） |

**codex 的插件系统最成熟**：
- Tool 是独立目录，含 `tool.json` manifest + `handler.py` 实现
- Skill 是独立目录，含 `skill.json` manifest + `prompts/` + `workflows/`
- 运行时动态加载，`importlib.util.spec_from_file_location` 实现热插拔
- 每个 Tool 声明 `risk_level`、`requires_auth`、`requires_approval`、`idempotent`

### 2.3 RAG 架构

| 项目 | 向量存储 | 切片策略 | 检索模式 | 证据引用 |
|------|---------|---------|---------|---------|
| **codex** | pgvector / 内存 fallback | `policy_chunker` 按 Markdown 标题切片 | Query Profile → 混合召回 → Rerank → 阈值过滤 | 结构化引用 `[KB-01]` |
| **refund-agent** | v15+ 内存向量 | 简单字符切片 | BM25 + 向量混合 | 无 |
| **customer-service-course** | 内存 TF-IDF | 段落切片 | 关键词匹配 | 无 |
| **本系统** | Milvus/Chroma/Memory | BM25 + Vector + Graph → RRF → Rerank | 双引擎（Search + Cognitive） | 来源标注 |

**codex 的 RAG 亮点**：
- `QueryProfile` 结构化处理：domain 分类 + 同义词扩展（ALIASES 字典）+ 实体识别
- 混合检索：pgvector 优先，不可用时 fallback 到内存搜索
- 证据阈值动态调整：`threshold = 1.2 if profile.tags else 0.8`
- 输出格式化时标注 `retrieval_method` 和 `citation`

### 2.4 Guardrails 安全体系

| 项目 | 输入安全 | 工具安全 | 输出安全 | 审计 |
|------|---------|---------|---------|------|
| **codex** | 注入检测 + PII 脱敏 + 越权订单检测 | `GuardrailRuntime.check_tool()` 四层检查 | 泄漏检测 + 越权承诺检查 | `audit_logs` 表 |
| **refund-agent** | v23+ `InputGuard` | v08+ 权限 + 幂等 | v23+ `OutputGuard` | v24+ Tracing |
| **customer-service-course** | `InputGuard` 注入 + PII | `ToolRuntime` 六道关 | `OutputGuard` 泄漏 + 越权 | `audit_log` 列表 |
| **本系统** | `InputGuard` 注入 + PIT | `ApprovalHandler` 风险门禁 | `OutputGuard` 代码安全 + PII | `AuditLog` + `HashChainedAuditLog` |

**codex 的 Guardrails 最精细**：
- 三层防护：`check_input()` → `check_tool()` → `check_output()`
- 注入检测用正则表达式黑名单（中英文混合）
- 自动检测"他者订单"（`foreign_order_id`）：用户 A 查询用户 B 的订单时阻断
- `safe_reply` 机制：阻断时返回预设安全回复而非错误信息

### 2.5 状态与 Checkpoint

| 项目 | 状态定义 | Checkpoint | 恢复机制 |
|------|---------|-----------|---------|
| **codex** | `AgentState` (TypedDict, 20+ 字段) | `runtime_checkpointer.save()` | LangGraph 原生 interrupt/resume |
| **refund-agent** | v18+ `SessionState` | v22+ Harness 状态保存 | 内存 |
| **customer-service-course** | `SessionState` | 无 | 无 |
| **本系统** | `WorkflowResult` + `ExecutionLog` | `save_checkpoint()` / `load_checkpoint()` | 文件系统 JSON |

**codex 的 AgentState 设计值得借鉴**：
```python
class AgentState(TypedDict, total=False):
    user: dict[str, Any]           # 当前用户
    conversation: dict[str, Any]   # 会话上下文
    conversation_id: str
    agent_run_id: str
    message: str                   # 当前用户消息
    intent: str                    # 意图分类结果
    intent_confidence: float
    slots: dict[str, Any]          # 槽位填充
    skill_name: str | None         # 当前激活的 skill
    current_order_id: str | None
    pending_action: str | None     # 待确认动作
    retrieved_evidence: list[dict] # RAG 检索结果
    tool_results: dict[str, Any]   # 工具调用结果
    risk_level: str | None
    human_task_id: str | None
    reply: str                     # 最终回复
    cards: list[dict[str, Any]]    # 结构化卡片
    trace: list[dict[str, Any]]    # 完整 trace
    stop_reason: str
    step_count: int
```

---

## 3. 可借鉴的架构模式

### 3.1 优先级 A：高价值、可快速集成

#### 3.1.1 Skill Registry + Tool Registry 插件系统

**来源**：codex 的 `SkillRegistry` + `ToolRegistry`

**当前差距**：本系统的 expert agents 通过 `agents.yaml` 静态声明，不支持运行时动态加载。

**借鉴方案**：
```
plugins/
  skills/
    refund_service/
      skill.json          # manifest: name, intents, tools, entry_agent, risk_level
      prompts/system.md   # 系统提示词
      workflows/refund_flow.yaml  # 声明式工作流
  tools/
    refund/
      tool.json           # manifest: name, namespace, risk_level, requires_approval
      handler.py          # 实现
```

#### 3.1.2 声明式 Workflow (SkillWorkflowRuntime)

**来源**：codex 的 `SkillWorkflowRuntime` + `refund_flow.yaml`

**当前差距**：本系统的修复策略是 Python 代码中的 `FixDeriver`，不是声明式。

**借鉴方案**：
```yaml
# refund_flow.yaml
name: refund_workflow
nodes:
  - collect_info
  - query_order
  - retrieve_policy
  - check_eligibility
  - risk_review
  - user_confirm
  - create_refund_or_handoff
```

#### 3.1.3 Query Profile 结构化 RAG

**来源**：codex 的 `QueryProfile` + `ALIASES` 同义词扩展

**当前差距**：本系统的 RAG Cognitive Engine 有意图分类，但没有同义词扩展和 domain 过滤。

**借鉴方案**：
- 在 `CognitiveEngine` 中加入 `QueryProfile` 数据类
- 增加同义词扩展字典（中英文混合）
- 增加 domain 过滤（refund / logistics / product / policy）

### 3.2 优先级 B：中等价值、需要设计

#### 3.2.1 Guardruntime 三层防护

**来源**：codex 的 `GuardrailRuntime`

**当前差距**：本系统的 `InputGuard` + `OutputGuard` 是独立的，没有统一运行时。

**借鉴方案**：创建 `GuardrailRuntime` 统一入口，整合 `check_input()` → `check_tool()` → `check_output()`。

#### 3.2.2 结构化输出卡片 (Cards)

**来源**：codex 的 `AgentState.cards` + 前端渲染

**当前差距**：本系统的输出是纯文本或 JSON，没有结构化卡片概念。

**借鉴方案**：在 `WorkflowResult.outputs` 中增加 `cards` 字段，支持 `OrderCard`、`RefundCard`、`LogisticsCard` 等。

#### 3.2.3 Eval 框架

**来源**：codex 的 `run_evals.py` + `test_refund_runtime.py`

**当前差距**：本系统的测试是纯 pytest，没有业务语义的 eval 用例。

**借鉴方案**：
```
evals/
  intent_eval.jsonl     # 意图分类 eval
  tool_eval.jsonl       # 工具调用 eval
  refund_flow_eval.jsonl # 退款流程端到端 eval
  runner.py             # 运行 + 报告生成
```

### 3.3 优先级 C：长期参考

#### 3.3.1 PostgreSQL + pgvector 持久化

**来源**：codex 的 `PostgresStore` + `apply_schema()`

**当前差距**：本系统纯内存存储。

#### 3.3.2 OpenTelemetry + Jaeger Tracing

**来源**：codex 的 tech stack 规划（尚未完全实现）

#### 3.3.3 渐进式教学法 (refund-agent v01-v30)

**来源**：refund-agent 的 30 个版本迭代

**价值**：本系统的文档可以参考这种"从最小可用版本开始，每章增加一个工程能力"的教学方式。

---

## 4. wsk-agent.xyz 部署方案分析

### 4.1 平台概述

`http://www.wsk-agent.xyz/dashboard` 是 codex 项目的在线部署实例，具有以下特征：
- **域名**：`wsk-agent.xyz`（WSK = Workshop）
- **路径**：`/dashboard`（管理/演示面板）
- **技术栈**：Next.js 前端 + FastAPI 后端 + PostgreSQL + Redis + Docker Compose

### 4.2 部署架构（从 codex 项目推断）

```
                    Nginx (80/443)
                   /              \
          Next.js (3000)    FastAPI (8000)
                              /    |    \
                         PostgreSQL Redis  MinIO
                         (pgvector)
```

### 4.3 可借鉴的部署模式

| 模式 | codex 实现 | 本系统适配 |
|------|-----------|-----------|
| **Docker Compose 一键启动** | `docker-compose.yml` + `infra/docker/` | 已有 Dockerfile，需补 `docker-compose.yml` |
| **PostgreSQL 持久化** | `apply_schema()` 自动建表 | 可选：代码生成结果的持久化 |
| **SSE 流式输出** | `GET /api/chat/stream/{conversation_id}` | 已有 `/api/v1/pipeline/stream` |
| **Mock 模式** | `config/app.config.json` → `model.provider = mock` | 已有 `MockLLMProvider` |
| **Eval 接口** | `scripts/run_evals.py` | 已有 `tools/eval/runner.py` |

### 4.4 本系统的在线演示方案建议

借鉴 codex 的部署模式，本系统可以：

1. **Dashboard 页面**（Next.js/Streamlit 增强）：
   - Pipeline 可视化（节点图 + 实时执行状态）
   - Schema 编辑器（在线编辑 JSON Schema，实时预览编译结果）
   - RAG 检索测试（输入查询，展示 BM25/Vector/Graph 三路召回 + Rerank 结果）
   - 审批面板（EnterpriseApprovalHandler 的可视化管理）

2. **部署方式**：
   - `docker-compose.yml`：FastAPI + Streamlit + PostgreSQL（可选）
   - `docker-compose.dev.yml`：纯 Mock 模式，无 API Key 即可运行
   - `docker-compose.prod.yml`：完整模式，含 Redis + MinIO

---

## 5. 总结：本系统的独特优势与差距

### 独特优势（参考项目没有的）
1. **Schema-First 编译**：从 JSON Schema 自动推导执行图，参考项目都是手写 DAG
2. **RAG 双引擎**：Search（BM25+Vector+Graph→RRF→Rerank）+ Cognitive（Intent→Memory→Skill→GRPO）
3. **多 Provider LLM 切换**：20+ 后端统一接口，支持运行时切换
4. **Hash-Chained 审计**：SHA-256 防篡改，参考项目只有普通日志
5. **LangGraph 适配器**：编译产物可执行于两个后端

### 主要差距（需要学习的）
1. **对话式交互**：参考项目都是对话式 Agent，本系统是批处理流水线
2. **Tool/Skill 插件系统**：codex 的运行时动态加载远超本系统的静态注册
3. **业务语义 RAG**：codex 的 QueryProfile + 同义词扩展 + domain 过滤更精细
4. **前端体验**：参考项目有 Next.js 聊天界面，本系统只有 Streamlit 仪表板
5. **持久化存储**：codex 有 PostgreSQL 全量持久化，本系统纯内存
6. **Eval 框架**：codex 有业务语义的 eval 用例，本系统只有单元测试

---

## 6. 参考项目文件索引

### codex.zip 关键文件
| 文件 | 功能 |
|------|------|
| `codex/apps/api/app/agent/state.py` | AgentState TypedDict 定义 |
| `codex/apps/api/app/agent/refund_graph.py` | LangGraph StateGraph 构建 |
| `codex/apps/api/app/agent/workflow.py` | SkillWorkflowRuntime 声明式工作流 |
| `codex/apps/api/app/agent/tooling.py` | ToolRegistry 动态加载 |
| `codex/apps/api/app/agent/skills.py` | SkillRegistry 意图索引 |
| `codex/apps/api/app/agent/model_provider.py` | 多 Provider 模型切换 |
| `codex/apps/api/app/rag/service.py` | PolicyRagService + QueryProfile |
| `codex/apps/api/app/core/postgres_store.py` | PostgreSQL 持久化 |
| `codex/apps/api/app/guardrails/runtime.py` | GuardrailRuntime 三层防护 |
| `codex/plugins/tools/refund/handler.py` | 退款工具实现示例 |
| `codex/plugins/skills/refund_service/` | Skill 插件目录结构 |
| `codex/scripts/run_evals.py` | Eval 运行器 |
| `codex/tests/unit/test_refund_runtime.py` | 退款流程测试 |

### refund-agent-v01-v30.zip 关键文件
| 文件 | 功能 |
|------|------|
| `refund_agent/v06_tools.py` | Tool Registry 初始实现 |
| `refund_agent/v07_tool_runtime.py` | Tool Runtime 安全沙箱 |
| `refund_agent/v08_tool_safety.py` | 权限 + 审批 + 幂等 |
| `refund_agent/v12_workflow.py` | 声明式工作流 |
| `refund_agent/v14_hitl.py` | HITL 人工审批 |
| `refund_agent/v16_agentic_rag.py` | Agentic RAG |
| `refund_agent/v20_supervisor.py` | Supervisor 多 Agent |
| `refund_agent/v22_harness.py` | Harness 装配 |
| `refund_agent/v23_guardrails.py` | Guardrails 完整实现 |
| `refund_agent/v26_security.py` | 安全审计 |
| `refund_agent/v27_mcp_server.py` | MCP Server |
| `refund_agent/v29_langgraph.py` | LangGraph 集成 |
| `refund_agent/v30_final.py` | 最终完整版 |

### customer-service-course.zip 关键文件
| 文件 | 功能 |
|------|------|
| `customer_service_agent/agent.py` | Agent Harness 主管道 |
| `customer_service_agent/tools/runtime.py` | ToolRuntime 六道关 |
| `customer_runtime/loop.py` | ReAct 循环 |
| `customer_service_agent/guardrails/` | 输入输出护栏 |
| `customer_service_agent/memory/` | 短期/长期记忆 |
| `customer_service_agent/eval/` | 离线评估 |
