# gui/pages/eval.py

"""Eval tab — Evaluation suite runner."""

import streamlit as st


def render():
    """Render the Eval tab."""
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
