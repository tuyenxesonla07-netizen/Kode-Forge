# 🧠 Claude-Codex Multi-Agent Pipeline (CC)

> **Write JSON Schema → Get Secure, Production-Ready Code from Multi-Agent Pipeline**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-1095%20passed-brightgreen.svg)](tests/)

**The workflow:**
1. 🏗️ You write JSON Schemas (module input/output contracts)
2. 🤖 Pipeline auto-compiles schemas into parallel multi-agent tasks
3. ✍️ Expert agents generate code with RAG context + skill injection
4. 🔒 Security review (injection detection + AST validation + PII masking)
5. 📊 Quality evaluation + fix loop until convergence

**No manual DAG wiring.** The compiler reads your schemas and derives context, order, prompts, fix rules, and quality gates automatically.

## ✨ Why This Exists

Most multi-agent frameworks make you wire agents by hand — `agent_a → agent_b → agent_c`. Change one agent and the DAG breaks.

CC is **schema-first**: define the *what* (module contracts), let the compiler figure out the *how* (execution order, context injection, retry strategy). Add a module by dropping two JSON files — zero Python code.

## 🔌 MCP Server

CC exposes a JSON-RPC 2.0 interface over SSE — any MCP-compatible client (Claude Desktop, Cursor, CLI tools) can invoke pipeline tools directly.

```bash
cc serve --port 8080        # REST API + WebSocket
cc mcp                     # MCP JSON-RPC over stdio/SSE
```

## 🚀 Quick Start

### Install

```bash
git clone <repo-url> && cd claude-codex-multi-agent
pip install -e ".[dev]"
```

### Zero-Config Demo (no API key needed)

```bash
python examples/demo_showcase.py
```

Runs a complete 6-step pipeline with mock LLM — see schema compilation, expert analysis, code generation, security review, quality evaluation, and observability in action.

### Real LLM

```bash
# Pick one:
export ANTHROPIC_API_KEY="sk-..."        # Claude (recommended)
export OPENAI_API_KEY="sk-..."            # OpenAI / DeepSeek / Tongyi / Kimi
export GEMINI_API_KEY="AIza..."           # Gemini

# Run full pipeline
cc run "Build a JWT auth module with FastAPI"
```

### Scaffold a New Project

```bash
cc init my-project --modules "auth,api,data"
# Generates: schemas, agents.yaml, pipeline.yaml, README
```

### Python API

```python
# Layer 1: One-liner
from agents.pipeline import generate_code
result = generate_code("Build a REST API with auth")

# Layer 2: Pipeline class
from agents.pipeline import Pipeline
pipeline = Pipeline(config_dir="config", llm_backend="mock")
result = pipeline.run("Build a REST API with auth")

# Layer 3: Full multi-agent system
from agents.pipeline import ClaudeCodexMultiAgent
agent = ClaudeCodexMultiAgent()
```

## 🎯 Use Cases

- **Custom AI coding pipelines** — Build multi-agent systems that match your architecture
- **RAG-powered code generation** — Feed your codebase + docs for context-aware code
- **Self-improving agents** — Skills automatically extracted from successful runs
- **Multi-model applications** — Swap between Claude/GPT/Gemini/DeepSeek without code changes
- **HITL workflows** — Auto-approve low-risk changes, escalate high-risk ones
- **Feedback-driven improvement** — GRPO preference optimization from human feedback (👍👎)
- **Skill marketplace** — Publish and share reusable skills as Markdown files

## 🏗️ Architecture

```
User Requirement
  → 🔒 InputGuard (injection detection + PII masking)
  → 🧠 Memory.load() (restore context)
  → ✋ HITL Approval (risk-based gate)
  → 📊 CodexSupervisor.parse_requirement() → identify modules
  → 🔧 PipelineCompiler.compile() → context/order/prompts/fixes/gates
  → 📦 ExpertAgent.process() × N (with Skills injection, parallel)
  → ✍️ Supervisor.generate_code() × N (LLM code gen + AST validation)
  → ✅ OutputGuard.check() (code safety + PII cleanup + strict mode)
  → 💾 Memory.save() + SessionState.checkpoint()
  → 📊 QualityEvaluator + ConvergenceDetector (fix loop up to 3×)
  → 🔍 Tracer (contextmanager spans) + AuditLog (PII masked) + PipelineMetrics
  → 📤 Code Artifact
```

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Quick Start](docs/QUICK_START.md) | 5 分钟上手，安装、配置、第一个 Pipeline |
| [Schema Guide](docs/SCHEMA_GUIDE.md) | 如何定义模块 Input/Output Schema |
| [Pipeline Config](docs/PIPELINE_CONFIG.md) | 质量门禁、超时、重试策略配置 |
| [RAG Config](docs/RAG_CONFIG.md) | 双引擎（Search + Cognitive）调参指南 |
| [Skill Authoring](docs/SKILL_AUTHORING.md) | 编写自定义 Skill |
| [Deployment](docs/DEPLOYMENT.md) | Docker / 生产环境部署 |

## 🎯 Use Cases

- **Custom AI coding pipelines** — Build multi-agent systems that match your architecture
- **RAG-powered code generation** — Feed your codebase + docs for context-aware code
- **Self-improving agents** — Skills automatically extracted from successful runs
- **Multi-model applications** — Swap between Claude/GPT/Gemini/DeepSeek without code changes
- **HITL workflows** — Auto-approve low-risk changes, escalate high-risk ones
- **Feedback-driven improvement** — GRPO preference optimization from human feedback (👍👎)
- **Skill marketplace** — Publish and share reusable Markdown files

## 🏗️ Architecture

```
User Requirement
  → 🔒 InputGuard (injection detection + PII masking)
  → 🧠 Memory.load() (restore context)
  → ✋ HITL Approval (risk-based gate)
  → 📊 CodexSupervisor.parse_requirement() → identify modules
  → 🔧 PipelineCompiler.compile() → context/order/prompts/fixes/gates
  → 📦 ExpertAgent.process() × N (with Skills injection, parallel)
  → ✍️ Supervisor.generate_code() × N (LLM code gen + AST validation)
  → ✅ OutputGuard.check() (code safety + PII cleanup + strict mode)
  → 💾 Memory.save() + SessionState.checkpoint()
  → 📊 QualityEvaluator + ConvergenceDetector (fix loop up to 3×)
  → 🔍 Tracer (contextmanager spans) + AuditLog (PII masked) + PipelineMetrics
  → 📤 Code Artifact

Feedback (👍👎) can be collected for GRPO preference optimization.
```
```

## 🔧 Adding a New Module

**Zero code changes** — just two config files:

1. Create `config/schemas/xxx_input.json` + `xxx_output.json`
2. Add `expert_xxx` section to `config/agents.yaml` with capabilities
3. Auto-discovered at runtime

## 📚 Adding a New Skill

Skills are Markdown-based — no code required:

```markdown
# tools/skills/builtin/my-skill/SKILL.md
---
name: my-skill
description: What this skill does
triggers: [keyword1, keyword2]
version: 1.0.0
author: your-name
---

# Skill Instructions

Detailed instructions for the agent...
```

Or publish via CLI:
```bash
cc skills publish path/to/my-skill
```

## 📊 Competitor Comparison

| Feature | **CC** | Claude Code | Cursor | Hermes | Dify | Coze | Gemini CLI |
|---------|--------|-------------|--------|--------|------|------|-------------|
| Schema-first Multi-Agent | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| RAG Dual-Engine | ✅ | ❌ | ❌ | Partial | Search | Search | ❌ |
| Skill Self-Learning | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| User Modeling + Intent | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| GRPO Feedback-Driven | ✅ | ❌ | ❌ | Partial | ❌ | ❌ | ❌ |
| HITL Risk Approval | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Milvus/Chroma Vector DB | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| LLM Query Rewrite | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| REST API + WebSocket | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| CLI + GUI | ✅ | ✅ CLI | ✅ IDE | ❌ | ❌ | ✅ | ✅ CLI |
| Feedback-Driven GUI | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Skill Marketplace | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 20+ LLM Providers | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |

## 📁 Project Structure

```
├── agents/                  # Supervisor + Expert agents
│   ├── supervisor/           # CodexSupervisor (requirement parsing, task decomposition)
│   └── experts/              # ExpertAgent (auto-discovered, config-driven)
├── tools/
│   ├── rag/                 # RAG dual-engine
│   │   ├── pipeline.py       # Search: BM25+Vector+Graph→RRF→Rerank
│   │   ├── intent.py         # Cognitive: Intent→Memory→Skill→GRPO
│   │   ├── feedback.py       # Human feedback collection (👍👎)
│   │   ├── grpo.py           # GRPO trainer (stub + real gradient)
│   │   ├── memory_manager.py # Cross-session memory
│   │   ├── skill_manager.py  # Skill matching + injection
│   │   ├── user_model.py     # Expertise detection + intent routing
│   │   ├── vector_store.py   # Milvus/Chroma/InMemory
│   │   ├── retriever.py      # BM25 + Vector + Graph retrievers
│   │   ├── reranker.py       # Cross-encoder + LLM scorer + combined
│   │   ├── query_rewriter.py # Multi-strategy query rewriting
│   │   └── observability.py  # Metrics + structured logging
│   ├── compiler/            # Pipeline compiler (Schema→executable)
│   │   ├── context_deriver.py # Context strategy generation
│   │   ├── fix_deriver.py    # Fix rule generation
│   │   ├── dependency_graph.py # Module dependency DAG
│   │   └── prompt_generator.py # Prompt template generation
│   ├── quality/             # Quality evaluation + convergence detection
│   ├── guardrails/          # Input/output security (injection, PII, leaks)
│   ├── memory/              # Short-term + long-term + session state
│   ├── hitl/                # HITL risk-based approval + audit log
│   ├── workflow/            # DAG execution engine (topological sort)
│   ├── llm/                 # LLM provider abstraction (20+ providers)
│   ├── skills/              # Markdown skill system (load, manage, publish)
│   │   ├── loader.py         # SKILL.md parser (YAML frontmatter)
│   │   ├── manager.py        # Skill selection + prompt injection
│   │   └── registry.py       # Skill marketplace (publish/search/unpublish)
│   ├── observability/       # Per-request Tracer + PipelineMetrics
│   ├── eval/                # 25 behavioral evaluation cases
│   ├── cc_switch.py         # Multi-provider model switcher + connectivity test
│   └── cc_cli.py            # Unified CLI entry point
├── gui/                     # Streamlit GUI
│   └── app.py               # Query/Pipeline/Skills/Feedback/Status pages
├── config/
│   ├── schemas/             # 7 JSON module schemas (auth, cart, order, etc.)
│   ├── agents.yaml          # Agent capability registry
│   └── pipeline.yaml        # Pipeline phases, quality gates, retry policies
├── tests/                   # 621 tests across 24 files
├── examples/                # Demo scripts
└── pyproject.toml           # Package config + dependencies
```

## 🎯 Use Cases

- **Custom AI coding pipelines** — Build multi-agent systems that match your architecture
- **RAG-powered code generation** — Feed your codebase + docs for context-aware code
- **Self-improving agents** — Skills automatically extracted from successful runs
- **Multi-model applications** — Swap between Claude/GPT/Gemini/DeepSeek without code changes
- **HITL workflows** — Auto-approve low-risk changes, escalate high-risk ones
- **Feedback-driven improvement** — GRPO preference optimization from human feedback (👍👎)
- **Skill marketplace** — Publish and share reusable skills as Markdown files

## 🧪 Testing

```bash
python -m pytest tests/ -v
# 1021 passed, 9 skipped, 0 failed
```

| Test File | Coverage Area | Tests |
|-----------|--------------|-------|
| `tests/test_rag.py` | RAG pipeline | 45 |
| `tests/test_rag_dual_engine.py` | Cognitive engine | 46 |
| `tests/test_rag_production.py` | Production features | 43 |
| `tests/test_grpo.py` | GRPO + feedback store | 42 |
| `tests/test_guardrails.py` | Input/output security | 22 |
| `tests/test_hitl.py` | HITL approval | 21 |
| `tests/test_memory_full.py` | Long-term memory + store | 39 |
| `tests/test_quality.py` | Quality + convergence | 31 |
| `tests/test_enhancements.py` | Tracer contextmanager + behavioral assertions + HITL HumanNode + audit PII masking + eval isolation | 46 |
| `tests/test_workflow_full.py` | Workflow nodes + engine | 18 |
| `tests/test_cc_switch.py` | Model switching + CLI | 30+ |
| `tests/compiler/` | Pipeline compiler | ~60 |
| `tests/integration/` | End-to-end integration | ~100 |
| `tests/stores/` | State management | ~20 |

## 🌍 Environment Variables

| Variable | Required For | Description |
|----------|-------------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic Claude | API key (sk-... or sk-ant-...) |
| `ANTHROPIC_BASE_URL` | Custom gateway | Proxy/gateway URL |
| `ANTHROPIC_MODEL` | Model override | e.g. claude-opus-4-7 |
| `OPENAI_API_KEY` | OpenAI-compatible | Works for Tongyi/DeepSeek/Zhipu/Kimi/MiniMax |
| `OPENAI_BASE_URL` | Custom endpoint | OpenAI-compatible endpoint URL |
| `OPENAI_MODEL` | Model override | e.g. gpt-4o |
| `GEMINI_API_KEY` | Google Gemini | API key (AIza...) |

## 📐 Design Philosophy

1. **Schema-first, not code-first** — Define what, not how
2. **Dual-engine RAG** — Search for facts, cognitive for complex reasoning
3. **Self-improving** — Every successful run improves the skill library
4. **Feedback-driven** — Human feedback (👍👎) feeds GRPO preference optimization
5. **HITL by default** — Low auto, high manual, never blind trust
6. **Strict when needed** — `cc run --strict` blocks unsafe outputs instead of rewriting
7. **Behavioral eval** — Assert intent/tools/blocked, not exact output text
8. **PII-safe audit** — All args masked before persistence
9. **Isolated eval** — Per-case context isolation prevents state leakage
10. **Model-agnostic** — Switch providers without changing pipeline code
11. **Observable** — Every decision traced (contextmanager spans), every metric collected
12. **Marketplace-ready** — Publish skills as shareable Markdown files

## 🔮 Roadmap

- [ ] Multi-platform messaging gateway (Telegram/Discord/Slack)
- [ ] VS Code extension
- [ ] Visual drag-drop workflow builder
- [ ] Batch trajectory training pipeline
- [ ] Enterprise multi-tenant deployment
- [ ] PyPI publication (`pip install claude-codex-multi-agent`)

## License

MIT
