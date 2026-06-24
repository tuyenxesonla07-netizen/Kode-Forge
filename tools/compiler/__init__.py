# tools/compiler/__init__.py

"""
Pipeline Compiler — 核心编译器模块

编译器读 Schema，自动推导：
  1. 上下文注入策略（ContextDeriver）
  2. Prompt 模板（PromptTemplateGenerator）
  3. 修复指令模板（FixInstructionDeriver）
  4. 依赖图（DependencyGraphBuilder）
  5. 质量门禁配置（QualityGateGenerator）
"""

from tools.compiler.pipeline_compiler import PipelineCompiler
from tools.compiler.context_deriver import ContextDeriver
from tools.compiler.prompt_generator import PromptTemplateGenerator
from tools.compiler.fix_deriver import FixInstructionDeriver
from tools.compiler.dependency_graph import DependencyGraphBuilder
from tools.compiler.quality_gate_gen import QualityGateGenerator

__all__ = [
    "PipelineCompiler",
    "ContextDeriver",
    "PromptTemplateGenerator",
    "FixInstructionDeriver",
    "DependencyGraphBuilder",
    "QualityGateGenerator",
]
