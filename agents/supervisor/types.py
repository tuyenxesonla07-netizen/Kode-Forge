# agents/supervisor/types.py

"""
Codex Supervisor — shared data types.

This module defines the dataclasses used across the supervisor sub-modules.
Keeping them separate avoids circular imports and gives a single source of
truth for the supervisor's public data contract.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Requirement:
    """Structured requirement extracted from natural-language input."""
    functional_modules: List[str] = field(default_factory=list)
    non_functional: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    priority: str = "medium"
    raw_text: str = ""


@dataclass
class ModuleTask:
    """A single module task dispatched to an expert agent."""
    module: str
    priority: int = 1
    dependencies: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompiledPipeline:
    """Compiled pipeline configuration produced by PipelineCompiler."""
    context_strategies: Dict[str, Any] = field(default_factory=dict)
    implementation_order: List[str] = field(default_factory=list)
    fix_templates: Dict[str, Any] = field(default_factory=dict)
    quality_gates: List[Dict[str, Any]] = field(default_factory=list)
