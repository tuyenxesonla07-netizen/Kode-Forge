# gui/pages/skills.py

"""Skills tab — Skill browser and publishing guide."""

import streamlit as st

from gui.state import _get_skill_manager


def render():
    """Render the Skills tab."""
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
