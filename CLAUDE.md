# Claude-Codex Multi-Agent Pipeline

## Project Overview
Schema-first multi-agent development pipeline. Compiles JSON schemas into orchestration logic, then dispatches to expert agents for code generation, quality review, and fix loops.

## Architecture

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

## Key Directories
- `agents/supervisor/` — Orchestrator (run_phase1, run_phase2, code generation)
- `agents/experts/` — Dynamic expert agents (auto-discovered, skills injection)
- `tools/compiler/` — Pipeline compiler (context deriver, quality gates, fix instructions)
- `tools/quality/` — Quality evaluation + convergence detection
- `tools/guardrails/` — Input/output security (injection/PII/leak/overpromise)
- `tools/memory/` — Short-term + long-term memory + session state
- `tools/hitl/` — Human-in-the-loop approval + audit logging
- `tools/workflow/` — DAG execution engine (topological sort + parallel branches)
- `tools/observability/` — Per-request tracing + pipeline metrics
- `tools/eval/` — Behavioral evaluation suite (25 cases, 5 dimensions)
- `tools/skills/` — Markdown-based skill system (3 built-in skills)
- `tools/mcp/` — MCP tool server (JSON-RPC over SSE)
- `tools/stores/` — State management (requirement, interface, spec stores)
- `tools/messaging/` — Event-driven message bus (pub/sub with topics)
- `tools/llm/` — LLM provider abstraction (mock + anthropic)
- `config/schemas/` — Module input/output schemas (JSON, 7 modules)
- `config/agents.yaml` — Agent registry and capabilities

## Adding a New Module
1. Add `config/schemas/xxx_input.json` + `xxx_output.json`
2. Add `expert_xxx` section to `config/agents.yaml` with capabilities
3. No Python code changes needed — auto-discovered at runtime

## Commands
```bash
# Run tests
python -m pytest tests/ -v

# Run eval suite
python -m tools.eval.runner

# Start MCP server (async)
python -c "import asyncio; from tools.mcp import *; ..."
```

## Environment Variables
- `ANTHROPIC_API_KEY` — API key for Anthropic Claude provider
- `LLM_API_KEY` — Generic LLM API key
