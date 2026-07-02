# tools/cli/model.py
"""Model management sub-commands: list, switch, test."""

from __future__ import annotations

import argparse


def cmd_model_list(args: argparse.Namespace) -> None:
    from tools.llm.model_switcher import ModelRegistry

    registry = ModelRegistry()
    entries = registry.list_display()

    print("\n" + "=" * 60)
    print("  CC Switch — Model Registry")
    print("=" * 60)

    for entry in entries:
        key_status = "✓" if entry["has_api_key"] else "✗"
        print(f"\n  [{key_status}] {entry['display_name']}")
        print(f"      Provider: {entry['name']}")
        print(f"      Default:  {entry['default_model']}")
        print(f"      Models:   {', '.join(entry['models'][:3])}")
        if entry["notes"]:
            print(f"      Notes:    {entry['notes']}")

    print("\n" + "-" * 60)
    print("  ✓ = API key detected  ✗ = no key")
    print("=" * 60)


def cmd_model_switch(args: argparse.Namespace) -> None:
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)
    model = getattr(args, "model", None)

    if switcher.switch(args.provider, model):
        print(f"✓ Switched to {args.provider}/{model or 'default'}")
    else:
        print(f"✗ Unknown provider: {args.provider}")
        print(f"  Available: {', '.join(registry.list_providers())}")


def cmd_model_test(args: argparse.Namespace) -> None:
    from tools.llm.model_switcher import ModelSwitcher, ModelRegistry

    registry = ModelRegistry()
    switcher = ModelSwitcher(registry)

    if hasattr(args, "provider") and args.provider:
        results = [switcher.test_provider(args.provider)]
    else:
        results = switcher.test_all()

    print("\n" + "=" * 60)
    print("  CC Switch — Connectivity Test")
    print("=" * 60)

    for r in results:
        status_icon = "✓" if r["status"] == "ok" else "✗"
        latency = r.get("latency_ms", 0)
        print(f"\n  [{status_icon}] {r['provider']}/{r['model']}")
        print(f"      Status:  {r['status']}")
        if latency:
            print(f"      Latency: {latency:.0f}ms")
        if r.get("error"):
            print(f"      Error:   {r['error'][:100]}")
        if r.get("env_var"):
            print(f"      Set:     export {r['env_var']}=...")

    print("\n" + "=" * 60)
