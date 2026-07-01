# tools/cli/skills.py
"""Skills sub-command: list, search, publish, unpublish."""

from __future__ import annotations

import argparse


def cmd_skills(args: argparse.Namespace) -> None:
    subcmd = getattr(args, "skills_command", "list")

    if subcmd == "list":
        _skills_list(args)
    elif subcmd == "search":
        _skills_search(args)
    elif subcmd == "publish":
        _skills_publish(args)
    elif subcmd == "unpublish":
        _skills_unpublish(args)
    else:
        print(f"Unknown skills sub-command: {subcmd}")
        print("  Available: list, search, publish, unpublish")


def _skills_list(args: argparse.Namespace) -> None:
    from tools.plugins import PluginSkillRegistry
    from pathlib import Path

    registry = PluginSkillRegistry(plugins_dir=Path("plugins"))
    registry.load()
    skills = registry.list_skills()

    print(f"\n  CC Skills ({len(skills)} loaded)")
    print("  ─────────────────────────────")
    if not skills:
        print("  No skills found. Add skills to the plugins/skills/ directory.")
    else:
        for skill in skills:
            name = getattr(skill, "name", str(skill))
            desc = getattr(skill, "description", "")[:60]
            print(f"  • {name}: {desc}")
    print()


def _skills_search(args: argparse.Namespace) -> None:
    from tools.plugins import PluginSkillRegistry
    from pathlib import Path

    registry = PluginSkillRegistry(plugins_dir=Path("plugins"))
    registry.load()
    query = getattr(args, "query", "")
    results = registry.select_for(query)

    print(f"\n  Skills matching: {query!r}")
    print("  ─────────────────────────────")
    if not results:
        print("  No matches found.")
    else:
        for skill in results:
            name = getattr(skill, "name", str(skill))
            print(f"  • {name}")
    print()


def _skills_publish(args: argparse.Namespace) -> None:
    import shutil, os
    path = getattr(args, "path", "")
    dest = os.path.join("plugins", "skills", os.path.basename(path))
    if not os.path.exists(path):
        print(f"  ✗ Path not found: {path}")
        return
    shutil.copytree(path, dest, dirs_exist_ok=True)
    print(f"  ✓ Published: {os.path.basename(path)}")


def _skills_unpublish(args: argparse.Namespace) -> None:
    import shutil, os
    name = getattr(args, "name", "")
    dest = os.path.join("plugins", "skills", name)
    if not os.path.exists(dest):
        print(f"  ✗ Skill not found: {name}")
        return
    shutil.rmtree(dest)
    print(f"  ✓ Unpublished: {name}")
