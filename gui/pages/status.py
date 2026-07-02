# gui/pages/status.py

"""Status tab — System status, metrics, and GRPO training."""

import os

import streamlit as st

from gui.state import (
    _get_feedback_store,
    _get_observer,
    _get_pipeline,
    _get_switcher,
)


def render():
    """Render the Status tab."""
    st.header("📊 System Status")

    switcher = _get_switcher()
    observer = _get_observer()

    _render_model_status(switcher)
    _render_api_keys(switcher)
    _render_health_check(observer)
    _render_metrics(observer)
    _render_vector_store()
    _render_feedback_training()
    _render_env_vars()


def _render_model_status(switcher):
    st.subheader("LLM Model")
    status = switcher.status_display()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Provider", status["current_provider"])
    with col2:
        st.metric("Model", status["current_model"])


def _render_api_keys(switcher):
    st.subheader("API Keys")
    status = switcher.status_display()
    for name, has_key in status["has_key"].items():
        st.write(f"{'✅' if has_key else '❌'} {name}")


def _render_health_check(observer):
    st.subheader("Health Check")
    health = observer.health_check()
    st.json(health)


def _render_metrics(observer):
    metrics = observer.get_metrics_summary()
    if metrics.get("total_queries", 0) > 0:
        st.subheader("Metrics")
        st.json(metrics)


def _render_vector_store():
    st.subheader("Vector Store")
    pipeline = _get_pipeline()
    st.metric("Documents", pipeline.num_documents)


def _render_feedback_training():
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


def _render_env_vars():
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
