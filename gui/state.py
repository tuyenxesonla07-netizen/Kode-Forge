# gui/state.py

"""Streamlit session state management and lazy initialization."""

import os
import time

import streamlit as st


def init_session_state():
    """Initialize all session state variables if not present."""
    defaults = {
        "pipeline": None,
        "observer": None,
        "switcher": None,
        "query_history": [],
        "feedback_store": None,
        "skill_manager": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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
    if st.session_state.feedback_store is None:
        from tools.rag.feedback.rag_feedback import FeedbackStore
        st.session_state.feedback_store = FeedbackStore(".feedback.json")
    return st.session_state.feedback_store


def _get_skill_manager():
    if st.session_state.skill_manager is None:
        from pathlib import Path
        from tools.plugins import PluginSkillRegistry
        st.session_state.skill_manager = PluginSkillRegistry(plugins_dir=Path("plugins"))
        st.session_state.skill_manager.load()
    return st.session_state.skill_manager


def _get_pipeline_system():
    """Get or create a fresh KodeForge instance."""
    from agents.pipeline import KodeForge
    return KodeForge(
        llm_backend="mock",
        enable_guardrails=False,
        enable_memory=False,
        enable_hitl=False,
        enable_observability=False,
    )


# Convenience re-exports
__all__ = [
    "init_session_state",
    "_get_pipeline",
    "_get_observer",
    "_get_switcher",
    "_get_feedback_store",
    "_get_skill_manager",
    "_get_pipeline_system",
]
