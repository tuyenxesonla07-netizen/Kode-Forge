# tools/langgraph_adapter/__init__.py

"""
LangGraph 后端适配器 — 将 CompiledPipeline 编译为 LangGraph StateGraph。

提供与 WorkflowEngine 平行的执行路径：
- LangGraphBackend.build(compiled) → CompiledStateGraph
- LangGraphBackend.execute(graph, initial_state) → LangGraphState

全程 lazy import（langgraph 为可选依赖，未安装时给出安装提示）。

用法:
    from tools.langgraph_adapter import LangGraphBackend

    backend = LangGraphBackend()
    graph = backend.build(compiled_pipeline)
    result = await backend.execute(graph, {"query": "..."})
"""

from tools.langgraph_adapter.state import LangGraphState

__all__ = [
    "LangGraphState",
    "LangGraphBackend",
]

# Lazy import to avoid hard dependency
try:
    from tools.langgraph_adapter.graph_builder import LangGraphBackend
except ImportError:
    # langgraph 未安装时，提供友好的错误提示
    class LangGraphBackend:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise ImportError(
                "langgraph is required for LangGraphBackend. "
                "Install with: pip install langgraph"
            )
