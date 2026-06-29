# agents/supervisor/agent_executor.py
"""
Agent execution layer — ClaudeCodeExecutor and supporting abstractions.

This module provides the ``ClaudeCodeExecutor`` class used by the
``CodexSupervisor`` to generate Python code via an LLM provider.  It also
defines the ``ExecutionBackend`` abstract base, ``TaskSpec`` dataclass, and
the ``MergeCoordinator`` / ``ComputerUseOrchestrator`` helpers that the
supervisor imports.

Public API
----------
- :class:`ClaudeCodeExecutor`   — high-level code generator
- :class:`ExecutionBackend`     — abstract backend interface
- :class:`TaskSpec`             — task descriptor
- :class:`MergeCoordinator`     — file-level conflict resolution
- :class:`ComputerUseOrchestrator` — post-generation verification
- :func:`create_computer_use_backend` — factory
"""

from __future__ import annotations

import ast
import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ClaudeCodeExecutor
# ---------------------------------------------------------------------------

class ClaudeCodeExecutor:
    """
    Generate production-ready Python code for a module using an LLM provider.

    Parameters
    ----------
    llm_provider:
        Any object that exposes a ``complete(prompt, system_prompt, ...)``
        method returning an ``LLMResponse`` (or compatible ``.content`` /
        ``.success`` / ``.error`` attributes).
    max_tokens:
        Token budget for a single generation call.
    temperature:
        Sampling temperature (lower → more deterministic).
    """

    def __init__(
        self,
        llm_provider: Any,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ):
        self._provider = llm_provider
        self._max_tokens = max_tokens
        self._temperature = temperature

    # -- public interface ---------------------------------------------------

    def generate_code(
        self,
        spec: Dict[str, Any],
        module_name: str,
        timeout: float = 120.0,
    ) -> str:
        """
        Generate Python code for *module_name* based on *spec*.

        Returns the generated code as a string (empty string on failure).
        The code is validated with :func:`ast.parse` before being returned.
        If AST validation fails, retries once with the error context.

        Args:
            spec: Module specification (components, interfaces, acceptance_criteria).
            module_name: Name of the module to generate code for.
            timeout: Max seconds per LLM call attempt.
        """
        prompt = self._build_prompt(spec, module_name)
        system_prompt = (
            "You are an expert Python code generator. "
            "Generate complete, runnable Python code. "
            "Output ONLY raw Python code -- no markdown, no explanation, "
            "no code fences."
        )

        for attempt in range(1, 3):  # up to 2 attempts
            try:
                response = self._provider_complete_with_timeout(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning(
                    "[ClaudeCodeExecutor] Timeout for %s (attempt %d / %d)",
                    module_name, attempt, 2,
                )
                if attempt == 1:
                    timeout = min(timeout * 2.5, 300.0)  # extend timeout for retry
                    continue
                return ""
            except Exception as exc:
                logger.error(
                    "[ClaudeCodeExecutor] LLM call failed for %s (attempt %d): %s",
                    module_name, attempt, exc,
                )
                return ""

            if not response.success or not response.content:
                logger.warning(
                    "[ClaudeCodeExecutor] Generation failed for %s (attempt %d): %s",
                    module_name, attempt, response.error or "Empty response",
                )
                return ""

            code = self._strip_markdown_fences(response.content)

            # AST validation
            try:
                ast.parse(code)
            except SyntaxError as e:
                logger.warning(
                    "[ClaudeCodeExecutor] AST validation failed for %s (attempt %d): %s "
                    "(response length: %d)",
                    module_name, attempt, e, len(response.content or ""),
                )
                if attempt == 1:
                    # Retry: prepend error context to prompt
                    prompt = (
                        f"Your previous code had a syntax error:\n"
                        f"  {e}\n\n"
                        f"Please fix it. Output ONLY corrected Python code "
                        f"with no markdown fences.\n\n"
                        f"Original request:\n{prompt}"
                    )
                    system_prompt = (
                        "You are an expert Python code generator. "
                        "Fix the syntax error and output ONLY corrected Python code. "
                        "No markdown, no explanation, no code fences."
                    )
                    continue
                return ""

            # Interface consistency check
            missing = self._check_interface_consistency(code, spec, module_name)
            if missing and attempt == 1:
                logger.warning(
                    "[ClaudeCodeExecutor] Missing interfaces for %s: %s (attempt %d)",
                    module_name, missing, attempt,
                )
                prompt = (
                    f"Your code is missing these required interfaces: {missing}\n\n"
                    f"Please add them. Output ONLY corrected Python code.\n\n"
                    f"Original request:\n{prompt}"
                )
                continue

            logger.info(
                "[ClaudeCodeExecutor] Generated %d lines for %s (attempt %d)",
                code.count("\n") + 1,
                module_name,
                attempt,
            )
            return code

        return ""

    def _provider_complete_with_timeout(
        self,
        prompt: str,
        system_prompt: str,
        timeout: float,
        **kwargs: Any,
    ) -> Any:
        """Call provider.complete with a hard timeout.

        Uses asyncio.wait_for when possible, otherwise falls back to
        threading-based timeout.
        """
        import concurrent.futures

        def _call():
            return self._provider.complete(
                prompt=prompt,
                system_prompt=system_prompt,
                output_format="text",
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                **kwargs,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"LLM call exceeded {timeout}s timeout"
                )

    @staticmethod
    def _check_interface_consistency(code: str, spec: Dict[str, Any], module_name: str) -> List[str]:
        """Check that all interfaces declared in spec appear in the code.

        Returns a list of missing interface names (empty if all present).
        """
        interfaces = spec.get("interfaces", [])
        if not interfaces:
            return []

        missing: List[str] = []
        code_lower = code.lower()
        for iface in interfaces:
            if isinstance(iface, dict):
                name = iface.get("name", "")
            else:
                name = str(iface)
            if not name:
                continue
            # Check if the interface name appears in the code
            if name.lower() not in code_lower:
                missing.append(name)
        return missing

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _build_prompt(spec: Dict[str, Any], module_name: str) -> str:
        components: List[str] = spec.get("components", [])
        interfaces: List[str] = spec.get("interfaces", [])
        acceptance_criteria: List[str] = spec.get("acceptance_criteria", [])

        spec_lines: List[str] = []
        for comp in components:
            if isinstance(comp, dict):
                spec_lines.append(
                    f'- {comp.get("name", "?")} ({comp.get("type", "?")}): '
                    f'{comp.get("description", "")}'
                )
            else:
                spec_lines.append(f"- {comp}")

        interface_lines: List[str] = []
        for iface in interfaces:
            if isinstance(iface, dict):
                interface_lines.append(
                    f'- {iface.get("name", "!")} {iface.get("method", "!")} '
                    f'{iface.get("path", "!")}'
                )
            else:
                interface_lines.append(f"- {iface}")

        criteria_lines = [f"- {c}" for c in acceptance_criteria]

        prompt_parts = [
            f"You are a senior Python developer. Generate production-ready "
            f"code for the '{module_name}' module.",
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
        return "\n".join(prompt_parts)

    @staticmethod
    def _strip_markdown_fences(raw: str) -> str:
        code = raw.strip()
        if code.startswith("```"):
            parts = code.split("\n", 1)
            code = parts[1] if len(parts) > 1 else code[3:]
            if code.endswith("```"):
                code = code[:-3]
            code = code.strip()
        return code


# ---------------------------------------------------------------------------
# ExecutionBackend (abstract)
# ---------------------------------------------------------------------------

@dataclass
class TaskSpec:
    """Describes a single module code-generation task."""
    module_name: str
    spec: Dict[str, Any]
    requirement: str = ""
    constraints: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result of executing a :class:`TaskSpec`."""
    module_name: str
    success: bool
    code: str = ""
    error: Optional[str] = None


class ExecutionBackend(ABC):
    """Abstract interface for code-generation execution backends."""

    @abstractmethod
    def execute_task(self, task: TaskSpec) -> TaskResult:
        """Execute a single module task and return the result."""

    @abstractmethod
    def get_name(self) -> str:
        """Return a human-readable backend name."""


# ---------------------------------------------------------------------------
# MergeCoordinator (stub)
# ---------------------------------------------------------------------------

class MergeCoordinator:
    """
    Detect and resolve file-level conflicts when multiple modules
    generate code that targets the same file.
    """

    def __init__(self, llm_provider: Any = None):
        self._provider = llm_provider
        self._targets: Dict[str, Dict[str, Any]] = {}
        self._generations: Dict[str, Dict[str, Any]] = {}
        self._resolutions: Dict[str, str] = {}

    # -- registration -------------------------------------------------------

    def register_target(
        self,
        module_name: str,
        file_path: str,
        is_primary: bool = False,
    ) -> None:
        self._targets.setdefault(file_path, {"modules": [], "primary": False})
        self._targets[file_path]["modules"].append(module_name)
        if is_primary:
            self._targets[file_path]["primary"] = True

    def register_generation(
        self,
        file_path: str,
        module_name: str,
        code: str,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        self._generations.setdefault(file_path, [])
        self._generations[file_path].append({
            "module_name": module_name,
            "code": code,
            "success": success,
            "error": error,
        })

    # -- resolution ----------------------------------------------------------

    def resolve_all(self) -> Dict[str, str]:
        """Resolve conflicts and return {file_path: final_code}."""
        for file_path, target in self._targets.items():
            generations = self._generations.get(file_path, [])
            successful = [g for g in generations if g["success"] and g["code"]]
            if successful:
                # Use the primary module's code if available, else first success
                primary = next(
                    (g for g in successful
                     if g["module_name"] in target["modules"]
                     and target.get("primary")),
                    successful[0],
                )
                self._resolutions[file_path] = primary["code"]
            elif generations:
                # All failed — keep empty
                self._resolutions[file_path] = ""
        return dict(self._resolutions)

    def get_resolution_report(self) -> Dict[str, Any]:
        return {
            "resolutions": {
                fp: len(code) for fp, code in self._resolutions.items()
            },
            "files": list(self._targets.keys()),
        }


# ---------------------------------------------------------------------------
# ComputerUseOrchestrator (stub)
# ---------------------------------------------------------------------------

@dataclass
class ComputerUseReport:
    """Result of computer-use verification."""
    verified: bool
    output: str = ""
    fixes_applied: int = 0


class ComputerUseBackend(ABC):
    """Abstract computer-use backend (e.g., Codex, Claude)."""

    name: str = "unknown"
    available: bool = False

    @abstractmethod
    def run(self, code_artifact: Dict[str, str]) -> ComputerUseReport:
        ...


class CodexComputerUseBackend(ComputerUseBackend):
    """Codex-based computer-use backend."""

    name = "codex"
    available = True

    def run(self, code_artifact: Dict[str, str]) -> ComputerUseReport:
        # In production this would call the Codex computer-use API.
        return ComputerUseReport(verified=True, output="Codex backend stub")


class ClaudeComputerUseBackend(ComputerUseBackend):
    """Claude-based computer-use backend."""

    name = "claude"
    available = True

    def run(self, code_artifact: Dict[str, str]) -> ComputerUseReport:
        return ComputerUseReport(verified=True, output="Claude backend stub")


def create_computer_use_backend(
    name: str = "codex",
    workdir: str = ".",
) -> ComputerUseBackend:
    """Factory for computer-use backends."""
    backends = {"codex": CodexComputerUseBackend, "claude": ClaudeComputerUseBackend}
    cls = backends.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown computer-use backend '{name}'. "
            f"Available: {list(backends.keys())}"
        )
    return cls()


class ComputerUseOrchestrator:
    """
    Verify and optionally fix generated code using a computer-use backend.
    """

    def __init__(
        self,
        backend: ComputerUseBackend,
        llm_provider: Any = None,
    ):
        self._backend = backend
        self._provider = llm_provider

    def verify_and_fix(
        self,
        code_artifact: Dict[str, str],
    ) -> ComputerUseReport:
        """Run verification on the generated code artifact."""
        if not self._backend.available:
            return ComputerUseReport(
                verified=False,
                output=f"Backend '{self._backend.name}' not available",
            )
        return self._backend.run(code_artifact)


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "ClaudeCodeExecutor",
    "ExecutionBackend",
    "TaskSpec",
    "TaskResult",
    "MergeCoordinator",
    "ComputerUseOrchestrator",
    "ComputerUseReport",
    "ComputerUseBackend",
    "CodexComputerUseBackend",
    "ClaudeComputerUseBackend",
    "create_computer_use_backend",
    # Code writer
    "CodeWriterConfig",
    "write_code_artifacts",
]

# ---------------------------------------------------------------------------
# Code writer — writes generated code artifacts to disk
# ---------------------------------------------------------------------------


@dataclass
class CodeWriterConfig:
    """代码写入配置"""
    base_dir: str = "src"
    module_template: str = "{base_dir}/{module}/service.py"
    create_init_files: bool = True       # 自动创建 __init__.py
    backup_existing: bool = True         # 备份已有文件为 .bak
    dry_run: bool = False                # 只返回路径，不实际写入


def _resolve_path(module_name: str, config: CodeWriterConfig):
    """根据模板解析模块文件路径"""
    path_str = config.module_template.format(
        base_dir=config.base_dir,
        module=module_name,
    )
    return Path(path_str)


def write_code_artifacts(
    code_artifact: dict,
    config: CodeWriterConfig = None,
) -> list:
    """
    将代码写入文件系统。

    Args:
        code_artifact: {模块名: 代码字符串}
        config: 写入配置（默认使用 CodeWriterConfig()）

    Returns:
        写入的文件路径列表
    """
    if config is None:
        config = CodeWriterConfig()

    written: list = []

    for module_name, code in code_artifact.items():
        if not code or not code.strip():
            logger.warning("[CodeWriter] Skipping empty code for module: %s", module_name)
            continue

        file_path = _resolve_path(module_name, config)

        if config.dry_run:
            logger.info("[CodeWriter] dry_run: would write %s", file_path)
            written.append(str(file_path))
            continue

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if config.backup_existing and file_path.exists():
            backup_path = file_path.with_suffix(
                file_path.suffix + f".{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.bak"
            )
            shutil.copy2(file_path, backup_path)
            logger.info("[CodeWriter] Backed up %s -> %s", file_path, backup_path)

        file_path.write_text(code, encoding="utf-8")
        logger.info("[CodeWriter] Wrote %s (%d lines)", file_path, code.count("\n") + 1)
        written.append(str(file_path))

        if config.create_init_files:
            init_path = file_path.parent / "__init__.py"
            if not init_path.exists():
                init_path.write_text(
                    f'"""Module: {module_name}"""\n',
                    encoding="utf-8",
                )
                logger.info("[CodeWriter] Created %s", init_path)

    return written
