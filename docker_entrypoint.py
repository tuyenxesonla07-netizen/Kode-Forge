#!/usr/bin/env python3
"""
Docker entrypoint — routes CMD to the correct action.

Usage:
    docker run <image>                  # default: eval
    docker run <image> eval             # run eval suite
    docker run <image> eval --json      # eval with JSON output
    docker run <image> test             # run test suite
    docker run <image> lint             # ruff lint check
    docker run <image> serve            # start MCP server
    docker run <image> serve --port 8080
    docker run <image> shell            # interactive bash
    docker run <image> pipeline "Build auth module"
"""

import os
import subprocess
import sys


def run_eval(args):
    """Run eval suite as a subprocess (clean argparse)."""
    env = os.environ.copy()
    env.setdefault("RUFF_CACHE_DIR", "/tmp/ruff_cache")
    cmd = [sys.executable, "-m", "tools.eval"] + args
    return subprocess.call(cmd, env=env)


def run_test(args):
    """Run pytest as a subprocess."""
    env = os.environ.copy()
    env.setdefault("RUFF_CACHE_DIR", "/tmp/ruff_cache")
    env.setdefault("PYTEST_CACHE_DIR", "/tmp/pytest_cache")
    cmd = [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"] + args
    return subprocess.call(cmd, env=env)


def run_lint(args):
    """Run ruff as a subprocess."""
    env = os.environ.copy()
    env.setdefault("RUFF_CACHE_DIR", "/tmp/ruff_cache")
    cmd = ["ruff", "check", "tools/", "agents/", "tests/", "--ignore", "E501"] + args
    return subprocess.call(cmd, env=env)


def run_serve(args):
    """Start MCP server."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--backend", default="mock", choices=["mock", "anthropic"])
    parsed, _ = parser.parse_known_args(args)

    os.environ.setdefault("LLM_BACKEND", parsed.backend)
    os.environ.setdefault("MCP_HOST", parsed.host)
    os.environ.setdefault("MCP_PORT", str(parsed.port))

    from __init__ import ClaudeCodexMultiAgent
    import asyncio

    pipeline = ClaudeCodexMultiAgent(llm_backend=parsed.backend)
    server = pipeline.get_mcp_server(host=parsed.host, port=parsed.port)
    print(f"[serve] MCP server starting on {parsed.host}:{parsed.port}")
    asyncio.run(server.start_sse())


def run_pipeline(args):
    """Run full pipeline with custom input."""
    user_input = args[0] if args else "Build authentication module with JWT"
    from __init__ import ClaudeCodexMultiAgent
    import json

    pipeline = ClaudeCodexMultiAgent(llm_backend="mock")
    result = pipeline.run_full_pipeline(user_input)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def run_shell():
    """Interactive shell."""
    shell = os.environ.get("SHELL", "/bin/bash")
    return subprocess.call([shell])


def main():
    args = sys.argv[1:]

    if not args:
        args = ["eval"]

    command = args[0]
    rest = args[1:]

    if command == "eval":
        sys.exit(run_eval(rest))
    elif command == "test":
        sys.exit(run_test(rest))
    elif command == "lint":
        sys.exit(run_lint(rest))
    elif command == "serve":
        run_serve(rest)
    elif command == "pipeline":
        run_pipeline(rest)
    elif command == "shell":
        sys.exit(run_shell())
    else:
        # Pass-through to python or any other command
        sys.exit(subprocess.call([command] + rest))


if __name__ == "__main__":
    main()
