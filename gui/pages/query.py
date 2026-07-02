# gui/pages/query.py

"""Query tab — RAG dual-engine query with feedback collection."""

import time

import streamlit as st

from gui.state import _get_pipeline, _get_observer, _get_feedback_store


def render():
    """Render the Query tab."""
    st.header("RAG Query")
    st.caption("双引擎: Search Engine (BM25+Vector+Graph) + Cognitive Engine (Intent→Memory→Skill)")

    query_text = st.text_input("Enter your query:", placeholder="What is machine learning?")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)
    with col2:
        top_k = st.number_input("Top K", min_value=1, max_value=20, value=5)

    if search_clicked and query_text.strip():
        _execute_query(query_text, top_k)

    _render_history()


def _execute_query(query_text: str, top_k: int):
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

    st.session_state.query_history.append({
        "query": query_text,
        "intent": result.intent.primary_intent,
        "num_results": len(result.reranked_documents),
        "latency_ms": round(elapsed, 1),
    })

    # Display results
    st.subheader("Answer")
    st.info(result.answer)

    col_intent, col_conf = st.columns(2)
    with col_intent:
        st.metric("Intent", result.intent.primary_intent)
    with col_conf:
        st.metric("Confidence", f"{result.intent.confidence:.2f}")

    if result.reranked_documents:
        st.subheader(f"Documents ({len(result.reranked_documents)})")
        for i, doc in enumerate(result.reranked_documents, 1):
            with st.expander(f"[{i}] {doc.source} — score: {doc.score:.4f}"):
                st.write(doc.content[:500])
                st.json({k: v for k, v in doc.metadata.items() if k != "embedding"}, expanded=False)

    st.subheader("Pipeline Metrics")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Documents", result.metadata.get("num_documents", 0))
    m2.metric("Retrieved", result.metadata.get("num_retrieved", 0))
    m3.metric("Fused", result.metadata.get("num_fused", 0))
    m4.metric("Latency", f"{elapsed:.0f}ms")

    _render_feedback(query_text, result.answer)


def _render_feedback(query_text: str, answer: str):
    st.divider()
    st.subheader("Rate this response")
    st.caption("Your feedback is used for GRPO training to improve future responses.")

    col_up, col_down, col_detail = st.columns([1, 1, 3])
    with col_up:
        if st.button("👍 Good", key="thumbs_up", use_container_width=True):
            store = _get_feedback_store()
            store.add_rating(query_text, answer, rating=5.0, user="gui_user")
            st.success("Thanks! Saved 5/5 rating.")
    with col_down:
        if st.button("👎 Bad", key="thumbs_down", use_container_width=True):
            store = _get_feedback_store()
            store.add_rating(query_text, answer, rating=1.0, user="gui_user")
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
                store.add_correction(query_text, answer, correction, user="gui_user")
                st.success("Correction saved!")
            else:
                store.add_rating(query_text, answer, rating=rating, user="gui_user")
                st.success(f"Rating {rating}/5 saved!")


def _render_history():
    if st.session_state.query_history:
        with st.expander("Query History"):
            for h in reversed(st.session_state.query_history[-10:]):
                st.write(f"**{h['query']}** — {h['intent']} ({h['num_results']} results, {h['latency_ms']}ms)")
