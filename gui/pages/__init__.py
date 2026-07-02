# gui/pages/__init__.py

"""GUI page modules — one per tab."""

from gui.pages.query import render as render_query
from gui.pages.search import render as render_search
from gui.pages.workflow import render as render_workflow
from gui.pages.skills import render as render_skills
from gui.pages.eval import render as render_eval
from gui.pages.status import render as render_status

__all__ = [
    "render_query",
    "render_search",
    "render_workflow",
    "render_skills",
    "render_eval",
    "render_status",
]
