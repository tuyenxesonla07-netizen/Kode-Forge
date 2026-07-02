# gui/pages/workflow.py

"""Workflow tab — Interactive pipeline runner with architecture diagrams."""

import time

import streamlit as st

from gui.state import _get_pipeline_system


def render():
    """Render the Workflow tab."""
    st.header("🔀 Pipeline Workflow")
    st.caption("Schema-first 多Agent编排流水线 — 运行 & 可视化")

    _render_pipeline_runner()
    _render_results()
    _render_architecture_diagrams()


def _render_pipeline_runner():
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
            run_clicked = st.button(
                "🚀 Run Full Pipeline", type="primary",
                use_container_width=True, disabled=not requirement_input.strip(),
            )
        with col_clear:
            if st.button("🗑 Clear Results", use_container_width=False):
                for k in ("pipeline_phase1", "pipeline_phase2", "pipeline_error"):
                    st.session_state.pop(k, None)
                st.rerun()

    if run_clicked and requirement_input.strip():
        _execute_pipeline(requirement_input.strip())


def _execute_pipeline(requirement_input: str):
    system = _get_pipeline_system()

    # Phase 1
    phase1_steps = []
    with st.status("🔄 Phase 1: Requirement → Code", expanded=True) as status:
        try:
            st.write("📋 Compiling pipeline...")
            t0 = time.time()
            phase1_result = system.run_phase1(requirement_input)
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


def _render_results():
    if "pipeline_phase1" not in st.session_state:
        return

    phase1_result = st.session_state.pipeline_phase1
    compiled = phase1_result.get("compiled")
    code_artifact = phase1_result.get("code_artifact", {})

    st.divider()
    st.subheader("📊 Execution Results")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Modules", len(compiled.implementation_order) if compiled else 0)
    m2.metric("Code Generated", len(code_artifact))
    if "pipeline_phase2" in st.session_state:
        p2 = st.session_state.pipeline_phase2
        m3.metric("Quality Score", f"{p2.get('quality_score', 0):.2f}")
        m4.metric("Iterations", p2.get("iterations", 0))

    if compiled:
        _render_implementation_order(compiled, code_artifact)
        _render_phase2_details()
        _render_module_specs(compiled, code_artifact)

    if "pipeline_error" in st.session_state:
        st.error(f"❌ Error: {st.session_state.pipeline_error}")


def _render_implementation_order(compiled, code_artifact):
    st.subheader("📋 Implementation Order")
    order_html = " → ".join(
        f"**{i+1}. {name}**" for i, name in enumerate(compiled.implementation_order)
    )
    st.markdown(order_html)


def _render_module_specs(compiled, code_artifact):
    st.subheader("📦 Module Specs")
    for module_name in compiled.implementation_order:
        with st.expander(f"🔧 {module_name}"):
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

            code = code_artifact.get(module_name, "")
            if code:
                st.code(code[:2000] + ("\n..." if len(code) > 2000 else ""), language="python")
            else:
                st.info("No code generated")


def _render_phase2_details():
    if "pipeline_phase2" not in st.session_state:
        return
    p2 = st.session_state.pipeline_phase2
    st.subheader("🔍 Phase 2 Review")
    col_p2_a, col_p2_b, col_p2_c = st.columns(3)
    col_p2_a.metric("Verdict", "PASS" if p2.get("passed") else "FAIL")
    col_p2_b.metric("Quality Score", f"{p2.get('quality_score', 0):.2f}")
    col_p2_c.metric("Convergence", p2.get("convergence_status", "unknown"))


def _render_architecture_diagrams():
    st.divider()

    with st.expander("📐 Phase 1 Architecture Diagram"):
        st.markdown("""```mermaid
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
```""")

    with st.expander("📐 Phase 2 Architecture Diagram"):
        st.markdown("""```mermaid
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
```""")

    with st.expander("📐 RAG Dual-Engine Diagram"):
        st.markdown("""```mermaid
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
```""")

    with st.expander("📐 Agent Dependency Graph"):
        st.markdown("""```mermaid
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
```""")
