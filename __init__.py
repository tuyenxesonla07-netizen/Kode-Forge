# Claude-Codex Multi-Agent Pipeline
# Schema-First Multi-Agent Development Pipeline
#
# 3-Layer API:
#
#   Layer 1 — One-liner:
#     from agents.pipeline import generate_code
#     result = generate_code("Build auth module with JWT")
#
#   Layer 2 — Pipeline class:
#     from agents.pipeline import Pipeline
#     pipe = Pipeline(config_dir="config", llm_backend="mock")
#     result = pipe.run("Build auth module with JWT")
#
#   Layer 3 — Full multi-agent system:
#     from agents.pipeline import ClaudeCodexMultiAgent
#     pipeline = ClaudeCodexMultiAgent(config_dir="config", llm_backend="anthropic")
#
# For all other imports, use the submodule path:
#     from tools.compiler import PipelineCompiler
#     from tools.llm import create_llm_provider
#     from agents.supervisor import CodexSupervisor
#     from tools.rag import RAGPipeline

__version__ = "0.1.0"

__all__ = [
    # Layer 1+2 (lazy — imported on access)
    "generate_code",
    "Pipeline",
    # Layer 3 (lazy — imported on access)
    "ClaudeCodexMultiAgent",
    "CodexSupervisor",
    "Requirement",
    "ModuleTask",
    # Agent execution internals (advanced users)
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
]


# ── Lazy imports (avoid heavy import at `import` time) ──────────────────
import importlib
import sys
from types import ModuleType
from typing import Any


class _LazyModule(ModuleType):
    """Proxy that defers heavy imports until first attribute access."""

    _LAZY_NAMES = {
        "generate_code": ("agents.pipeline", "generate_code"),
        "Pipeline": ("agents.pipeline", "Pipeline"),
        "ClaudeCodexMultiAgent": ("agents.supervisor", "ClaudeCodexMultiAgent"),
        "CodexSupervisor": ("agents.supervisor", "CodexSupervisor"),
        "Requirement": ("agents.supervisor", "Requirement"),
        "ModuleTask": ("agents.supervisor", "ModuleTask"),
        "ClaudeCodeExecutor": ("agents.supervisor.agent_executor", "ClaudeCodeExecutor"),
        "ExecutionBackend": ("agents.supervisor.agent_executor", "ExecutionBackend"),
        "TaskSpec": ("agents.supervisor.agent_executor", "TaskSpec"),
        "TaskResult": ("agents.supervisor.agent_executor", "TaskResult"),
        "MergeCoordinator": ("agents.supervisor.agent_executor", "MergeCoordinator"),
        "ComputerUseOrchestrator": ("agents.supervisor.agent_executor", "ComputerUseOrchestrator"),
        "ComputerUseReport": ("agents.supervisor.agent_executor", "ComputerUseReport"),
        "ComputerUseBackend": ("agents.supervisor.agent_executor", "ComputerUseBackend"),
        "CodexComputerUseBackend": ("agents.supervisor.agent_executor", "CodexComputerUseBackend"),
        "ClaudeComputerUseBackend": ("agents.supervisor.agent_executor", "ClaudeComputerUseBackend"),
        "create_computer_use_backend": ("agents.supervisor.agent_executor", "create_computer_use_backend"),
    }

    def __getattr__(self, name: str) -> Any:
        if name in self._LAZY_NAMES:
            module_path, attr_name = self._LAZY_NAMES[name]
            mod = importlib.import_module(module_path)
            obj = getattr(mod, attr_name)
            # Cache on this proxy
            self.__dict__[name] = obj
            return obj
        raise AttributeError(name)


# Replace this module with the lazy proxy
_mod = _LazyModule(__name__)
try:
    _mod.__dict__.update(sys.modules[__name__].__dict__)
except KeyError:
    # Module not yet in sys.modules (e.g. loaded via importlib.util.spec_from_file_location)
    pass
_mod.__dict__.pop("_LazyModule", None)
_mod.__dict__.pop("importlib", None)
_mod.__dict__.pop("sys", None)
_mod.__dict__.pop("ModuleType", None)
_mod.__dict__.pop("Any", None)
sys.modules[__name__] = _mod
