"""CC GUI — Streamlit 可视化界面 (观察层).

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

import os
import sys

import streamlit as st

from gui.state import (
    init_session_state,
    _get_switcher,
    _get_feedback_store,
)


def main():
    """Entry point for the Streamlit GUI."""
    # Page config
    st.set_page_config(
        page_title="KodeForge",
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Initialize session state
    init_session_state()

    # Render sidebar
    _render_sidebar()

    # Render tabs
    from gui.pages import (
        render_query,
        render_search,
        render_workflow,
        render_skills,
        render_eval,
        render_status,
    )

    tab_query, tab_search, tab_workflow, tab_skills, tab_eval, tab_status = st.tabs([
        "💬 Query", "🔍 Search", "🔀 Workflow", "📚 Skills", "🧪 Eval", "📊 Status",
    ])

    with tab_query:
        render_query()
    with tab_search:
        render_search()
    with tab_workflow:
        render_workflow()
    with tab_skills:
        render_skills()
    with tab_eval:
        render_eval()
    with tab_status:
        render_status()

    # Footer
    st.divider()
    st.caption(
        "🧠 KodeForge | "
        "Schema-first · RAG Dual-Engine · Skill Self-Learning · GRPO Online Optimization"
    )


def _render_sidebar():
    """Render the sidebar with model switcher and system info."""
    from tools.llm.model_switcher import ModelRegistry

    with st.sidebar:
        st.title("🧠 CC Pipeline")
        st.caption("KodeForge")
        st.divider()

        # Model status
        switcher = _get_switcher()
        provider, model = switcher.current
        st.metric("Current Model", f"{provider}/{model}")

        # Quick switch
        st.subheader("Quick Switch")
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

        # API Key status
        for name in providers[:6]:
            has_key = bool(os.environ.get(registry.get(name).api_key_env)) if registry.get(name) else False
            st.write(f"{'✅' if has_key else '❌'} {name}")

        # Feedback stats
        feedback_store = _get_feedback_store()
        st.divider()
        st.caption(f"📝 Feedback: {feedback_store.size} samples")

        st.divider()
        st.caption("🔗 GUI Layer")
        st.code("cc gui", language="bash")
        st.code("cc serve", language="bash")


if __name__ == "__main__":
    # Ensure project root is on sys.path when run directly
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    main()
