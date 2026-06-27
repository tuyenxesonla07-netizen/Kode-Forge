# Claude-Codex Multi-Agent Pipeline

**Schema-First Multi-Agent Development Pipeline** — a Python framework that compiles module schemas into structured agent workflows, with integrated guardrails, memory, HITL, observability, eval, skills, and MCP server.

## Features

| Feature | Description |
|---------|-------------|
| **Schema-First Compilation** | JSON schemas automatically derive context injection, implementation order, fix templates, and quality gates |
| **7 Expert Agents + 1 Supervisor** | Hierarchical delegation with dependency-aware topological ordering |
| **Dual-Phase Pipeline** | Phase 1 (requirement → code) + Phase 2 (review → fix loop with convergence detection) |
| **Guardrails** | Input injection detection + PII masking, output leak prevention + code safety checks |
| **Memory System** | Short-term (sliding window + compression) + Long-term (persistent user profiles) |
| **HITL** | Risk-based approval (low=auto, medium=auto/manual, high=human) with JSONL audit logging |
| **Workflow Engine** | DAG-based execution with topological sort, parallel branches, conditional routing |
| **Observability** | Per-request span tree with `render_tree()`, pipeline metrics (token/agent/tool tracking) |
| **Eval Suite** | 25 behavioral test cases across 5 dimensions (module_gen, code_quality, security, budget, convergence) |
| **Skills** | Markdown-based capability injection (code-review, api-design, security-audit) |
| **MCP Server** | JSON-RPC over SSE exposing generate_code, validate_python, compile_pipeline |
| **Pluggable LLM** | Mock provider (deterministic, no API key) + Anthropic Claude integration |

## Architecture

### System Layers

```
User Requirement
  │
  ▼
ClaudeCodexMultiAgent.run_full_pipeline()
  │
  ├── Phase 1: run_phase1()
  │   ├── InputGuard.check()  → injection/PII protection
  │   ├── Memory.load()       → restore context
  │   ├── HITL.request()      → approval gate
  │   ├── PipelineCompiler.compile()
  │   │   ├── ContextDeriver    → auto-inject context
  │   │   ├── DependencyGraph   → topological order
  │   │   ├── PromptGenerator   → prompt template
  │   │   ├── FixDeriver        → fix instructions
  │   │   └── QualityGateGen    → quality gates
  │   ├── ExpertAgent.process() × N  (with Skills injection)
  │   ├── Supervisor.generate_code() × N
  │   ├── OutputGuard.check()   → code safety check
  │   ├── Memory.save()        → persist interaction
  │   └── SessionState.checkpoint()
  │
  ├── Phase 2: run_phase2()
  │   ├── ExpertAgent.review() × N
  │   ├── QualityEvaluator.evaluate()
  │   ├── ConvergenceDetector.should_continue()
  │   └── AuditLog.record()
  │
  └── Observability + Audit  (cross-cutting, active throughout)
```

### Module Dependency Graph

```
authentication ─────┬──→ product_catalog ──→ shopping_cart ──→ order_system ──→ payment_integration
                    │                                           ↑
                    ├──→ notification_service                    │
                    └──→ data_reporting ─────────────────────────┘
```

### Core Roles

| Role | Count | Responsibility |
|------|-------|----------------|
| Codex (Supervisor) | 1 | Requirement understanding, task decomposition, quality evaluation, conflict resolution |
| Superpowers Plugin | 1 | Agent registration, message routing, context injection, result aggregation |
| Prompt Agent | 1 | Module spec integration, dependency analysis, prompt generation |
| Expert Agent | N (per module) | Single-module requirement analysis, code review |
| Claude Code | 1 | Code generation, fix execution |

### Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Single Responsibility** | Each Expert Agent handles one functional module only; input/output schemas enforce strict boundaries |
| **Minimum Privilege** | Superpowers ContextInjector only injects the minimum required context per module |
| **Independently Testable** | Each Agent can run in isolation; same input produces deterministic output |
| **Verifiable Results** | All outputs must pass output_schema validation; includes acceptance criteria |

### Communication Protocol

All Agent-to-Agent communication uses a unified message format with metadata envelope and typed payloads (task / result / review / error). Message codes follow E001-E010 convention with retry semantics. See `tools/messaging/` for implementation.

### Convergence Detection

The system uses a `ConvergenceDetector` that tracks quality trends across review iterations, detecting improving / stagnant / declining states. Critical issues trigger immediate escalation. This prevents the "death spiral" of automated fix loops making things worse.

## Quick Start

```python
from __init__ import ClaudeCodexMultiAgent

# Initialize pipeline (mock LLM, all features enabled)
pipeline = ClaudeCodexMultiAgent(
    config_dir="config",
    llm_backend="mock",  # or "anthropic" with ANTHROPIC_API_KEY
    enable_guardrails=True,
    enable_memory=True,
    enable_hitl=True,
    enable_observability=True,
)

# Run full pipeline (Phase 1 + Phase 2)
result = pipeline.run_full_pipeline("Build auth module with JWT")

# Access results
print(result["phase1"]["code_artifact"])       # Generated code per module
print(result["phase2"]["convergence_status"])  # Why the fix loop stopped
print(result["phase2"]["iterations"])          # Number of fix iterations

# Inspect observability
obs = result.get("observability", {})
print(obs.get("trace_tree"))  # Visual span tree

# Run eval suite
report = pipeline.run_eval()
print(report.render_table())
print(f"Pass rate: {report.pass_percentage}%")

# Start MCP server
server = pipeline.get_mcp_server(port=9000)
# await server.start_sse()  # Requires: pip install sse-starlette
```

## Project Structure

```
claude-codex-multi-agent/
├── __init__.py                    # Main entry point (ClaudeCodexMultiAgent class)
├── README.md                      # This file
├── requirements.txt               # Python dependencies
│
├── agents/
│   ├── supervisor/__init__.py     # CodexSupervisor (orchestration + code generation)
│   └── experts/__init__.py        # ExpertAgent (dynamic discovery, skill injection)
│
├── tools/
│   ├── compiler/                  # Schema → orchestration logic (5 sub-derivers)
│   │   ├── pipeline_compiler.py   # Main compiler entry
│   │   ├── context_deriver.py     # Auto-derive context injection strategies
│   │   ├── dependency_graph.py    # Build DAG, topological sort
│   │   ├── prompt_generator.py    # Generate prompt templates
│   │   ├── fix_deriver.py         # Derive fix instructions from schemas
│   │   └── quality_gate_gen.py    # Auto-generate quality gates
│   │
│   ├── quality/                   # Quality evaluation + convergence detection
│   │   ├── quality_evaluator.py   # Aggregate review results
│   │   └── convergence_detector.py # Detect improving/stagnant/declining trends
│   │
│   ├── guardrails/                # Input/output security
│   │   ├── input_guard.py         # Injection detection + PII masking
│   │   └── output_guard.py        # Leak prevention + overpromise rewriting
│   │
│   ├── memory/                    # Short-term + long-term memory
│   │   ├── short_term.py          # Sliding window + auto-compression
│   │   ├── long_term.py           # JSON persistence + user profiles
│   │   ├── session_state.py       # Checkpoint/resume
│   │   └── store.py               # MemoryStore interface + implementations
│   │
│   ├── hitl/                      # Human-in-the-loop
│   │   ├── approval.py            # AutoApprovalHandler + ManualApprovalHandler
│   │   └── audit.py               # AuditLog (JSONL persistence)
│   │
│   ├── workflow/                  # DAG execution engine
│   │   ├── engine.py              # WorkflowEngine (topological sort + parallel branches)
│   │   └── nodes.py               # LLMNode, RAGNode, ToolNode, CodeNode, BranchNode
│   │
│   ├── observability/             # Tracing + metrics
│   │   ├── tracer.py              # Per-request span tree with render_tree()
│   │   └── metrics.py             # PipelineMetrics (token/agent/tool tracking)
│   │
│   ├── eval/                      # Behavioral evaluation
│   │   ├── cases.py               # 25 test cases across 5 dimensions
│   │   ├── assertions.py           # Behavioral check functions
│   │   ├── runner.py              # EvalRunner
│   │   └── report.py              # EvalReport with table rendering
│   │
│   ├── skills/                    # Markdown-based capability injection
│   │   ├── loader.py              # SKILL.md parser (no YAML dependency)
│   │   ├── manager.py             # Skill selection by relevance
│   │   └── builtin/               # Built-in skills
│   │       ├── code-review/
│   │       ├── api-design/
│   │       └── security-audit/
│   │
│   ├── mcp/                       # Model Context Protocol
│   │   ├── tool_registry.py       # Tool registration + discovery
│   │   ├── mcp_server.py          # JSON-RPC over SSE server
│   │   └── builtin_tools.py       # Built-in tool definitions
│   │
│   ├── stores/                    # State management
│   │   ├── requirement_store.py   # Requirements persistence
│   │   ├── interface_store.py     # Interface definitions
│   │   ├── spec_store.py          # Module specs persistence
│   │   └── persistence.py         # Base persistence interface
│   │
│   ├── messaging/                 # Event-driven communication
│   │   ├── message_bus.py         # Pub/sub with topic routing
│   │   └── message.py             # Message + Topic definitions
│   │
│   └── llm/                       # LLM provider abstraction
│       ├── base.py                # LLMProvider ABC + LLMResponse
│       ├── mock.py                # MockLLMProvider (deterministic, no API key)
│       └── anthropic.py           # AnthropicClaudeProvider
│
├── config/
│   ├── agents.yaml                # Agent registry + capabilities + dependencies
│   └── schemas/                   # Module input/output JSON schemas
│       ├── auth_input.json / auth_output.json
│       ├── product_input.json / product_output.json
│       ├── cart_input.json / cart_output.json
│       ├── order_input.json / order_output.json
│       ├── payment_input.json / payment_output.json
│       ├── notification_input.json / notification_output.json
│       └── report_input.json / report_output.json
│
└── tests/
    ├── compiler/                  # Unit tests for compiler sub-derivers
    ├── stores/                    # Unit tests for stores
    └── integration/               # Integration tests
        ├── test_e2e_pipeline.py   # End-to-end pipeline tests
        ├── test_full_pipeline.py  # Full pipeline integration
        ├── test_system_integration.py # Main entry point tests
        └── test_edge_cases.py     # Boundary conditions
```

## Adding a Module

1. Create `config/schemas/{module}_input.json` + `{module}_output.json`
2. Add `expert_{module}` section to `config/agents.yaml` with capabilities
3. No Python code changes needed — auto-discovered at runtime

## LLM Provider Configuration

```python
# Mock (default) — no API key needed, deterministic output
pipeline = ClaudeCodexMultiAgent(llm_backend="mock")

# Anthropic Claude — requires ANTHROPIC_API_KEY
pipeline = ClaudeCodexMultiAgent(
    llm_backend="anthropic",
    api_key="sk-ant-...",  # or set ANTHROPIC_API_KEY env var
)
```

## Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
python -m pytest tests/ -v

# Run specific test suite
python -m pytest tests/compiler/ -v
python -m pytest tests/integration/test_e2e_pipeline.py -v

# With coverage (requires pytest-cov)
python -m pytest tests/ --cov=tools --cov=agents -v

# Lint
ruff check tools/ agents/ tests/ --ignore E501
```

## Eval Suite

```python
pipeline = ClaudeCodexMultiAgent()

# Run all 25 eval cases
report = pipeline.run_eval()
print(report.render_table())
print(report.to_json())  # Export as JSON

# Run specific cases only
from tools.eval.cases import EVAL_CASES
module_gen_cases = [c for c in EVAL_CASES if c["id"].startswith("module_gen")]
report = pipeline.run_eval(cases=module_gen_cases)
```

## MCP Server

```python
pipeline = ClaudeCodexMultiAgent()
server = pipeline.get_mcp_server(host="localhost", port=9000)

# In an async context:
# await server.start_sse()
# Available at: http://localhost:9000/sse
# POST to: http://localhost:9000/mcp with JSON-RPC 2.0
```

## Docker Deployment

### Quick Start

```bash
# Build and run eval suite (one command)
docker build -t ccm . && docker run --rm ccm

# Or with docker compose
docker compose up --build eval
```

### Run Modes

```bash
# MCP Server (default for 'up')
docker compose up

# Run eval suite
docker compose run --rm eval

# Run tests
docker compose run --rm test

# Lint check
docker compose run --rm lint

# Interactive shell
docker run --rm -it ccm shell

# Full pipeline with custom input
docker run --rm ccm pipeline "Build auth module with JWT"
```

### Deploy to GitHub Container Registry

Push to `main` triggers automatic build and push to `ghcr.io`:

```bash
# Pull and run anywhere
docker pull ghcr.io/<your-user>/claude-codex-multi-agent:latest
docker run -d --name ccm -p 9000:9000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e LLM_BACKEND=anthropic \
  ghcr.io/<your-user>/claude-codex-multi-agent:latest serve
```

### Deploy to VPS

Add these GitHub Secrets:
- `DEPLOY_HOST` — server IP/hostname
- `DEPLOY_USER` — SSH username
- `DEPLOY_SSH_KEY` — private SSH key
- `ANTHROPIC_API_KEY` — (optional) for real LLM

The workflow auto-deploys on every push to `main`.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | API key for Anthropic Claude | — |
| `LLM_API_KEY` | Generic LLM API key | — |

## Design Decisions

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Codex as sole supervisor | Avoids multi-supervisor decision conflicts | Single point of failure; needs fault tolerance |
| Superpowers mediates all communication | Enforces minimum privilege and context isolation | Adds one-hop latency |
| Module split by functional domain | Higher cohesion, fewer cross-Agent dependencies | Module granularity must be manually defined |
| Two-phase (separate analyze/review) | Each phase focuses on its own concern | Adds one round of communication |
| Prompt Agent as independent | Decouples integration logic from decision logic | Adds one more Agent to manage |
| Schema-driven validation | Ensures verifiable results, prevents error propagation | Requires pre-defined complete schemas |
| Event-driven message bus | Natural fit for async task-response patterns | Harder to debug than REST |
| Three-store separation (Req/Interface/Spec) | Separates read/write timing, avoids state coupling | Adds Superpowers internal complexity |

## Project Status & Roadmap

**Current state**: Core pipeline runs end-to-end with mock LLM. Compiler, stores, convergence detection, guardrails, and observability are implemented. 95 integration tests passing.

### Roadmap

| Phase | Items | Timeline |
|-------|-------|----------|
| **P0** | Real LLM integration (Claude API), code generator (write actual files), requirements.txt | 1-2 weeks |
| **P1** | Store persistence (SQLite/Redis), API server (FastAPI with streaming), multi-LLM support | 1 month |
| **P2** | RAG module, Dashboard | 3 months |
| **Plugin** | Dynamic Agent registration, Human-in-the-loop pause/resume, regression test framework | Ongoing |

## License

MIT
