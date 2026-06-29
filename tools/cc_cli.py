"""CC CLI — 统一命令行入口 (执行层)。

对标:
  - Claude Code: 终端 Agent 执行
  - Codex: 轻量 CLI
  - OpenCode: 终端交互

Commands:
    cc init <project_name>          — 创建新项目脚手架
    cc init my-api --modules auth,api — 自定义模块创建脚手架
    cc run <requirement>          — 执行 Pipeline (Phase1 + Phase2)
    cc query <text>               — RAG 查询
    cc search <text>              — BM25+Vector 搜索
    cc model list                 — 列出所有模型
    cc model switch <provider>    — 切换模型
    cc model test                 — 测试连通性
    cc skills list                   — 列出所有 Skills
    cc skills search <query>         — 搜索 Skills
    cc skills publish <path>         — 发布 Skill
    cc skills unpublish <name>       — 下架 Skill
    cc train                      — 运行 GRPO 训练
    cc status                     — 系统状态
    cc serve                      — 启动 API 服务
    cc gui                       — 启动 GUI
    cc eval                       — 运行评估套件

Usage:
    python -m tools.cc_switch run "Build an auth module with JWT"
    python -m tools.cc_switch query "What is machine learning?"
    python -m tools.cc_switch model switch anthropic
    python -m tools.cc_switch serve --port 8080
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cc")


# ---------------------------------------------------------------------------
# CLI Implementation
# ---------------------------------------------------------------------------

def _cmd_model_list(args: argparse.Namespace) -> None:
    """列出所有供应商和模型。"""
    from tools.llm.model_switcher import ModelRegistry

    registry = ModelRegistry()
    entries = registry.list_display()

    print("\n" + "=" * 60)
    print("  CC Switch — Model Registry")
    print("=" * 60)

    for entry in entries:
        key_status = "✓" if entry["has_api_key"] else "✗"
        print(f"\n  [{key_status}] {entry['display_name']}")
        print(f"      Provider: {entry['name']}")
        print(f"      Default:  {entry['default_model']}")
        print(f"      Models:   {', '.join(entry['models'][:3])}")
        if entry["notes"]:
            print(f"      Notes:    {entry['notes']}")

    print("\n" + "-" * 60)
    print("  ✓ = API key detected  ✗ = no key")
    print("=" * 60)


def _cmd_model_switch(args: argparse.Namespace) -> None:
    """切换模型。"""
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)
    model = getattr(args, "model", None)

    if switcher.switch(args.provider, model):
        print(f"✓ Switched to {args.provider}/{model or 'default'}")
    else:
        print(f"✗ Unknown provider: {args.provider}")
        print(f"  Available: {', '.join(registry.list_providers())}")


def _cmd_model_test(args: argparse.Namespace) -> None:
    """测试模型连通性。"""
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)

    if hasattr(args, "provider") and args.provider:
        results = [switcher.test_provider(args.provider)]
    else:
        results = switcher.test_all()

    print("\n" + "=" * 60)
    print("  CC Switch — Connectivity Test")
    print("=" * 60)

    for r in results:
        status_icon = "✓" if r["status"] == "ok" else "✗"
        latency = r.get("latency_ms", 0)
        print(f"\n  [{status_icon}] {r['provider']}/{r['model']}")
        print(f"      Status:  {r['status']}")
        if latency:
            print(f"      Latency: {latency:.0f}ms")
        if r.get("error"):
            print(f"      Error:   {r['error'][:100]}")
        if r.get("env_var"):
            print(f"      Set:     export {r['env_var']}=...")

    print("\n" + "=" * 60)


def _cmd_status(args: argparse.Namespace) -> None:
    """显示系统状态。"""
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)
    status = switcher.status_display()

    print("\n" + "=" * 60)
    print("  CC Status — System Overview")
    print("=" * 60)

    print(f"\n  Current Model: {status['current_provider']}/{status['current_model']}")
    print(f"  Providers:     {len(status['available_providers'])}")

    # API Keys
    print("\n  API Keys:")
    for name, has_key in status["has_api_key"].items():
        icon = "✓" if has_key else "✗"
        print(f"    [{icon}] {name}")

    print("=" * 60)


def _cmd_validate(args: argparse.Namespace) -> None:
    """验证 schemas 和 agents.yaml 的一致性。"""
    import io, sys
    from tools.schema_validator import validate_all

    config_dir = getattr(args, "config_dir", "config")

    # Windows 控制台编码修复
    if sys.stdout.encoding and "gbk" in sys.stdout.encoding.lower():
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("\n" + "=" * 60)
    print("  CC Validate — Schema & Config Validation")
    print("=" * 60)
    print(f"\n  Config dir: {config_dir}\n")

    report = validate_all(config_dir)
    print(report.summary())
    print("=" * 60)

    # 如果有错误则退出码非零
    if not report.is_valid:
        exit(1)


def _cmd_query(args: argparse.Namespace) -> None:
    """RAG 查询。"""
    from tools.rag import RAGPipeline, RAGConfig

    config = RAGConfig()
    pipeline = RAGPipeline(config)

    # 尝试加载文档
    docs_path = getattr(args, "docs", None)
    if docs_path and os.path.exists(docs_path):
        _load_docs_from_path(pipeline, docs_path)
    else:
        # 使用示例文档
        _load_sample_docs(pipeline)

    result = pipeline.query(args.query, top_k=getattr(args, "top_k", 5))

    print(f"\n  Query: {result.query}")
    print(f"  Intent: {result.intent.primary_intent} ({result.intent.confidence:.2f})")
    print(f"  Documents: {len(result.reranked_documents)}")
    print(f"\n  Answer:\n  {result.answer}\n")

    if result.reranked_documents:
        print("  Sources:")
        for i, doc in enumerate(result.reranked_documents[:5], 1):
            print(f"    [{i}] {doc.source} (score: {doc.score:.4f})")
            print(f"        {doc.content[:100]}...")


def _cmd_search(args: argparse.Namespace) -> None:
    """BM25+Vector 搜索。"""
    from tools.rag import RAGPipeline, RAGConfig

    config = RAGConfig()
    pipeline = RAGPipeline(config)
    _load_sample_docs(pipeline)

    result = pipeline.query(args.query, top_k=getattr(args, "top_k", 5))

    print(f"\n  Search: {args.query}")
    print(f"  Found:  {len(result.reranked_documents)} results\n")

    for i, doc in enumerate(result.reranked_documents, 1):
        print(f"  [{i}] {doc.source} (score: {doc.score:.4f})")
        print(f"      {doc.content[:150]}...")
        print()


def _cmd_run(args: argparse.Namespace) -> None:
    """执行 Pipeline (需求 → 代码)。

    端到端流程:
      1. 加载 Schema → PipelineCompiler 编译
      2. 创建 ExpertAgent × N (自动发现)
      3. 每个 ExpertAgent 分析模块需求 (含 Skill 注入)
      4. QualityEvaluator 评估 + ConvergenceDetector 修复循环
      5. 输出 module_specs + quality report
    """
    print(f"\n  CC Pipeline — Executing: {args.requirement}")
    print("  " + "=" * 50)

    # ── 初始化组件 ──────────────────────────────────────────────
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry
    from tools.compiler import PipelineCompiler, PipelineConfig
    from tools.skills import SkillSelector, SkillLoader
    from tools.quality import QualityEvaluator
    from agents.experts import create_expert_agents, ExpertInput
    from agents.supervisor import CodexSupervisor, Requirement

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)
    provider, model = switcher.auto_select()

    print(f"\n  LLM: {provider}/{model}")

    # ── Phase 1: Schema → Pipeline 编译 ─────────────────────────
    print("\n  [Phase 1] Schema → Pipeline Compilation...")
    try:
        compiler = PipelineCompiler()
        pipeline_cfg = PipelineConfig.load("config/pipeline.yaml")
        compiled = compiler.compile_from_config("config")
        print(f"    Modules: {len(compiled.module_schemas)}")
        print(f"    Order: {' → '.join(compiled.implementation_order)}")
        print(f"    Quality gates: {len(compiled.quality_gates.gates)}")
        print(f"    Fix rules: {compiled.metadata['total_fix_rules']}")
    except Exception as e:
        print(f"    Error: {e}")
        return

    # ── Phase 2: ExpertAgent × N 分析 ───────────────────────────
    print("\n  [Phase 2] Expert Analysis × N...")

    # Skill 加载
    skill_loader = SkillLoader("tools/skills/builtin")
    skill_manager = SkillSelector(skill_loader)

    # LLM Provider
    from tools.llm import create_llm_provider
    llm_provider = create_llm_provider(provider)

    # 创建 Expert Agents
    experts = create_expert_agents(
        schemas_dir="config/schemas",
        llm_provider=llm_provider,
        skill_manager=skill_manager,
    )
    print(f"    Experts: {len(experts)} agents")

    # 加载 agents.yaml
    try:
        import yaml
        with open("config/agents.yaml", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
            yaml_lines = []
            in_yaml = False
            for line in lines:
                if line.strip().startswith("```yaml"):
                    in_yaml = True
                    continue
                if line.strip() == "```" and in_yaml:
                    break
                if in_yaml:
                    yaml_lines.append(line)
            agents_config = yaml.safe_load("\n".join(yaml_lines)) if yaml_lines else {}
    except Exception:
        agents_config = {}

    # Supervisor
    supervisor = CodexSupervisor(agents_config)
    requirement = Requirement(
        functional_modules=compiled.implementation_order,
        raw_text=args.requirement,
        constraints=[],
    )

    # 逐模块执行 ExpertAgent
    module_specs = {}
    # 建立模块名映射 (完整名 -> schema短名)
    _module_to_short = {
        "authentication": "authentication",
        "data_processing": "data_processing",
        "api_integration": "api_integration",
    }
    for module_name in compiled.implementation_order:
        short_name = _module_to_short.get(module_name, module_name)
        expert = experts.get(short_name)
        if not expert:
            print(f"    [{module_name}] No expert found, skipping")
            continue

        # Skill 匹配
        matched = skill_manager.select_for(args.requirement, module_type=module_name)

        expert_input = ExpertInput(
            module_name=module_name,
            requirement=args.requirement,
            constraints=[],
            global_constraints={},
        )

        try:
            output = expert.process(expert_input)
            spec = {
                "module_name": output.module_name,
                "components": output.components,
                "interfaces": output.interfaces,
                "acceptance_criteria": output.acceptance_criteria,
                "confidence": output.confidence,
            }
            module_specs[module_name] = spec
            comp_count = len(output.components)
            iface_count = len(output.interfaces)
            print(f"    [{module_name}] {comp_count} components, {iface_count} interfaces (conf={output.confidence:.2f})")
        except Exception as e:
            print(f"    [{module_name}] Error: {e}")

    # ── Phase 3: Quality Review ──────────────────────────────────
    print("\n  [Phase 3] Quality Review...")

    # Output guard with optional strict mode
    from tools.guardrails import OutputGuard
    strict_mode = getattr(args, "strict", False)
    output_guard = OutputGuard(strict=strict_mode)
    if strict_mode:
        print("    Strict mode: ON (overpromises will be blocked)")

    evaluator = QualityEvaluator()
    review_results = []
    for module_name, spec in module_specs.items():
        from tools.quality import ReviewResult
        review_results.append(ReviewResult(
            module=module_name,
            verdict="pass" if spec.get("confidence", 0) > 0.7 else "fail",
            confidence=spec.get("confidence", 0.0),
        ))

    quality_report = evaluator.evaluate(review_results)
    print(f"    Quality score: {quality_report.quality_score:.2f}")
    print(f"    Passed: {quality_report.passed}")
    print(f"    Recommendation: {quality_report.recommendation}")

    # ── 输出 ────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("  Pipeline Summary")
    print("=" * 50)
    print(f"  Modules analyzed: {len(module_specs)}")
    print(f"  Quality score: {quality_report.quality_score:.2f}")
    print(f"  Status: {'PASS' if quality_report.passed else 'NEEDS FIX'}")

    if module_specs:
        print("\n  Module Specs:")
        for name, spec in module_specs.items():
            print(f"    - {name}: {len(spec.get('components', []))} components")

    print("\n  [OK] Pipeline complete")
    print("  Note: Code generation requires real LLM API key")


def _cmd_feedback(args: argparse.Namespace) -> None:
    """提交反馈 (用于 GRPO 训练)。"""
    from tools.rag.feedback.rag_feedback import FeedbackStore

    store = FeedbackStore(getattr(args, "feedback_path", ".feedback.json"))
    feedback_type = getattr(args, "feedback_type", "rating")

    if feedback_type == "rating":
        rating = getattr(args, "rating", 3.0)
        store.add_rating(
            query=args.query,
            response=args.response,
            rating=rating,
            user=getattr(args, "user", "anonymous"),
        )
        print(f"  [OK] Rating saved: {rating}/5.0 for query: {args.query[:50]}...")

    elif feedback_type == "preference":
        store.add_preference(
            query=args.query,
            chosen=args.response,
            rejected=getattr(args, "rejected", ""),
            user=getattr(args, "user", "anonymous"),
        )
        print(f"  [OK] Preference saved for query: {args.query[:50]}...")

    elif feedback_type == "correction":
        store.add_correction(
            query=args.query,
            response=args.response,
            correction=getattr(args, "correction", ""),
            user=getattr(args, "user", "anonymous"),
        )
        print(f"  [OK] Correction saved for query: {args.query[:50]}...")

    print(f"  Total feedback: {store.size} samples")


def _cmd_train(args: argparse.Namespace) -> None:
    """运行 GRPO 训练。"""
    from tools.rag import RAGConfig, RealGRPOTrainer
    from tools.rag.feedback.rag_feedback import FeedbackStore

    config = RAGConfig()
    feedback_path = getattr(args, "feedback_path", ".feedback.json")
    store = FeedbackStore(feedback_path)

    if store.size == 0:
        print("  No feedback data. Use 'cc feedback' to add training data first.")
        print("  Example: cc feedback 'How to sort a list?' 'Use sorted()' --rating 5")
        return

    print(f"  GRPO Training")
    print(f"  {'=' * 50}")
    print(f"  Feedback samples: {store.size}")
    print(f"  Epochs: {config.grpo_epochs}")
    print(f"  Learning rate: {config.grpo_learning_rate}")

    trainer = RealGRPOTrainer(config, feedback=store)
    result = trainer.train()

    print(f"\n  Training complete:")
    print(f"    Mean reward: {result.mean_reward:.4f}")
    print(f"    Loss: {result.loss:.4f}")
    print(f"    Samples: {result.num_samples}")

    summary = trainer.get_weights_summary()
    if summary.get("top_features"):
        pos = summary["top_features"].get("positive", [])[:3]
        if pos:
            print(f"    Top positive: {', '.join(f'{n}({w:+.2f})' for n, w in pos)}")

    print(f"\n  [OK] Training complete ({trainer.step_count} steps)")


def _cmd_skills(args: argparse.Namespace) -> None:
    """Skills 管理 (list / search / publish / unpublish)。"""
    from tools.skills import SkillRegistry

    registry = SkillRegistry()
    action = getattr(args, "skills_action", "list")

    if action == "list":
        entries = registry.discover()
        print(f"\n  CC Skills Registry ({len(entries)} skills)")
        print(f"  {'=' * 50}")
        for meta in entries:
            triggers = ", ".join(meta.triggers[:4])
            print(f"\n  [{meta.name}] v{meta.version}")
            print(f"      {meta.description}")
            print(f"      Triggers: {triggers}")
            print(f"      Author: {meta.author}")
        print(f"\n  {'=' * 50}")

    elif action == "search":
        query = args.query or ""
        results = registry.search(query)
        print(f"\n  Search: '{query}' ({len(results)} results)")
        for meta in results:
            print(f"    - {meta.name}: {meta.description}")

    elif action == "publish":
        path = args.path
        overwrite = getattr(args, "overwrite", False)
        try:
            meta = registry.publish(path, overwrite=overwrite)
            print(f"  [OK] Published skill: {meta.name} v{meta.version}")
            print(f"      {meta.description}")
            print(f"      Path: {registry.skills_dir / meta.name}")
        except FileNotFoundError as e:
            print(f"  [ERROR] {e}")
        except ValueError as e:
            print(f"  [ERROR] {e}")

    elif action == "unpublish":
        name = args.name
        if registry.unpublish(name):
            print(f"  [OK] Unpublished skill: {name}")
        else:
            print(f"  [ERROR] Skill not found: {name}")

    else:
        print(f"  Unknown action: {action}")


def _cmd_serve(args: argparse.Namespace) -> None:
    """启动 API 服务。"""
    from tools.rag import RAGPipeline, RAGConfig, RAGObserver
    from tools.rag.api import RAGServer

    config = RAGConfig()
    pipeline = RAGPipeline(config)
    _load_sample_docs(pipeline)
    observer = RAGObserver()

    server = RAGServer(pipeline, observer)
    port = getattr(args, "port", 8080)
    host = getattr(args, "host", "0.0.0.0")

    print(f"\n  CC API Server")
    print(f"  ─────────────────────────────")
    print(f"  http://{host}:{port}")
    print(f"  Docs: http://{host}:{port}/docs")
    print(f"  Press Ctrl+C to stop\n")

    server.run(host=host, port=port)


def _cmd_gui(args: argparse.Namespace) -> None:
    """启动 GUI。"""
    import subprocess

    gui_path = os.path.join(os.path.dirname(__file__), "..", "..", "gui", "app.py")
    gui_path = os.path.normpath(gui_path)

    if not os.path.exists(gui_path):
        print(f"✗ GUI not found: {gui_path}")
        return

    port = getattr(args, "port", 8501)
    print(f"\n  CC GUI — Starting Streamlit...")
    print(f"  ─────────────────────────────")
    print(f"  http://localhost:{port}\n")

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", gui_path, "--server.port", str(port)],
        check=True,
    )


def _cmd_eval(args: argparse.Namespace) -> None:
    """运行评估套件。"""
    print("\n  CC Eval Suite")
    print("  ─────────────────────────────")

    try:
        from tools.eval.runner import run_evaluations

        run_evaluations()
    except Exception as e:
        print(f"  ✗ Eval error: {e}")
        print("  ℹ Run: python -m tools.eval.runner")


def _load_sample_docs(pipeline: Any) -> None:
    """加载示例文档。"""
    from tools.rag import Document

    docs = [
        Document(content="Python is a high-level programming language with dynamic semantics. Its high-level built-in data structures make it attractive for rapid application development.", source="wiki_python"),
        Document(content="Machine learning is a subset of artificial intelligence that enables systems to learn and improve from experience without being explicitly programmed.", source="wiki_ml"),
        Document(content="Docker is a platform for developing, shipping, and running applications in containers. Containers allow an application to be packaged with all its dependencies.", source="docs_docker"),
        Document(content="REST APIs use HTTP methods like GET, POST, PUT, and DELETE to interact with resources. They are the backbone of modern web services.", source="docs_rest"),
    ]
    pipeline.ingest(docs)


def _load_docs_from_path(pipeline: Any, path: str) -> None:
    """从文件加载文档。"""
    from tools.rag import Document

    docs = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        docs.append(Document(content=content, source=path))
    elif os.path.isdir(path):
        for root, _, files in os.walk(path):
            for fname in files:
                if fname.endswith((".py", ".md", ".txt", ".json")):
                    fpath = os.path.join(root, fname)
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if content.strip():
                        docs.append(Document(content=content[:10000], source=fpath))

    if docs:
        pipeline.ingest(docs)


# ---------------------------------------------------------------------------
# Argument Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="cc",
        description="CC — Claude-Codex Multi-Agent Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cc model list                          # 列出所有模型
  cc model switch anthropic               # 切换到 Claude
  cc model test                          # 测试连通性
  cc query "What is machine learning?"   # RAG 查询
  cc search "Python programming"         # 搜索
  cc status                              # 系统状态
  cc serve --port 8080                   # 启动 API
  cc gui                                 # 启动 GUI
  cc init my-project                     # Create scaffold with default modules
  cc init my-api --modules auth,api      # Custom modules
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- model ---
    model_parser = subparsers.add_parser("model", help="Model management")
    model_sub = model_parser.add_subparsers(dest="model_command")

    model_sub.add_parser("list", help="List all providers and models")

    switch_parser = model_sub.add_parser("switch", help="Switch provider")
    switch_parser.add_argument("provider", help="Provider name (e.g. anthropic, openai)")
    switch_parser.add_argument("--model", "-m", help="Model name", default=None)

    test_parser = model_sub.add_parser("test", help="Test connectivity")
    test_parser.add_argument("--provider", "-p", help="Specific provider", default=None)

    # --- query ---
    query_parser = subparsers.add_parser("query", help="RAG query")
    query_parser.add_argument("query", help="Query text")
    query_parser.add_argument("--top-k", "-k", type=int, default=5)
    query_parser.add_argument("--docs", "-d", help="Documents path", default=None)

    # --- search ---
    search_parser = subparsers.add_parser("search", help="BM25+Vector search")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--top-k", "-k", type=int, default=5)

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Execute pipeline")
    run_parser.add_argument("requirement", help="Requirement description")
    run_parser.add_argument("--strict", action="store_true",
                           help="Enable strict mode (block overpromises instead of rewriting)")

    # --- serve ---
    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument("--port", "-p", type=int, default=8080)
    serve_parser.add_argument("--host", default="0.0.0.0")

    # --- gui ---
    gui_parser = subparsers.add_parser("gui", help="Start GUI")
    gui_parser.add_argument("--port", "-p", type=int, default=8501)

    # --- eval ---
    subparsers.add_parser("eval", help="Run evaluation suite")

    # --- feedback ---
    feedback_parser = subparsers.add_parser("feedback", help="Submit feedback for GRPO training")
    feedback_parser.add_argument("query", help="Original query")
    feedback_parser.add_argument("response", help="Response to rate")
    feedback_parser.add_argument("--rating", "-r", type=float, default=3.0,
                                help="Rating 1-5 (default: 3.0)")
    feedback_parser.add_argument("--type", "-t", choices=["rating", "preference", "correction"],
                                default="rating", help="Feedback type")
    feedback_parser.add_argument("--rejected", help="Rejected response (for preference)")
    feedback_parser.add_argument("--correction", help="Correct response (for correction)")
    feedback_parser.add_argument("--user", "-u", default="anonymous", help="User ID")
    feedback_parser.add_argument("--feedback-path", default=".feedback.json",
                                help="Feedback storage path")

    # --- train ---
    train_parser = subparsers.add_parser("train", help="Run GRPO training")
    train_parser.add_argument("--feedback-path", default=".feedback.json",
                              help="Feedback storage path")
    train_parser.add_argument("--epochs", "-e", type=int, help="Number of training epochs")

    # --- skills ---
    skills_parser = subparsers.add_parser("skills", help="Skill management")
    skills_sub = skills_parser.add_subparsers(dest="skills_action")
    skills_sub.add_parser("list", help="List all skills")

    search_parser = skills_sub.add_parser("search", help="Search skills")
    search_parser.add_argument("query", help="Search query")

    publish_parser = skills_sub.add_parser("publish", help="Publish a skill")
    publish_parser.add_argument("path", help="Path to skill directory")
    publish_parser.add_argument("--overwrite", action="store_true",
                               help="Overwrite existing skill")

    unpublish_parser = skills_sub.add_parser("unpublish", help="Unpublish a skill")
    unpublish_parser.add_argument("name", help="Skill name to remove")

    # --- status ---
    subparsers.add_parser("status", help="System status")

    # --- validate ---
    validate_parser = subparsers.add_parser("validate", help="Validate schemas and agents.yaml")
    validate_parser.add_argument("--config-dir", default="config", help="Config directory path")

    # --- init ---
    from tools.cc_init import add_init_subparser
    add_init_subparser(subparsers)

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 路由
    if args.command == "model":
        if args.model_command == "list":
            _cmd_model_list(args)
        elif args.model_command == "switch":
            _cmd_model_switch(args)
        elif args.model_command == "test":
            _cmd_model_test(args)
        else:
            parser.parse_args(["model", "--help"])

    elif args.command == "query":
        _cmd_query(args)

    elif args.command == "search":
        _cmd_search(args)

    elif args.command == "run":
        _cmd_run(args)

    elif args.command == "serve":
        _cmd_serve(args)

    elif args.command == "gui":
        _cmd_gui(args)

    elif args.command == "eval":
        _cmd_eval(args)

    elif args.command == "feedback":
        _cmd_feedback(args)

    elif args.command == "train":
        _cmd_train(args)

    elif args.command == "skills":
        _cmd_skills(args)

    elif args.command == "init":
        from tools.cc_init import _cmd_init
        _cmd_init(args)

    elif args.command == "status":
        _cmd_status(args)

    elif args.command == "validate":
        _cmd_validate(args)


if __name__ == "__main__":
    main()
