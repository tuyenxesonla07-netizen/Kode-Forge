"""CC Init — Project scaffold generator.

Usage:
    cc init <project_name> [--path <dir>]

Generates a new project scaffold with:
    - config/schemas/<module>_input.json + <module>_output.json
    - config/agents.yaml
    - config/pipeline.yaml
    - modules/<module>/ (empty implementation directory)

Templates are generic — users define their own modules.
"""

from __future__ import annotations

import argparse
import json
import os
import textwrap
from typing import List


# ── Templates ──────────────────────────────────────────────────────────────

def _make_input_schema(module_name: str) -> dict:
    """Generate a generic input schema for a module."""
    display = module_name.replace("_", " ").title()
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{display}ModuleInput",
        "description": f"Input schema for {display} module expert agent",
        "type": "object",
        "required": ["requirement", "constraints"],
        "properties": {
            "requirement": {
                "type": "string",
                "description": "Requirement description for this module",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Technical constraints list",
            },
            "dependencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of other modules this depends on",
            },
            "tech_stack": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "default": "Python 3.12"},
                    "framework": {"type": "string", "default": "FastAPI"},
                    "database": {"type": "string", "default": "PostgreSQL"},
                },
            },
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Acceptance criteria for generated code",
            },
        },
    }


def _make_output_schema(module_name: str) -> dict:
    """Generate a generic output schema for a module."""
    display = module_name.replace("_", " ").title()
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{display}ModuleOutput",
        "description": f"Output schema for {display} module expert agent",
        "type": "object",
        "required": ["module_spec", "confidence"],
        "properties": {
            "module_spec": {
                "type": "object",
                "required": ["components", "interfaces"],
                "properties": {
                    "components": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "type", "description"],
                            "properties": {
                                "name": {"type": "string"},
                                "type": {
                                    "enum": [
                                        "service", "model", "middleware",
                                        "route", "util", "config",
                                    ],
                                },
                                "description": {"type": "string"},
                                "methods": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                    "interfaces": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "method"],
                            "properties": {
                                "name": {"type": "string"},
                                "method": {"type": "string"},
                                "path": {"type": "string"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "reasoning": {
                "type": "string",
                "description": "Design reasoning",
            },
        },
    }


def _make_agents_yaml(modules: List[str]) -> str:
    """Generate agents.yaml content."""
    lines = [
        "# Agent Registry — Auto-discovered at runtime",
        "# Each module in schemas/ gets a matching expert agent entry",
        "",
        "agents:",
    ]
    for module in modules:
        display = module.replace("_", " ").title()
        short = module.split("_")[0]  # e.g., "data" from "data_processing"
        lines.extend([
            f"  expert_{module}:",
            f"    name: {display} Expert",
            f"    capabilities: [{module}]",
            f"    depends_on: []",
            f"    description: Auto-discovered expert for {display} module",
        ])
    lines.extend([
        "",
        "settings:",
        "  auto_discover: true",
        "  max_parallel_agents: 3",
        "  skill_injection: true",
    ])
    return "\n".join(lines) + "\n"


def _make_pipeline_yaml() -> str:
    """Generate pipeline.yaml content."""
    return textwrap.dedent("""\
        # Pipeline Configuration
        pipeline:
          name: "cc-pipeline"
          version: "1.0.0"
          description: "Schema-first multi-agent compilation pipeline"

        quality_gates:
          - name: "syntax"
            description: "Generated code must be valid Python"
            required: true
          - name: "security"
            description: "No dangerous imports or patterns"
            required: true
          - name: "interfaces"
            description: "All declared interfaces must be implemented"
            required: false

        retry_policy:
          max_retries: 3
          backoff_factor: 2.0
          initial_delay_seconds: 1.0

        fix:
          max_iterations: 3
          convergence_threshold: 0.85
          strategy: "targeted"  # targeted | full

        compilation:
          dependency_resolution: "topological"
          parallel_groups: "auto"
          context_derivation: "schema_based"
    """) + "\n"


def _make_readme(project_name: str, modules: List[str]) -> str:
    """Generate project README."""
    module_list = "\n".join(
        f"  - `{m}` — {m.replace('_', ' ').title()} module"
        for m in modules
    )
    return textwrap.dedent(f"""\
        # {project_name}

        Generated by `cc init` — KodeForge scaffold.

        ## Modules

        {module_list}

        ## Quick Start

        ```bash
        # Install dependencies
        pip install -e ".[dev]"

        # Run pipeline (requires LLM API key)
        cc run "Implement the core logic for {modules[0].replace('_', ' ')}"

        # Or start API server
        cc serve --port 8080
        ```

        ## Customize

        1. Edit `config/schemas/` to define your module interfaces
        2. Add/remove modules by creating/deleting schema pairs
        3. Run `cc init . --modules <new_module>` to add more modules

        ## Architecture

        ```
        Schema (JSON) → PipelineCompiler → Parallel Expert Agents → Code → Review
        ```
    """) + "\n"


# ── Scaffold generation ────────────────────────────────────────────────────

DEFAULT_MODULES = ["authentication", "data_processing", "api_integration"]


def scaffold(project_name: str, path: str = ".", modules: List[str] | None = None) -> str:
    """Generate a new project scaffold.

    Args:
        project_name: Name of the project (used in README and config)
        path: Target directory (default: current directory)
        modules: List of module names (default: 3 demo modules)

    Returns:
        Absolute path to the created project directory
    """
    if modules is None:
        modules = DEFAULT_MODULES

    project_dir = os.path.normpath(os.path.join(os.path.abspath(path), project_name))
    if os.path.exists(project_dir):
        raise FileExistsError(f"Directory already exists: {project_dir}")

    # Create directory structure
    os.makedirs(os.path.join(project_dir, "config", "schemas"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "modules"), exist_ok=True)

    # Generate schemas
    for module in modules:
        input_path = os.path.join(project_dir, "config", "schemas", f"{module}_input.json")
        output_path = os.path.join(project_dir, "config", "schemas", f"{module}_output.json")

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(_make_input_schema(module), f, indent=2, ensure_ascii=False)
            f.write("\n")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(_make_output_schema(module), f, indent=2, ensure_ascii=False)
            f.write("\n")

    # Generate config files
    with open(os.path.join(project_dir, "config", "agents.yaml"), "w", encoding="utf-8") as f:
        f.write(_make_agents_yaml(modules))

    with open(os.path.join(project_dir, "config", "pipeline.yaml"), "w", encoding="utf-8") as f:
        f.write(_make_pipeline_yaml())

    # Generate README
    with open(os.path.join(project_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(_make_readme(project_name, modules))

    return os.path.abspath(project_dir)


# ── CLI integration ────────────────────────────────────────────────────────

def _cmd_init(args: argparse.Namespace) -> None:
    """Handle `cc init` command."""
    project_name = args.project_name
    path = getattr(args, "path", ".")
    modules_str = getattr(args, "modules", None)
    modules = modules_str.split(",") if modules_str else None

    try:
        result = scaffold(project_name, path, modules)
        print(f"\n  [OK] Project scaffold created: {result}")
        print(f"\n  Next steps:")
        print(f"    cd {project_name}")
        print(f"    pip install -e '.[dev]'")
        print(f"    cc run 'Describe your first module requirement'")
        print(f"    cc serve --port 8080")
    except FileExistsError as e:
        print(f"  [ERROR] {e}")
    except Exception as e:
        print(f"  [ERROR] Failed to create scaffold: {e}")


def add_init_subparser(subparsers) -> None:
    """Add the init subparser to the CLI argument parser."""
    init_parser = subparsers.add_parser(
        "init",
        help="Create a new project scaffold",
        description="Generate a new project with module schemas and config",
    )
    init_parser.add_argument(
        "project_name",
        help="Name of the new project (used as directory name)",
    )
    init_parser.add_argument(
        "--path",
        default=".",
        help="Parent directory (default: current directory)",
    )
    init_parser.add_argument(
        "--modules",
        default=None,
        help="Comma-separated module names (default: authentication,data_processing,api_integration)",
    )
