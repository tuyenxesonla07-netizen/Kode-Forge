# gui/pages/search.py

"""Search tab — BM25 + Vector + Graph retrieval visualization."""

import streamlit as st

from gui.state import _get_pipeline


def render():
    """Render the Search tab."""
    st.header("BM25 + Vector + Graph Search")
    st.caption("三路召回 → RRF 融合 → Rerank 排序")

    search_text = st.text_input("Search:", placeholder="Python programming", key="search_input")

    if st.button("Search", key="search_btn", use_container_width=True) and search_text.strip():
        pipeline = _get_pipeline()
        result = pipeline.query(search_text, top_k=5)

        if result.retrieved_documents:
            st.subheader(f"All Retrieved ({len(result.retrieved_documents)})")

            retrievers: dict[str, list] = {}
            for doc in result.retrieved_documents:
                r = doc.metadata.get("retriever", "unknown")
                retrievers.setdefault(r, []).append(doc)

            for retriever_name, docs in retrievers.items():
                with st.expander(f"📦 Retriever: {retriever_name} ({len(docs)} docs)"):
                    for doc in docs:
                        st.write(f"- **{doc.source}** (score: {doc.score:.4f})")
                        st.caption(doc.content[:200])

        if result.reranked_documents:
            st.subheader("🏆 Reranked Results")
            for i, doc in enumerate(result.reranked_documents, 1):
                score_color = "🟢" if doc.score > 0.7 else "🟡" if doc.score > 0.4 else "🔴"
                st.write(f"{score_color} **[{i}] {doc.source}** — `{doc.score:.4f}`")
                st.caption(doc.content[:200])
