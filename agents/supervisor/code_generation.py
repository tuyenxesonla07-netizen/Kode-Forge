# agents/supervisor/code_generation.py

"""
Codex Supervisor — code generation with AST validation.

Handles:
  - Primary generation via ClaudeCodeExecutor (real LLM)
  - Inline fallback with ThreadPoolExecutor timeout control
  - AST validation + retry on syntax error
  - Interface consistency check
"""

import ast
import concurrent.futures
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def generate_code(
    module_spec: Dict[str, Any],
    llm_provider: Any,
    module_name: str,
    timeout: float = 120.0,
) -> str:
    """Generate production-ready Python code using the real LLM. Validates with ast.parse()."""
    try:
        from agents.supervisor.agent_executor import ClaudeCodeExecutor

        executor = ClaudeCodeExecutor(llm_provider=llm_provider)
        code = executor.generate_code(
            spec=module_spec, module_name=module_name, timeout=timeout,
        )
        return code
    except (ImportError, RuntimeError) as e:
        logger.warning("[Supervisor] ClaudeCodeExecutor not available (%s), falling back to inline", e)
        return _generate_code_inline(module_spec, llm_provider, module_name, timeout=timeout)


def _generate_code_inline(
    module_spec: Dict[str, Any],
    llm_provider: Any,
    module_name: str,
    timeout: float = 120.0,
) -> str:
    """Inline code generation fallback with AST validation + retry + interface check."""
    try:
        components = module_spec.get("components", [])
        interfaces = module_spec.get("interfaces", [])
        acceptance_criteria = module_spec.get("acceptance_criteria", [])

        spec_lines = []
        for comp in components:
            if isinstance(comp, dict):
                spec_lines.append(f'- {comp.get("name", "?")} ({comp.get("type", "?")}): {comp.get("description", "")}')
            else:
                spec_lines.append(f"- {comp}")

        interface_lines = []
        for iface in interfaces:
            if isinstance(iface, dict):
                interface_lines.append(f'- {iface.get("name", "?")} {iface.get("method", "?")} {iface.get("path", "?")}')
            else:
                interface_lines.append(f"- {iface}")

        criteria_lines = [f"- {c}" for c in acceptance_criteria]

        prompt_parts = [
            f"You are a senior Python developer. Generate production-ready code for the '{module_name}' module.",
            "",
            "## Module Specification",
            "Components:",
        ] + spec_lines + [
            "",
            "Interfaces:",
        ] + interface_lines + [
            "",
            "Acceptance Criteria:",
        ] + criteria_lines + [
            "",
            "## Requirements",
            "- Valid, parseable Python 3.12+ code with type hints and docstrings",
            "- Follow Google Python Style Guide",
            "- Use FastAPI framework",
            "- Implement ALL acceptance criteria listed above",
            "- Include proper error handling and logging",
            "- Output ONLY the Python code. No markdown fences, no explanation.",
        ]
        prompt = "\n".join(prompt_parts)

        system_prompt = (
            "You are an expert Python code generator. "
            "Generate complete, runnable Python code. "
            "Output ONLY raw Python code -- no markdown, no explanation, no code fences."
        )

        def _call_llm(prompt_text: str, sys_prompt_text: str) -> Any:
            return llm_provider.complete(
                prompt=prompt_text,
                system_prompt=sys_prompt_text,
                output_format="text",
                max_tokens=8192,
                temperature=0.2,
            )

        current_timeout = timeout
        for attempt in range(1, 3):  # up to 2 attempts
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_call_llm, prompt, system_prompt)
                    response = future.result(timeout=current_timeout)
            except concurrent.futures.TimeoutError:
                logger.warning("[Supervisor] LLM timeout for %s (attempt %d / %d)",
                               module_name, attempt, 2)
                if attempt == 1:
                    current_timeout = min(current_timeout * 2.5, 300.0)
                    continue
                return ""
            except Exception as exc:
                logger.error("[Supervisor] LLM call failed for %s (attempt %d): %s",
                             module_name, attempt, exc)
                return ""

            if not response.success or not response.content:
                logger.warning("[Supervisor] LLM generation failed for %s (attempt %d): %s",
                               module_name, attempt, response.error)
                return ""

            code = response.content.strip()
            if code.startswith("```"):
                parts = code.split("\n", 1)
                if len(parts) > 1:
                    code = parts[1]
                else:
                    code = code[3:]
                if code.endswith("```"):
                    code = code[:-3]
                code = code.strip()

            try:
                ast.parse(code)
            except SyntaxError as e:
                logger.warning(
                    "[Supervisor] AST validation failed for %s (attempt %d): %s",
                    module_name, attempt, e,
                )
                if attempt == 1:
                    prompt = (
                        f"Your previous code had a syntax error:\n"
                        f"  {e}\n\n"
                        f"Fix it. Output ONLY corrected Python code "
                        f"with no markdown fences.\n\n"
                        f"Original request:\n{prompt}"
                    )
                    system_prompt = (
                        "Fix the syntax error and output ONLY corrected Python code. "
                        "No markdown, no explanation, no code fences."
                    )
                    continue
                return ""

            # Interface consistency check
            missing_names = []
            code_lower = code.lower()
            for iface in interfaces:
                name = iface.get("name", "") if isinstance(iface, dict) else str(iface)
                if name and name.lower() not in code_lower:
                    missing_names.append(name)
            if missing_names and attempt == 1:
                logger.warning("[Supervisor] Missing interfaces for %s: %s", module_name, missing_names)
                prompt = (
                    f"Your code is missing these required interfaces: {missing_names}\n\n"
                    f"Add them. Output ONLY corrected Python code.\n\n"
                    f"Original request:\n{prompt}"
                )
                continue

            logger.info("[Supervisor] Generated %d lines for %s (attempt %d)",
                        code.count("\n") + 1, module_name, attempt)
            return code

        return ""

    except Exception as exc:
        logger.error("[Supervisor] Code gen error for %s: %s", module_name, exc)
        return ""
