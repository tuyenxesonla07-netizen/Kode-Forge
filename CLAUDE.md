# Claude-Codex Multi-Agent

Schema-First Compilation Architecture for Multi-Agent Development Pipeline

## Quick Start

```bash
# Run all tests
python -B -m pytest tests/ -v

# Run end-to-end trace example
python -B -c "import examples.ecommerce_trace; examples.ecommerce_trace.run_trace()"
```

## Project Structure

```
claude-codex-multi-agent/
├── __init__.py              # Main entry: ClaudeCodexMultiAgent class
├── config/
│   ├── agents.yaml           # Agent registry (7 experts + supervisor + plugin)
│   ├── pipeline.yaml         # Pipeline configuration (phases, quality gates)
│   └── schemas/              # JSON Schema for each module (input + output)
│       ├── auth_input.json / auth_output.json
│       ├── product_input.json / product_output.json
│       └── ...
├── tools/
│   ├── compiler/             # Core compilation engine
│   │   ├── pipeline_compiler.py   # Main compiler: Schema → orchestration logic
│   │   ├── context_deriver.py     # Derive context injection from input schemas
│   │   ├── fix_deriver.py         # Derive fix instructions from output schemas
│   │   ├── prompt_generator.py    # Auto-generate Prompt from schemas
│   │   ├── dependency_graph.py    # Dependency graph + topological sort
│   │   └── quality_gate_gen.py    # Auto-generate quality gates from schemas
│   ├── stores/               # Runtime data storage
│   │   ├── requirement_store.py   # Module requirements
│   │   ├── interface_store.py     # Interface definitions
│   │   └── spec_store.py          # Module specifications
│   ├── messaging/            # Communication layer
│   │   ├── message.py             # Unified message envelope
│   │   └── message_bus.py         # Event-driven message bus
│   └── quality/              # Quality assurance
│       ├── quality_evaluator.py   # Evaluate quality gates
│       └── convergence_detector.py# Detect fix loop convergence
├── agents/
│   ├── supervisor/           # Codex supervisor agent
│   │   └── __init__.py           # CodexSupervisor class
│   └── experts/              # Expert agents (7 modules)
│       └── __init__.py           # AuthExpert, OrderExpert, etc.
├── examples/
│   └── ecommerce_trace.py    # Executable end-to-end trace
├── tests/
│   ├── compiler/             # Unit tests for compiler components
│   ├── stores/               # Unit tests for stores
│   ├── integration/          # Integration tests
│   │   ├── test_e2e_pipeline.py         # Original E2E tests
│   │   ├── test_full_pipeline.py        # Full pipeline integration
│   │   ├── test_system_integration.py   # System-level integration
│   │   └── test_edge_cases.py           # Edge cases
│   └── ...
└── docs/
    ├── architecture.md       # System architecture overview
    ├── agent-design.md       # Detailed agent design
    ├── deep-design-spec.md   # Comprehensive design spec
    ├── protocols.md          # Communication protocols
    └── ...
```

## Architecture

```
User → Codex (主管) → PipelineCompiler → Expert Agents → Claude Code
                          ↓
                    ContextDeriver → 自动注入上下文
                    FixInstructionDeriver → 自动修复模板
                    QualityGateGenerator → 自动质量门禁
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| `PipelineCompiler` | `tools/compiler/pipeline_compiler.py` | Compiles schemas → orchestration logic |
| `ContextDeriver` | `tools/compiler/context_deriver.py` | Derives context injection strategy |
| `FixInstructionDeriver` | `tools/compiler/fix_deriver.py` | Derives fix instruction templates |
| `PromptTemplateGenerator` | `tools/compiler/prompt_generator.py` | Generates Prompt from schemas |
| `QualityGateGenerator` | `tools/compiler/quality_gate_gen.py` | Generates quality gates from schemas |
| `ConvergenceDetector` | `tools/quality/convergence_detector.py` | Detects fix loop convergence |
| `ClaudeCodexMultiAgent` | `__init__.py` | Main entry point |

## Module Configuration

7 functional modules defined in `config/agents.yaml`:

| Module | Expert | Dependencies |
|--------|--------|-------------|
| authentication | AuthExpert | (none) |
| product_catalog | ProductExpert | authentication |
| shopping_cart | CartExpert | authentication |
| order_system | OrderExpert | authentication, shopping_cart |
| payment_integration | PaymentExpert | authentication, order_system |
| notification_service | NotificationExpert | authentication |
| data_reporting | ReportExpert | authentication, order_system |

## Progressive Enhancement

| Phase | What | When |
|-------|------|------|
| 0 | Pure Superpowers | Agent ≤ 3, quick validation |
| 1 | Python Compiler (current) | Agent > 3, need Schema validation |
| 2 | Quality Evaluator | Need algorithmic quality scoring |
| 3 | Orchestration Engine | Need independent deployment |

## Testing

```bash
# All tests
python -B -m pytest tests/ -v

# Specific test file
python -B -m pytest tests/compiler/test_context_deriver.py -v

# With coverage
python -B -m pytest tests/ --cov=tools --cov=agents -v
```
