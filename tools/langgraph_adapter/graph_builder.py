# tools/langgraph_adapter/graph_builder.py

"""
图构建器 — 将 CompiledPipeline / Workflow 编译为 LangGraph StateGraph。

Lazy import langgraph：未安装时给出友好提示。
"""

from __future__ import annotations

import logging
from typing import Any

from tools.langgraph_adapter.node_builder import build_node_fn
from tools.langgraph_adapter.state import LangGraphState, initial_state

logger = logging.getLogger(__name__)


class LangGraphBackend:
    """
    LangGraph 后端适配器。

    将本系统的 CompiledPipeline 或 Workflow 编译为 LangGraph CompiledStateGraph，
    提供与 WorkflowEngine 平行的执行路径。

    用法:
        backend = LangGraphBackend()
        graph = backend.build(compiled_pipeline)
        result = await backend.execute(graph, {"query": "..."})
    """

    def __init__(
        self,
        llm_provider=None,
        rag_engine=None,
        tool_registry=None,
        interrupt_before: list[str] | None = None,
        max_fix_iterations: int = 3,
    ) -> None:
        """
        Args:
            llm_provider: LLM 提供者（用于 LLMNode）
            rag_engine: RAG 引擎（用于 RAGNode）
            tool_registry: 工具注册表（用于 ToolNode）
            interrupt_before: 需要在哪些节点前中断（HITL 审批）
            max_fix_iterations: 质量循环最大修复迭代次数
        """
        try:
            from langgraph.graph import END, START, StateGraph
            self._StateGraph = StateGraph
            self._END = END
            self._START = START
        except ImportError:
            raise ImportError(
                "langgraph is required for LangGraphBackend. "
                "Install with: pip install langgraph"
            )

        self._llm_provider = llm_provider
        self._rag_engine = rag_engine
        self._tool_registry = tool_registry
        self._interrupt_before = interrupt_before or []
        self._max_fix_iterations = max_fix_iterations

    def build(
        self,
        workflow: Any,
    ) -> Any:
        """
        将 Workflow 编译为 LangGraph CompiledStateGraph。

        Args:
            workflow: Workflow 实例（包含 nodes 和 edges）

        Returns:
            CompiledStateGraph
        """
        StateGraph = self._StateGraph
        END = self._END
        START = self._START

        # 创建 StateGraph
        graph = StateGraph(LangGraphState)

        # 添加节点
        nodes = workflow.nodes  # Dict[str, WorkflowNode]
        node_fns: dict[str, Any] = {}

        for node_id, node in nodes.items():
            fn = build_node_fn(
                node,
                llm_provider=self._llm_provider,
                rag_engine=self._rag_engine,
                tool_registry=self._tool_registry,
            )
            node_fns[node_id] = fn
            graph.add_node(node_id, fn)

        # 添加边
        edges = workflow.edges  # Dict[str, List[str]]
        for src_id, dst_ids in edges.items():
            for dst_id in dst_ids:
                if dst_id in nodes:
                    graph.add_edge(src_id, dst_id)

        # 处理分支节点（条件边）
        for node_id, node in nodes.items():
            from tools.workflow.nodes import NodeType
            if node.type == NodeType.BRANCH:
                branches = node.config.get("branches", {})
                if branches:
                    path_map: dict[str, str] = {}
                    for branch_name, target_id in branches.items():
                        if target_id and target_id in nodes:
                            path_map[branch_name] = target_id
                    if path_map:
                        graph.add_conditional_edges(
                            node_id,
                            lambda state, _branches=branches: _branches.get("true", "") if state.get("node_outputs", {}).get(node_id, {}).get("branch") == "true" else _branches.get("false", ""),
                            path_map,
                        )

        # 连接 START 到没有入边的节点（入口节点）
        all_targets: set[str] = set()
        for dst_ids in edges.values():
            all_targets.update(dst_ids)
        entry_nodes = [n for n in nodes if n not in all_targets]
        for entry_id in entry_nodes:
            graph.add_edge(START, entry_id)

        # 连接没有出边的节点到 END
        for node_id in nodes:
            if node_id not in edges or not edges.get(node_id):
                graph.add_edge(node_id, END)

        # 编译图
        compiled = graph.compile(
            interrupt_before=self._interrupt_before or None,
        )

        return compiled

    async def execute(
        self,
        graph: Any,
        initial: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> LangGraphState:
        """
        执行编译后的图。

        Args:
            graph: CompiledStateGraph（由 build() 返回）
            initial: 初始状态（覆盖默认值）
            config: 运行配置

        Returns:
            最终 LangGraphState
        """
        state = initial_state(**(initial or {}))

        if hasattr(graph, "ainvoke"):
            result = await graph.ainvoke(state, config=config or {})
        else:
            # 同步回退
            result = graph.invoke(state, config=config or {})

        return result

    async def astream_events(
        self,
        graph: Any,
        initial: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ):
        """
        流式执行，产生事件（用于 GUI 实时更新）。

        Args:
            graph: CompiledStateGraph
            initial: 初始状态
            config: 运行配置

        Yields:
            LangGraph 事件字典
        """
        state = initial_state(**(initial or {}))

        if hasattr(graph, "astream_events"):
            async for event in graph.astream_events(state, config=config or {}):
                yield event
        else:
            # 不支持流式时，直接执行并 yield 最终结果
            result = await graph.ainvoke(state, config=config or {}) if hasattr(graph, "ainvoke") else graph.invoke(state, config=config or {})
            yield {"event": "end", "data": result}
