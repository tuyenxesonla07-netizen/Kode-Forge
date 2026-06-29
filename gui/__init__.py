"""CC GUI — Streamlit 可视化界面 (观察层)。

功能:
  1. 模型切换 (Model Switcher)
  2. RAG 查询 (Query) — 含反馈收集 (👍/👎)
  3. 搜索 (Search)
  4. 工作流可视化 (Workflow Canvas)
  5. Skills 浏览器
  6. 评估仪表盘 (Eval Dashboard)
  7. 系统状态 (Status)

Usage:
    streamlit run gui/__init__.py
    或: cc gui
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

import streamlit as st

st.set_page_config(
    page_title="CC — Claude-Codex Multi-Agent Pipeline",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "pipeline" not in st.session_state:
    st.session_state.pipeline = None
if "observer" not in st.session_state:
    st.session_state.observer = None
if "switcher" not in st.session_state:
    st.session_state.switcher = None
if "query_history" not in st.session_state:
    st.session_state.query_history = []


# ---------------------------------------------------------------------------
# Lazy initialization
# ---------------------------------------------------------------------------

def _get_pipeline():
    if st.session_state.pipeline is None:
        from tools.rag import RAGPipeline, RAGConfig, Document

        config = RAGConfig()
        pipeline = RAGPipeline(config)

        docs = [
            Document(content="Python is a high-level programming language with dynamic semantics. Its high-level built-in data structures make it attractive for rapid application development.", source="wiki_python"),
            Document(content="Machine learning is a subset of artificial intelligence that enables systems to learn and improve from experience without being explicitly programmed.", source="wiki_ml"),
            Document(content="FastAPI is a modern, fast web framework for building APIs with Python 3.7+ based on standard Python type hints. It supports async/await and automatic OpenAPI docs.", source="docs_fastapi"),
            Document(content="Docker is a platform for developing, shipping, and running applications in containers. Containers allow an application to be packaged with all its dependencies.", source="docs_docker"),
            Document(content="REST APIs use HTTP methods like GET, POST, PUT, and DELETE to interact with resources. They are the backbone of modern web services and follow stateless communication patterns.", source="docs_rest"),
            Document(content="JWT (JSON Web Tokens) are a compact, URL-safe means of representing claims to be transferred between two parties. They are commonly used for authentication and authorization.", source="docs_jwt"),
            Document(content="Kubernetes is an open-source container orchestration system for automating deployment, scaling, and management.", source="docs_k8s"),
            Document(content="Neural networks are computing systems inspired by biological neural networks.", source="wiki_nn"),
            Document(content="The Eiffel Tower is a wrought-iron lattice tower located in Paris, France.", source="wiki_eiffel"),
        ]
        pipeline.ingest(docs)
        st.session_state.pipeline = pipeline

    return st.session_state.pipeline


def _get_observer():
    if st.session_state.observer is None:
        from tools.rag import RAGObserver

        st.session_state.observer = RAGObserver()
    return st.session_state.observer


def _get_switcher():
    if st.session_state.switcher is None:
        from tools.llm.model_switcher import ModelSwitcher, ModelRegistry

        st.session_state.switcher = ModelSwitcher(ModelRegistry())
    return st.session_state.switcher


def _get_feedback_store():
    if "feedback_store" not in st.session_state:
        from tools.rag.feedback.rag_feedback import FeedbackStore
        st.session_state.feedback_store = FeedbackStore(".feedback.json")
    return st.session_state.feedback_store


def _get_skill_manager():
    if "skill_manager" not in st.session_state:
        from tools.skills import SkillSelector, SkillLoader
        loader = SkillLoader("tools/skills/builtin")
        st.session_state.skill_manager = SkillSelector(loader)
    return st.session_state.skill_manager


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🧠 CC Pipeline")
    st.caption("Claude-Codex Multi-Agent Pipeline")
    st.divider()

    # 模型状态
    switcher = _get_switcher()
    provider, model = switcher.current
    st.metric("Current Model", f"{provider}/{model}")

    # 快速切换
    st.subheader("Quick Switch")
    from tools.llm.model_switcher import ModelRegistry

    registry = ModelRegistry()
    providers = registry.list_providers()
    selected_provider = st.selectbox("Provider", providers, index=providers.index(provider) if provider in providers else 0)

    cfg = registry.get(selected_provider)
    if cfg:
        selected_model = st.selectbox("Model", cfg.models, index=0)
        if st.button("Switch", use_container_width=True):
            switcher.switch(selected_provider, selected_model)
            st.rerun()

    st.divider()
    st.caption("📊 System")

    # API Key 状态
    for name in providers[:6]:
        has_key = bool(os.environ.get(registry.get(name).api_key_env)) if registry.get(name) else False
        st.write(f"{'✅' if has_key else '❌'} {name}")

    # 反馈统计
    feedback_store = _get_feedback_store()
    st.divider()
    st.caption(f"📝 Feedback: {feedback_store.size} samples")

    st.divider()
    st.caption("🔗 GUI Layer")
    st.code("cc gui", language="bash")
    st.code("cc serve", language="bash")


# ---------------------------------------------------------------------------
# Main content — Tabs
# ---------------------------------------------------------------------------

tab_query, tab_search, tab_workflow, tab_skills, tab_eval, tab_status = st.tabs([
    "💬 Query", "🔍 Search", "🔀 Workflow", "📚 Skills", "🧪 Eval", "📊 Status",
])


# ---------------------------------------------------------------------------
# Tab: Query (with feedback)
# ---------------------------------------------------------------------------

with tab_query:
    st.header("RAG Query")
    st.caption("双引擎: Search Engine (BM25+Vector+Graph) + Cognitive Engine (Intent→Memory→Skill)")

    query_text = st.text_input("Enter your query:", placeholder="What is machine learning?")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)
    with col2:
        top_k = st.number_input("Top K", min_value=1, max_value=20, value=5)

    if search_clicked and query_text.strip():
        pipeline = _get_pipeline()
        observer = _get_observer()
        start = time.time()

        result = pipeline.query(query_text, top_k=top_k)
        elapsed = (time.time() - start) * 1000

        observer.record_query(
            query=query_text,
            num_results=len(result.reranked_documents),
            latency_ms=elapsed,
            intent=result.intent.primary_intent,
        )

        # 保存历史
        st.session_state.query_history.append({
            "query": query_text,
            "intent": result.intent.primary_intent,
            "num_results": len(result.reranked_documents),
            "latency_ms": round(elapsed, 1),
        })

        # 显示结果
        st.subheader("Answer")
        st.info(result.answer)

        # Intent
        col_intent, col_conf = st.columns(2)
        with col_intent:
            st.metric("Intent", result.intent.primary_intent)
        with col_conf:
            st.metric("Confidence", f"{result.intent.confidence:.2f}")

        # 文档
        if result.reranked_documents:
            st.subheader(f"Documents ({len(result.reranked_documents)})")
            for i, doc in enumerate(result.reranked_documents, 1):
                with st.expander(f"[{i}] {doc.source} — score: {doc.score:.4f}"):
                    st.write(doc.content[:500])
                    st.json({k: v for k, v in doc.metadata.items() if k != "embedding"}, expanded=False)

        # Metrics
        st.subheader("Pipeline Metrics")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Documents", result.metadata.get("num_documents", 0))
        m2.metric("Retrieved", result.metadata.get("num_retrieved", 0))
        m3.metric("Fused", result.metadata.get("num_fused", 0))
        m4.metric("Latency", f"{elapsed:.0f}ms")

        # --- Feedback section ---
        st.divider()
        st.subheader("Rate this response")
        st.caption("Your feedback is used for GRPO training to improve future responses.")

        col_up, col_down, col_detail = st.columns([1, 1, 3])
        with col_up:
            if st.button("👍 Good", key="thumbs_up", use_container_width=True):
                store = _get_feedback_store()
                store.add_rating(query_text, result.answer, rating=5.0, user="gui_user")
                st.success("Thanks! Saved 5/5 rating.")
        with col_down:
            if st.button("👎 Bad", key="thumbs_down", use_container_width=True):
                store = _get_feedback_store()
                store.add_rating(query_text, result.answer, rating=1.0, user="gui_user")
                st.warning("Thanks! Saved 1/5 rating. We'll improve.")

        with st.expander("Detailed rating"):
            rating = st.slider("Rating", 1, 5, 3, key="detail_rating")
            correction = st.text_area(
                "Correction (optional)",
                placeholder="What should the correct answer be?",
                key="correction_input",
            )
            if st.button("Submit feedback", key="submit_feedback"):
                store = _get_feedback_store()
                if correction.strip():
                    store.add_correction(query_text, result.answer, correction, user="gui_user")
                    st.success("Correction saved!")
                else:
                    store.add_rating(query_text, result.answer, rating=rating, user="gui_user")
                    st.success(f"Rating {rating}/5 saved!")

    # 查询历史
    if st.session_state.query_history:
        with st.expander("Query History"):
            for h in reversed(st.session_state.query_history[-10:]):
                st.write(f"**{h['query']}** — {h['intent']} ({h['num_results']} results, {h['latency_ms']}ms)")


# ---------------------------------------------------------------------------
# Tab: Search
# ---------------------------------------------------------------------------

with tab_search:
    st.header("BM25 + Vector + Graph Search")
    st.caption("三路召回 → RRF 融合 → Rerank 排序")

    search_text = st.text_input("Search:", placeholder="Python programming", key="search_input")

    if st.button("Search", key="search_btn", use_container_width=True) and search_text.strip():
        pipeline = _get_pipeline()
        result = pipeline.query(search_text, top_k=5)

        if result.retrieved_documents:
            st.subheader(f"All Retrieved ({len(result.retrieved_documents)})")

            # 按 retriever 分组
            retrievers: dict[str, list] = {}
            for doc in result.retrieved_documents:
                r = doc.metadata.get("retriever", "unknown")
                retrievers.setdefault(r, []).append(doc)

            for retriever_name, docs in retrievers.items():
                with st.expander(f"📦 Retriever: {retriever_name} ({len(docs)} docs)"):
                    for doc in docs:
                        st.write(f"- **{doc.source}** (score: {doc.score:.4f})")
                        st.caption(doc.content[:200])

        # Rerank 结果
        if result.reranked_documents:
            st.subheader("🏆 Reranked Results")
            for i, doc in enumerate(result.reranked_documents, 1):
                score_color = "🟢" if doc.score > 0.7 else "🟡" if doc.score > 0.4 else "🔴"
                st.write(f"{score_color} **[{i}] {doc.source}** — `{doc.score:.4f}`")
                st.caption(doc.content[:200])


# ---------------------------------------------------------------------------
# Tab: Workflow Canvas (Interactive Pipeline Runner)
# ---------------------------------------------------------------------------

with tab_workflow:
    st.header("🔀 Pipeline Workflow")
    st.caption("Schema-first 多Agent编排流水线 — 运行 & 可视化")

    # --- Interactive Pipeline Runner ---
    st.subheader("▶ Run Pipeline")
    with st.expander("展开输入面板", expanded=True):
        requirement_input = st.text_area(
            "需求描述",
            placeholder="构建一个在线商城，支持用户注册登录、商品浏览、购物车、下单和支付",
            key="pipeline_requirement_input",
            height=80,
        )

        col_run, col_clear = st.columns([1, 5])
        with col_run:
            run_clicked = st.button("🚀 Run Full Pipeline", type="primary", use_container_width=True, disabled=not requirement_input.strip())
        with col_clear:
            if st.button("🗑 Clear Results", use_container_width=False):
                for k in ("pipeline_phase1", "pipeline_phase2", "pipeline_error"):
                    st.session_state.pop(k, None)
                st.rerun()

    # --- Execute Pipeline ---
    if run_clicked and requirement_input.strip():
        from agents.pipeline import ClaudeCodexMultiAgent

        system = ClaudeCodexMultiAgent(
            llm_backend="mock",
            enable_guardrails=False,
            enable_memory=False,
            enable_hitl=False,
            enable_observability=False,
        )

        # Phase 1
        phase1_steps = []
        with st.status("🔄 Phase 1: Requirement → Code", expanded=True) as status:
            try:
                st.write("📋 Compiling pipeline...")
                t0 = time.time()
                phase1_result = system.run_phase1(requirement_input.strip())
                phase1_elapsed = time.time() - t0

                compiled = phase1_result.get("compiled")
                code_artifact = phase1_result.get("code_artifact", {})

                phase1_steps.append(f"✅ Pipeline compiled: {len(compiled.implementation_order)} modules")
                phase1_steps.append(f"✅ Implementation order: {' → '.join(compiled.implementation_order)}")
                phase1_steps.append(f"✅ Code generated: {len(code_artifact)} modules")
                phase1_steps.append(f"⏱ Phase 1 completed in {phase1_elapsed:.1f}s")

                st.session_state.pipeline_phase1 = phase1_result
                status.update(label=f"✅ Phase 1 Complete ({phase1_elapsed:.1f}s)", state="complete")
            except Exception as e:
                phase1_steps.append(f"❌ Phase 1 failed: {e}")
                status.update(label="❌ Phase 1 Failed", state="error")
                st.session_state.pipeline_error = str(e)

        # Phase 2
        if "pipeline_phase1" in st.session_state and "pipeline_error" not in st.session_state:
            phase1_result = st.session_state.pipeline_phase1
            code_artifact = phase1_result.get("code_artifact", {})
            compiled = phase1_result.get("compiled")

            with st.status("🔄 Phase 2: Review → Convergence", expanded=True) as status:
                try:
                    t0 = time.time()
                    phase2_result = system.run_phase2(
                        code_artifact,
                        compiled_pipeline=compiled,
                    )
                    phase2_elapsed = time.time() - t0

                    st.session_state.pipeline_phase2 = phase2_result

                    verdict = "✅ PASSED" if phase2_result.get("passed") else "⚠️ NEEDS FIX"
                    status.update(
                        label=f"{verdict} — Phase 2 Complete ({phase2_elapsed:.1f}s)",
                        state="complete" if phase2_result.get("passed") else "error",
                    )
                except Exception as e:
                    status.update(label="❌ Phase 2 Failed", state="error")
                    st.session_state.pipeline_error = str(e)

    # --- Display Results ---
    if "pipeline_phase1" in st.session_state:
        phase1_result = st.session_state.pipeline_phase1
        compiled = phase1_result.get("compiled")
        code_artifact = phase1_result.get("code_artifact", {})

        st.divider()
        st.subheader("📊 Execution Results")

        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Modules", len(compiled.implementation_order) if compiled else 0)
        m2.metric("Code Generated", len(code_artifact))
        if "pipeline_phase2" in st.session_state:
            p2 = st.session_state.pipeline_phase2
            m3.metric("Quality Score", f"{p2.get('quality_score', 0):.2f}")
            m4.metric("Iterations", p2.get("iterations", 0))

        # Implementation order
        if compiled:
            st.subheader("📋 Implementation Order")
            order_html = " → ".join(
                f"**{i+1}. {name}**" for i, name in enumerate(compiled.implementation_order)
            )
            st.markdown(order_html)

            # Module details
            st.subheader("📦 Module Specs")
            for module_name in compiled.implementation_order:
                with st.expander(f"🔧 {module_name}"):
                    # Strategy info
                    strategy = compiled.context_strategies.get(module_name)
                    if strategy:
                        flags = []
                        if strategy.needs_security_context:
                            flags.append("🔒 Security")
                        if strategy.needs_compliance_context:
                            flags.append("📋 Compliance")
                        if strategy.needs_dependency_interfaces:
                            deps = ", ".join(strategy.depends_on) if strategy.depends_on else "none"
                            flags.append(f"🔗 Deps: {deps}")
                        if flags:
                            st.write(" · ".join(flags))

                    # Generated code
                    code = code_artifact.get(module_name, "")
                    if code:
                        st.code(code[:2000] + ("\n..." if len(code) > 2000 else ""), language="python")
                    else:
                        st.info("No code generated")

        # Phase 2 details
        if "pipeline_phase2" in st.session_state:
            p2 = st.session_state.pipeline_phase2
            st.subheader("🔍 Phase 2 Review")
            col_p2_a, col_p2_b, col_p2_c = st.columns(3)
            col_p2_a.metric("Verdict", "PASS" if p2.get("passed") else "FAIL")
            col_p2_b.metric("Quality Score", f"{p2.get('quality_score', 0):.2f}")
            col_p2_c.metric("Convergence", p2.get("convergence_status", "unknown"))

        # Error display
        if "pipeline_error" in st.session_state:
            st.error(f"❌ Error: {st.session_state.pipeline_error}")

    # --- Architecture Diagrams (collapsed) ---
    st.divider()
    with st.expander("📐 Phase 1 Architecture Diagram"):
        phase1_graph = """
        graph LR
            A["📋 User Requirement"] --> B["🔒 InputGuard<br/>(Security Check)"]
            B --> C["🧠 Memory Load<br/>(Restore Context)"]
            C --> D["✋ HITL Approval<br/>(Risk-based Gate)"]
            D --> E["📊 CodexSupervisor<br/>parse_requirement()"]
            E --> F["🔧 PipelineCompiler<br/>compile()"]
            F --> G["📦 ExpertAgent × N<br/>(Parallel Code Gen)"]
            G --> H["🔍 QualityEvaluator<br/>(Review & Score)"]
            H --> I["✅ OutputGuard<br/>(Safety Check)"]
            I --> J["💾 Memory Save<br/>+ Checkpoint"]
            J --> K["📤 Code Artifact"]

            style A fill:#fff3e0,stroke:#e65100
            style B fill:#fce4ec,stroke:#c62828
            style D fill:#fff9c4,stroke:#f57f17
            style E fill:#fff3e0,stroke:#e65100
            style F fill:#f3e5f5,stroke:#6a1b9a
            style G fill:#e3f2fd,stroke:#1565c0
            style H fill:#e8f5e9,stroke:#2e7d32
            style K fill:#c8e6c9,stroke:#2e7d32
        """
        st.markdown(f"```mermaid\n{phase1_graph}\n```")

    with st.expander("📐 Phase 2 Architecture Diagram"):
        phase2_graph = """
        graph LR
            A["📤 Code Artifact"] --> B["📦 Distribute<br/>to Experts"]
            B --> C["🔍 Expert Review × N<br/>(Parallel)"]
            C --> D["📊 QualityEvaluator<br/>+ ConvergenceDetector"]
            D --> E{"✅ Pass?"}
            E -->|"Yes"| F["📤 Deliver"]
            E -->|"No"| G["🔧 Fix Strategy<br/>(Supervisor Decides)"]
            G --> H["✏️ Apply Fixes"]
            H --> B

            style A fill:#fff3e0,stroke:#e65100
            style C fill:#e3f2fd,stroke:#1565c0
            style D fill:#e8f5e9,stroke:#2e7d32
            style E fill:#fff9c4,stroke:#f57f17
            style F fill:#c8e6c9,stroke:#2e7d32
            style G fill:#fce4ec,stroke:#c62828
        """
        st.markdown(f"```mermaid\n{phase2_graph}\n```")

    with st.expander("📐 RAG Dual-Engine Diagram"):
        rag_graph = """
        graph TB
            Q["Query"] --> SW{"Engine Mode"}

            SW -->|"Search"| SE["🔍 Search Engine"]
            SE --> BM25["📝 BM25 Retriever"]
            SE --> VEC["📐 Vector Retriever"]
            SE --> GRP["🕸️ Graph Retriever"]
            BM25 --> FUS["⚡ RRF Fusion"]
            VEC --> FUS
            GRP --> FUS
            FUS --> RERANK["🏆 Rerank<br/>(CrossEncoder + LLM + Vector)"]
            RERANK --> ANS1["Answer"]

            SW -->|"Cognitive"| CE["🧠 Cognitive Engine"]
            CE --> INTENT["🎯 Intent Classifier"]
            CE --> MEM["💾 Memory Manager"]
            CE --> SKILL["📚 Skill Manager"]
            INTENT --> ROUTER["🔀 IntentRouter<br/>(12 Strategies)"]
            MEM --> CTX["Context Builder"]
            SKILL --> CTX
            ROUTER --> RETRIEVE["Selective Retrieval"]
            RETRIEVE --> CTX
            CTX --> GEN["🧬 GRPO-Trained<br/>Answer Generator"]
            GEN --> ANS2["Answer + Context"]

            style Q fill:#fff3e0,stroke:#e65100
            style SE fill:#e3f2fd,stroke:#1565c0
            style CE fill:#f3e5f5,stroke:#6a1b9a
            style RERANK fill:#e8f5e9,stroke:#2e7d32
            style GEN fill:#e8f5e9,stroke:#2e7d32
        """
        st.markdown(f"```mermaid\n{rag_graph}\n```")

    with st.expander("📐 Agent Dependency Graph"):
        agent_graph = """
        graph LR
            CS["🧠 Codex Supervisor<br/>(Orchestrator)"] --> PA["📝 Prompt Agent<br/>(Integrator)"]
            CS --> SP["⚡ Superpowers<br/>(Message Bus)"]
            SP --> EA1["🔐 Auth Expert"]
            SP --> EA2["📦 Product Expert"]
            SP --> EA3["🛒 Cart Expert"]
            SP --> EA4["📋 Order Expert"]
            SP --> EA5["💳 Payment Expert"]
            SP --> EA6["🔔 Notification Expert"]
            SP --> EA7["📊 Report Expert"]

            EA2 --> EA1
            EA3 --> EA1
            EA3 --> EA2
            EA4 --> EA1
            EA4 --> EA3
            EA5 --> EA1
            EA5 --> EA4
            EA6 --> EA1
            EA7 --> EA1
            EA7 --> EA4

            style CS fill:#fff3e0,stroke:#e65100
            style SP fill:#fce4ec,stroke:#c62828
            style PA fill:#f3e5f5,stroke:#6a1b9a
            style EA1 fill:#e3f2fd,stroke:#1565c0
            style EA2 fill:#e3f2fd,stroke:#1565c0
            style EA3 fill:#e3f2fd,stroke:#1565c0
            style EA4 fill:#e3f2fd,stroke:#1565c0
            style EA5 fill:#e3f2fd,stroke:#1565c0
            style EA6 fill:#e3f2fd,stroke:#1565c0
            style EA7 fill:#e3f2fd,stroke:#1565c0
        """
        st.markdown(f"```mermaid\n{agent_graph}\n```")


# ---------------------------------------------------------------------------
# Tab: Skills
# ---------------------------------------------------------------------------

with tab_skills:
    st.header("📚 Skills")
    st.caption("Markdown-based skill system — auto-discovered and injected into agent prompts")

    skill_manager = _get_skill_manager()
    skills = skill_manager.list_skills()

    st.subheader(f"Available Skills ({len(skills)})")

    for skill in skills:
        with st.expander(f"**{skill['name']}** — {skill['description']}"):
            st.markdown(f"**Triggers**: {', '.join(skill['triggers'])}")
            st.markdown("---")
            loader = skill_manager.loader
            full_skill = loader.load(skill["name"])
            if full_skill:
                st.markdown(full_skill.system_snippet)

    # Skill publishing info
    st.divider()
    st.subheader("Publish a Skill")
    st.markdown("""
    To publish a skill:

    1. Create a directory under `tools/skills/builtin/` (or any custom path)
    2. Add a `SKILL.md` file with YAML frontmatter
    3. Run `cc skills publish <path>` to register it

    Example SKILL.md:
    ```yaml
    ---
    name: my-skill
    description: What this skill does
    triggers: [keyword1, keyword2]
    ---

    # Skill Content
    Your instructions here...
    ```""")


# ---------------------------------------------------------------------------
# Tab: Eval
# ---------------------------------------------------------------------------

with tab_eval:
    st.header("🧪 Evaluation Suite")
    st.caption("Behavioral evaluation: 25 cases × 5 dimensions")

    if st.button("▶ Run Evaluation", use_container_width=True, type="primary"):
        try:
            from tools.eval.runner import run_evaluations

            with st.spinner("Running evaluations..."):
                results = run_evaluations()

            st.success("Evaluation complete!")
            st.json(results if isinstance(results, dict) else {"status": "done"})
        except Exception as e:
            st.error(f"Evaluation error: {e}")
            st.exception(e)

    # 评估维度说明
    st.subheader("Evaluation Dimensions")
    st.write("""
    | Dimension | Weight | Description |
    |-----------|--------|-------------|
    | Correctness | 30% | Does the output correctly implement the requirement? |
    | Completeness | 20% | Are all functional modules covered? |
    | Code Quality | 20% | Is the code well-structured, typed, documented? |
    | Security | 15% | Are there injection vulnerabilities or unsafe patterns? |
    | Efficiency | 15% | Is the solution performant and non-rendundant? |
    """)


# ---------------------------------------------------------------------------
# Tab: Status
# ---------------------------------------------------------------------------

with tab_status:
    st.header("📊 System Status")

    switcher = _get_switcher()
    observer = _get_observer()
    status = switcher.status_display()

    # 模型状态
    st.subheader("LLM Model")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Provider", status["current_provider"])
    with col2:
        st.metric("Model", status["current_model"])

    # API Keys
    st.subheader("API Keys")
    for name, has_key in status["has_key"].items():
        st.write(f"{'✅' if has_key else '❌'} {name}")

    # 健康检查
    st.subheader("Health Check")
    health = observer.health_check()
    st.json(health)

    # 指标
    metrics = observer.get_metrics_summary()
    if metrics.get("total_queries", 0) > 0:
        st.subheader("Metrics")
        st.json(metrics)

    # 向量存储状态
    st.subheader("Vector Store")
    pipeline = _get_pipeline()
    st.metric("Documents", pipeline.num_documents)

    # 反馈统计
    st.subheader("Feedback & GRPO Training")
    store = _get_feedback_store()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Samples", store.size)
    col2.metric("Ratings", len(store.get_samples_by_type("rating")))
    col3.metric("Preferences", len(store.get_samples_by_type("preference")))
    col4.metric("Corrections", len(store.get_samples_by_type("correction")))

    if st.button("Run GRPO Training", disabled=store.size == 0):
        with st.spinner("Training..."):
            try:
                from tools.rag import RAGConfig, RealGRPOTrainer

                config = RAGConfig()
                trainer = RealGRPOTrainer(config, feedback=store)
                result = trainer.train()

                st.success("Training complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Mean Reward", f"{result.mean_reward:.4f}")
                col2.metric("Loss", f"{result.loss:.6f}")
                col3.metric("Samples", result.num_samples)

                summary = trainer.get_weights_summary()
                if summary.get("top_features"):
                    st.subheader("Top Features")
                    pos = summary["top_features"].get("positive", [])[:5]
                    if pos:
                        st.markdown("**Positive:** " + ", ".join(
                            f"`{n}` ({w:+.4f})" for n, w in pos
                        ))
            except Exception as e:
                st.error(f"Training error: {e}")

    # 环境变量
    with st.expander("Environment Variables"):
        env_vars = {
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")[:8] + "..." if os.environ.get("ANTHROPIC_API_KEY") else "(not set)",
            "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", "(not set)"),
            "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", "(not set)"),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")[:8] + "..." if os.environ.get("OPENAI_API_KEY") else "(not set)",
            "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "")[:8] + "..." if os.environ.get("GEMINI_API_KEY") else "(not set)",
            "LLM_API_KEY": os.environ.get("LLM_API_KEY", "")[:8] + "..." if os.environ.get("LLM_API_KEY") else "(not set)",
        }
        st.json(env_vars)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    "🧠 CC — Claude-Codex Multi-Agent Pipeline | "
    "Schema-first · RAG Dual-Engine · Skill Self-Learning · GRPO Online Optimization"
)


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    main()