# tools/cli/pipeline.py
"""Pipeline sub-commands: run, serve, eval."""

from __future__ import annotations

import argparse


def cmd_run(args: argparse.Namespace) -> None:
    from agents.pipeline import Pipeline

    requirement = " ".join(args.requirement) if isinstance(args.requirement, list) else args.requirement
    backend = getattr(args, "backend", "workflow")

    print(f"\n  CC Pipeline Run")
    print(f"  ─────────────────────────────")
    print(f"  Requirement: {requirement[:80]}")
    print(f"  Backend:     {backend}\n")

    pipeline = Pipeline(
        llm_backend=getattr(args, "llm_backend", "mock"),
        enable_guardrails=True,
        enable_memory=False,
        enable_hitl=False,
    )
    result = pipeline.run(requirement)

    status = result.get("status", "unknown")
    print(f"  Status: {status}")
    if result.get("phase1") and result["phase1"].get("code_artifact"):
        artifacts = result["phase1"]["code_artifact"]
        print(f"  Generated {len(artifacts)} module(s):")
        for mod, code in artifacts.items():
            lines = code.count("\n") + 1
            print(f"    • {mod}: {lines} lines")
    print()


def cmd_serve(args: argparse.Namespace) -> None:
    from tools.server.app import create_app, ServerConfig
    from tools.rag import RAGPipeline, RAGConfig, Document

    config = ServerConfig(
        host=getattr(args, "host", "0.0.0.0"),
        port=getattr(args, "port", 8080),
    )

    rag_config = RAGConfig()
    rag_pipeline = RAGPipeline(rag_config)
    rag_pipeline.ingest([
        Document(content="Python is a high-level programming language.", source="wiki_python"),
        Document(content="Machine learning enables systems to learn from experience.", source="wiki_ml"),
    ])

    app = create_app(rag_engine=rag_pipeline, config=config)

    import uvicorn
    print(f"\n  CC Unified API Server")
    print(f"  ─────────────────────────────")
    print(f"  http://{config.host}:{config.port}")
    print(f"  Docs: http://{config.host}:{config.port}/docs")
    print(f"  Press Ctrl+C to stop\n")
    uvicorn.run(app, host=config.host, port=config.port)


def cmd_eval(args: argparse.Namespace) -> None:
    print("\n  CC Eval Suite")
    print("  ─────────────────────────────")
    try:
        from tools.eval.runner import EvalRunner
        runner = EvalRunner(verbose=True)
        report = runner.run_all()
        print(f"  {report.cases_passed}/{report.cases_total} passed ({report.pass_percentage:.0f}%)")
    except Exception as e:
        print(f"  ✗ Eval error: {e}")
        print("  ℹ Run: python -m tools.eval.runner")
