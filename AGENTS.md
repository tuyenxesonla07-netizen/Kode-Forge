# Claude-Codex Multi-Agent Pipeline

This project uses a schema-driven multi-agent architecture for automated code generation.

## Core Principle
Agents are defined in `config/schemas` and `config/agents.yaml`.
Do not modify `agents/experts/__init__.py` unless adding new base capabilities.
New modules = new schema files + YAML registration only.

## Architecture (Full)

```
ClaudeCodexMultiAgent
├── Phase 1: Requirement → Code Generation
│   ├── InputGuard (security: injection detection + PII masking)
│   ├── Memory (short-term + long-term context)
│   ├── HITL Approval Gate (risk-based auto/manual approval)
│   ├── Compiler Pipeline (Schema → context/order/prompts/fixes/gates)
│   ├── Expert Agents (one per module, skills-injected prompts)
│   └── OutputGuard (code safety check + PII cleanup)
│
├── Phase 2: Code Review → Fix Loop
│   ├── QualityEvaluator (aggregate review results)
│   ├── ConvergenceDetector (improving/stagnant/declining trends)
│   └── Audit Log (JSONL persistence of all review events)
│
├── Workflow Engine (DAG execution)
│   ├── Topological sort (Kahn's algorithm)
│   ├── Parallel branch support
│   └── Conditional routing
│
├── Observability
│   ├── Tracer (per-request span tree with render_tree())
│   └── PipelineMetrics (token/agent/tool call tracking)
│
├── Eval Suite
│   ├── 25 behavioral test cases (module_gen, code_quality, security, budget, convergence)
│   ├── BehavioralCheckResult (per-check pass/fail with detail)
│   └── EvalReport (pass rate, table rendering, JSON export)
│
├── Skills (Markdown-based capability injection)
│   ├── code-review: Security, performance, type safety checks
│   ├── api-design: FastAPI best practices
│   └── security-audit: OWASP patterns, dangerous code detection
│
└── MCP Server (JSON-RPC over SSE)
    ├── generate_code: Schema → Python code
    ├── validate_python: Syntax validation
    ├── search_knowledge: Knowledge base search
    ├── compile_pipeline: Full pipeline compilation
    └── execute math: Safe math evaluation
```

## Key Files
- `__init__.py` — Main entry point with `ClaudeCodexMultiAgent` class
- `agents/supervisor/__init__.py` — `CodexSupervisor` with code generation and conflict resolution
- `agents/experts/__init__.py` — `ExpertAgent` with dynamic discovery and skill injection
- `config/schemas/` — Module definitions (input/output JSON Schema)
- `config/agents.yaml` — Agent capabilities and routing config
- `tools/compiler/` — Schema → orchestration logic compiler (5 sub-derivers)
- `tools/quality/` — Quality evaluation + convergence detection
- `tools/guardrails/` — Input/Output security guards
- `tools/memory/` — Short-term + long-term memory + session state
- `tools/hitl/` — Human-in-the-loop approval + audit logging
- `tools/workflow/` — DAG workflow engine
- `tools/observability/` — Tracer + pipeline metrics
- `tools/eval/` — Behavioral evaluation suite
- `tools/skills/` — Markdown-based skill system
- `tools/mcp/` — MCP tool server

## Adding a Module
1. Create `config/schemas/{module}_input.json` + `{module}_output.json`
2. Add `expert_{module}` to `config/agents.yaml` with capabilities list
3. Done — no Python changes needed

## Usage

```python
pipeline = ClaudeCodexMultiAgent(
    config_dir="config",
    llm_backend="mock",  # or "anthropic"
    enable_guardrails=True,
    enable_memory=True,
    enable_hitl=True,
    enable_observability=True,
)

# Full pipeline: Phase 1 + Phase 2
result = pipeline.run_full_pipeline("Build auth module with JWT")
print(result["phase1"]["code_artifact"])
print(result["phase2"]["convergence_status"])

# Eval suite
report = pipeline.run_eval()
print(report.render_table())
print(f"Pass rate: {report.pass_percentage}%")

# MCP server
server = pipeline.get_mcp_server(port=9000)
# await server.start_sse()
```
