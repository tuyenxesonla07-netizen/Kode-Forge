# 🧠 Claude-Codex Multi-Agent Pipeline (CC)

**Schema-first multi-agent development pipeline with RAG dual-engine, skill self-learning, and GRPO online optimization.**

> ⚠️ This is the project's AI-oriented documentation (for Claude Code). For user-facing docs, see [README.md](README.md).

## 🎯 Project Positioning

**The world's only** pipeline combining:
- **Schema-first multi-agent orchestration** (JSON Schema → compiled pipeline, not manual DAG)
- **RAG dual-engine** (Search: BM25+Vector+Graph→RRF→Rerank + Cognitive: Intent→Memory→Skill→GRPO)
- **Skill self-learning** (extract→store→match→improve from successful trajectories)
- **User modeling + intent routing** (4 intents × 3 expertise levels = 12 retrieval strategies)
- **GRPO feedback-driven optimization** (Group Relative Policy Optimization)
- **HITL risk-based approval** (auto/low → manual for medium/high risk)

**Closest competitor**: [Hermes Agent](https://github.com/NousResearch/hermes-agent) (self-improving personal assistant). This project focuses on **code generation engineering pipeline** rather than personal assistant.

## 🏗️ Architecture

```
User Requirement
  → InputGuard (security: injection detection + PII masking)
  → Memory.load() (restore context)
  → HITL.request_approval() (risk-based approval gate)
  → CodexSupervisor.parse_requirement() → identify modules
  → PipelineCompiler.compile() → context/order/prompts/fixes/gates
  → ExpertAgent.process() × N (with Skills injection)
  → Supervisor.generate_code() × N (LLM code gen + AST validation)
  → OutputGuard.check() (code safety + PII cleanup)
  → Memory.save() + SessionState.checkpoint()
  → QualityEvaluator + ConvergenceDetector (Phase 2 fix loop)
  → AuditLog.record() (all significant events)
  → Tracer + PipelineMetrics (cross-cutting observability)
```

## 📁 Key Directories

| Directory | Component | Description |
|-----------|-----------|-------------|
| `agents/supervisor/` | Orchestrator | `CodexSupervisor` — requirement parsing, task decomposition, fix strategy |
| `agents/experts/` | Expert Agents | Auto-discovered experts with skills injection |
| `tools/compiler/` | Pipeline Compiler | `ContextDeriver`, `FixDeriver`, `PromptGenerator`, `DependencyGraph` |
| `tools/quality/` | Quality | `QualityEvaluator` + `ConvergenceDetector` (Phase 2 fix loop) |
| `tools/guardrails/` | Security | `InputGuard` (injection/PII) + `OutputGuard` (code safety/leak) |
| `tools/memory/` | Memory | Short-term + long-term memory + `SessionState` checkpointing |
| `tools/hitl/` | HITL | Risk-based `AutoApprovalHandler` / `ManualApprovalHandler` + `AuditLog` |
| `tools/workflow/` | DAG Engine | Topological sort + parallel branch execution |
| `tools/observability/` | Observability | Per-request `Tracer` + `PipelineMetrics` |
| `tools/eval/` | Evaluation | 25 behavioral cases × 5 dimensions |
| `tools/skills/` | Skills | Markdown-based skill system (3 built-in skills) |
| `tools/mcp/` | MCP Server | JSON-RPC over SSE tool server |
| `tools/stores/` | State Stores | Requirement, interface, spec stores |
| `tools/messaging/` | Message Bus | Pub/sub with topics |
| `tools/llm/` | LLM Abstraction | Mock + Anthropic + OpenAI-compatible + Gemini providers |
| `tools/rag/` | RAG System | Dual-engine: Search (BM25+Vector+Graph) + Cognitive (Intent→Memory→Skill) |
| `tools/cc_switch.py` | Model Switcher | Multi-provider model switching + connectivity testing |
| `tools/cc_cli.py` | CLI | Unified command-line entry point |
| `gui/` | GUI | Streamlit visualization interface |
| `config/schemas/` | Module Schemas | JSON input/output definitions (3 modules) |
| `config/agents.yaml` | Agent Registry | Agent capabilities and dependency graph |
| `config/pipeline.yaml` | Pipeline Config | Phase definitions, quality gates, retry policies |

## 🚀 Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
# Optional providers:
pip install openai              # OpenAI-compatible
pip install anthropic           # Anthropic direct
pip install google-generativeai # Google Gemini
pip install streamlit           # GUI
```

### 2. Configure LLM

```bash
# Option A: Anthropic (recommended)
export ANTHROPIC_API_KEY="sk-..."
export ANTHROPIC_BASE_URL="https://your-gateway.example.com"  # optional
export ANTHROPIC_MODEL="claude-opus-4-7"                       # optional

# Option B: OpenAI-compatible
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o"

# Option C: Google Gemini
export GEMINI_API_KEY="AIza..."
```

### 3. Run CLI

```bash
# Model management
python -m tools.cc_switch model list
python -m tools.cc_switch model switch anthropic
python -m tools.cc_switch model test

# RAG query
python -m tools.cc_switch query "What is machine learning?"
python -m tools.cc_switch search "Python programming"

# System status
python -m tools.cc_switch status

# Validate schemas and agents.yaml
python -m tools.cc_switch validate

# Start API server
python -m tools.cc_switch serve --port 8080

# Start GUI
python -m tools.cc_switch gui --port 8501
# OR directly:
streamlit run gui/__init__.py

# Run tests
python -m pytest tests/ -v

# Run eval suite
python -m tools.eval.runner
```

### 4. Python API

```python
from tools.rag import RAGPipeline, RAGConfig, Document

# RAG query
config = RAGConfig()
pipeline = RAGPipeline(config)
pipeline.ingest([Document(content="...", source="...")])
result = pipeline.query("What is machine learning?")

# Multi-provider LLM
from tools.llm import create_llm_provider
provider = create_llm_provider("anthropic", model="claude-opus-4-7")
response = provider.complete("Analyze this requirement...")

# Model switching
from tools.cc_switch import ModelSwitcher, ModelRegistry
switcher = ModelSwitcher(ModelRegistry())
switcher.switch("openai", "gpt-4o")
provider = switcher.create_provider()
```

## 🔧 Adding a New Module

1. Add `config/schemas/xxx_input.json` + `xxx_output.json`
2. Add `expert_xxx` section to `config/agents.yaml` with capabilities
3. No Python code changes needed — auto-discovered at runtime

## 📊 Test Coverage

```
1095 tests passed, 13 skipped, 0 failed
```

| Test File | Coverage Area | Tests |
|-----------|--------------|-------|
| `tests/test_rag.py` | RAG pipeline | 45 |
| `tests/test_rag_dual_engine.py` | Cognitive engine | 46 |
| `tests/test_rag_production.py` | Production features | 43 |
| `tests/compiler/` | Pipeline compiler | ~67 |
| `tests/stores/` | State management | ~20 |
| `tests/integration/` | Integration tests | ~80 |
| `tests/test_resilience.py` | Error recovery | 24 |

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [QUICK_START.md](docs/QUICK_START.md) | 5 分钟上手指南 |
| [SCHEMA_GUIDE.md](docs/SCHEMA_GUIDE.md) | 模块 Schema 编写指南 |
| [PIPELINE_CONFIG.md](docs/PIPELINE_CONFIG.md) | 质量门禁/超时/重试配置 |
| [RAG_CONFIG.md](docs/RAG_CONFIG.md) | RAG 双引擎调参 |
| [SKILL_AUTHORING.md](docs/SKILL_AUTHORING.md) | Skill 编写指南 |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker / 生产部署 |

## 🌍 Environment Variables

| Variable | Required For | Description |
|----------|-------------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic Claude | API key (sk-... or sk-ant-...) |
| `ANTHROPIC_BASE_URL` | Custom gateway | Proxy/gateway URL (e.g. dayueai.fun) |
| `ANTHROPIC_MODEL` | Model override | e.g. claude-opus-4-7 |
| `OPENAI_API_KEY` | OpenAI-compatible | Works for Tongyi/DeepSeek/Zhipu/Kimi/MiniMax |
| `OPENAI_BASE_URL` | Custom endpoint | OpenAI-compatible endpoint URL |
| `OPENAI_MODEL` | Model override | e.g. gpt-4o |
| `GEMINI_API_KEY` | Google Gemini | API key (AIza...) |

## 📐 Competitor Comparison Summary

| Feature | **This Project** | Claude Code | Cursor | Hermes | Dify | Coze | Gemini CLI |
|---------|-----------------|-------------|--------|--------|------|------|-------------|
| Schema-first | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multi-Agent | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| RAG Dual-Engine | ✅ | ❌ | ❌ | Partial | Search only | Search only | ❌ |
| Skill Self-Learning | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| User Modeling | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| GRPO Training | ✅ | ❌ | ❌ | Partial | ❌ | ❌ | ❌ |
| HITL Approval | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Vector Store | Milvus/Chroma/Mem | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| Query Rewrite | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| REST API + WS | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| CLI + GUI | ✅ | ✅ CLI | ✅ IDE | ❌ | ❌ | ✅ | ✅ CLI |
| Model Switching | ✅ 20+ providers | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |

See [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md) for detailed comparison.
