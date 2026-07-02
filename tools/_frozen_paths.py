"""
tools/_frozen_paths.py
Centralized path resolution that works for both source and PyInstaller onedir.

In a frozen PyInstaller onedir bundle, __file__ points inside dist/kodeforge/_internal/.
The project root can be reliably reached via sys._MEIPASS (frozen) or by walking
up from this file's location (source).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def is_frozen() -> bool:
    """Return True when running from a PyInstaller frozen executable."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """
    Return the project root directory.

    Frozen  : sys._MEIPASS. When PyInstaller puts extra data at _internal/
              (the default in onedir mode), prefer that path since bundled
              files (config/, gui/) live there.
    Source  : two levels up from this file (tools/_frozen_paths.py → project root).
    """
    if is_frozen():
        internal = Path(sys._MEIPASS) / "_internal"
        if (internal / "config").exists() or (internal / "gui").exists():
            return internal
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """
    Return the directory in which non-Python asset files live.

    Frozen  : PyInstaller onedir by default places --add-data files at
              <name>/_internal/ (unless --contents-directory . is used).
              Try _internal first, then fall back to sys._MEIPASS.
    Source  : project root.
    """
    if is_frozen():
        internal = Path(sys._MEIPASS) / "_internal"
        if (internal / "config").exists() or (internal / "gui").exists():
            return internal
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Directory where writable runtime data lives (persistent DB, logs)."""
    if is_frozen():
        # Write next to the exe, NOT inside _internal/
        exe_dir = Path(sys.executable).parent
        d = exe_dir / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = project_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_dir() -> Path:
    """Directory containing agents.yaml / pipeline.yaml / schemas/."""
    return bundle_dir() / "config"


def plugins_dir() -> Path:
    """Directory containing custom skill plugins."""
    return bundle_dir() / "plugins"


def resolve_path(relpath: str) -> Path:
    """
    Resolve a project-relative path (e.g. "config/pipeline.yaml") to a filesystem path.
    Works for source-tree and frozen-runtime invocations.
    """
    return bundle_dir() / relpath


def db_path(default: Optional[str] = None) -> str:
    """Default SQLite database path — always writeable next to the exe."""
    if default is not None:
        return default
    return str(data_dir() / "stores.db")
