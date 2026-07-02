# tools/cli/__init__.py
"""CLI sub-command handlers.

Each module in this package corresponds to a top-level cc command group.
All functions follow the signature: fn(args: argparse.Namespace) -> None.
"""

from tools.cli.model import cmd_model_list, cmd_model_switch, cmd_model_test
from tools.cli.rag import cmd_query, cmd_search
from tools.cli.pipeline import cmd_run, cmd_serve, cmd_eval
from tools.cli.skills import cmd_skills
from tools.cli.system import cmd_status, cmd_validate, cmd_gui

__all__ = [
    "cmd_model_list", "cmd_model_switch", "cmd_model_test",
    "cmd_query", "cmd_search",
    "cmd_run", "cmd_serve", "cmd_eval",
    "cmd_skills",
    "cmd_status", "cmd_validate", "cmd_gui",
]
