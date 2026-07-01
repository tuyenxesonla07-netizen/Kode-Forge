# tools/cli/system.py
"""System sub-commands: status, validate, gui."""

from __future__ import annotations

import argparse
import os
import sys


def cmd_status(args: argparse.Namespace) -> None:
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)
    status = switcher.status_display()

    print("\n" + "=" * 60)
    print("  CC Status — System Overview")
    print("=" * 60)
    print(f"\n  Current Model: {status['current_provider']}/{status['current_model']}")
    print(f"  Providers:     {len(status['available_providers'])}")
    print("\n  API Keys:")
    for name, has_key in status["has_api_key"].items():
        icon = "✓" if has_key else "✗"
        print(f"    [{icon}] {name}")
    print("=" * 60)


def cmd_validate(args: argparse.Namespace) -> None:
    import io
    from tools.schema_validator import validate_all

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        ok = validate_all("config")
    finally:
        sys.stdout = old_stdout

    output = buf.getvalue()
    print(output)
    if not ok:
        sys.exit(1)


def cmd_gui(args: argparse.Namespace) -> None:
    import subprocess

    gui_path = os.path.join(os.path.dirname(__file__), "..", "..", "gui", "app.py")
    gui_path = os.path.normpath(gui_path)

    if not os.path.exists(gui_path):
        print(f"  ✗ GUI not found: {gui_path}")
        return

    port = getattr(args, "port", 8501)
    print(f"\n  CC GUI — Starting Streamlit...")
    print(f"  http://localhost:{port}\n")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", gui_path, "--server.port", str(port)],
        check=True,
    )
