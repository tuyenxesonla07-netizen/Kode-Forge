# tools/langgraph_adapter/node_builder.py

"""
节点构建器 — 将 WorkflowNode 转换为 LangGraph 异步节点函数。

纯 Python 实现，不依赖 LangGraph（只构建可调用函数）。
LangGraph 依赖在 graph_builder.py 中 lazy import。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from tools.langgraph_adapter.state import LangGraphState
from tools.workflow.nodes import (
    NodeType,
    WorkflowNode,
)

logger = logging.getLogger(__name__)

# 节点函数签名: async (state: LangGraphState) -> dict (partial state update)
NodeFn = Callable[[LangGraphState], Awaitable[dict[str, Any]]]


def build_node_fn(
    node: WorkflowNode,
    llm_provider=None,
    rag_engine=None,
    tool_registry=None,
) -> NodeFn:
    """
    根据 WorkflowNode 构建 LangGraph 异步节点函数。

    Args:
        node: 工作流节点定义
        llm_provider: LLM 提供者（用于 LLMNode）
        rag_engine: RAG 引擎（用于 RAGNode）
        tool_registry: 工具注册表（用于 ToolNode）

    Returns:
        异步函数 async (state) -> partial_state_dict

    Raises:
        ValueError: 未知节点类型
    """
    builder_map = {
        NodeType.LLM: _build_llm_node,
        NodeType.RAG: _build_rag_node,
        NodeType.TOOL: _build_tool_node,
        NodeType.CODE: _build_code_node,
        NodeType.BRANCH: _build_branch_node,
        NodeType.HUMAN: _build_human_node,
    }

    builder = builder_map.get(node.type)
    if builder is None:
        raise ValueError(f"Unknown node type: {node.type}")

    return builder(node, llm_provider=llm_provider, rag_engine=rag_engine, tool_registry=tool_registry)


def _get_node_inputs(state: LangGraphState, node: WorkflowNode) -> dict[str, Any]:
    """从状态中提取当前节点的 inputs（上游节点输出）。"""
    outputs = state.get("node_outputs", {})
    inputs: dict[str, Any] = {}
    for dep_id in node.inputs:
        if dep_id in outputs:
            inputs[dep_id] = outputs[dep_id]
    return inputs


def _build_llm_node(
    node: WorkflowNode,
    llm_provider=None,
    **kwargs: Any,
) -> NodeFn:
    """构建 LLM 节点函数。"""
    prompt_template = node.config.get("prompt_template", node.name)
    node.config.get("model", "gpt-4o")
    temperature = node.config.get("temperature", 0.7)
    max_tokens = node.config.get("max_tokens", 4096)

    async def llm_node_fn(state: LangGraphState) -> dict[str, Any]:
        inputs = _get_node_inputs(state, node)
        prompt = prompt_template
        for key, value in inputs.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", str(value))

        output: Any
        if llm_provider is None:
            output = f"[LLM:{node.id}] {prompt[:200]}"
        else:
            try:
                if hasattr(llm_provider, "acomplete"):
                    response = await llm_provider.acomplete(
                        prompt=prompt, max_tokens=max_tokens, temperature=temperature
                    )
                else:
                    response = llm_provider.complete(
                        prompt=prompt, max_tokens=max_tokens, temperature=temperature
                    )
                output = response.content if response.success else f"Error: {response.error}"
            except Exception as e:
                logger.error("[LangGraph] LLMNode %s error: %s", node.id, e)
                return {node.id: f"Error: {e}", "errors": [f"LLMNode {node.id}: {e}"]}

        return {node.id: output}

    llm_node_fn.__name__ = f"llm_node_{node.id}"  # type: ignore[attr-defined]
    return llm_node_fn


def _build_rag_node(
    node: WorkflowNode,
    rag_engine=None,
    **kwargs: Any,
) -> NodeFn:
    """构建 RAG 检索节点函数。"""
    top_k = node.config.get("top_k", 5)

    async def rag_node_fn(state: LangGraphState) -> dict[str, Any]:
        inputs = _get_node_inputs(state, node)
        query = inputs.get("query", node.config.get("query", ""))

        if not rag_engine or not query:
            return {node.id: {"sources": [], "query": query}}

        try:
            result = await rag_engine.query(query, top_k=top_k)
            return {
                node.id: {
                    "answer": result.answer,
                    "sources": [s.content[:200] for s in result.sources],
                    "query": query,
                }
            }
        except Exception as e:
            logger.error("[LangGraph] RAGNode %s error: %s", node.id, e)
            return {node.id: {"error": str(e)}, "errors": [f"RAGNode {node.id}: {e}"]}

    rag_node_fn.__name__ = f"rag_node_{node.id}"  # type: ignore[attr-defined]
    return rag_node_fn


def _build_tool_node(
    node: WorkflowNode,
    tool_registry=None,
    **kwargs: Any,
) -> NodeFn:
    """构建工具调用节点函数。"""
    tool_name = node.config.get("tool_name", "")
    arguments = node.config.get("arguments", {})

    async def tool_node_fn(state: LangGraphState) -> dict[str, Any]:
        inputs = _get_node_inputs(state, node)
        args = {**arguments, **inputs}

        if not tool_registry or not tool_name:
            return {node.id: {"error": "Tool not configured"}}

        try:
            result = await tool_registry.call(tool_name, args)
            return {node.id: {"result": result, "tool": tool_name}}
        except Exception as e:
            logger.error("[LangGraph] ToolNode %s error: %s", node.id, e)
            return {node.id: {"error": str(e)}, "errors": [f"ToolNode {node.id}: {e}"]}

    tool_node_fn.__name__ = f"tool_node_{node.id}"  # type: ignore[attr-defined]
    return tool_node_fn


def _build_code_node(
    node: WorkflowNode,
    **kwargs: Any,
) -> NodeFn:
    """构建代码执行节点函数。"""
    code_template = node.config.get("code_template", "")
    safe_mode = node.config.get("safe_mode", False)

    async def code_node_fn(state: LangGraphState) -> dict[str, Any]:
        inputs = _get_node_inputs(state, node)
        code = code_template
        for key, value in inputs.items():
            code = code.replace(f"{{{{{key}}}}}", repr(value))

        if safe_mode:
            try:
                from tools.quality.ast_validator import ASTValidator
                validator = ASTValidator()
                issues = validator.validate_dangerous_imports(code)
                if issues:
                    return {
                        node.id: {"error": f"Safety check failed: {issues[0].message}"},
                        "errors": [f"CodeNode {node.id}: safety violation"],
                    }
            except ImportError:
                pass  # ASTValidator 不存在时跳过

        try:
            allowed_builtins = {
                "len": len, "str": str, "int": int, "float": float,
                "list": list, "dict": dict, "print": print,
                "range": range, "enumerate": enumerate, "zip": zip,
            }
            local_vars: dict = {}
            exec(code, {"__builtins__": allowed_builtins}, local_vars)
            return {node.id: {"output": str(local_vars.get("result", local_vars))}}
        except Exception as e:
            return {node.id: {"error": f"Code execution failed: {e}"}, "errors": [f"CodeNode {node.id}: {e}"]}

    code_node_fn.__name__ = f"code_node_{node.id}"  # type: ignore[attr-defined]
    return code_node_fn


def _build_branch_node(
    node: WorkflowNode,
    **kwargs: Any,
) -> NodeFn:
    """构建条件分支节点函数。"""
    condition = node.config.get("condition", "true")
    branches = node.config.get("branches", {"true": "", "false": ""})

    async def branch_node_fn(state: LangGraphState) -> dict[str, Any]:
        inputs = _get_node_inputs(state, node)
        context = {
            "node_outputs": state.get("node_outputs", {}),
            "current_phase": state.get("current_phase", 0),
            "quality_passed": state.get("quality_passed", False),
            **inputs,
        }
        try:
            result = eval(condition, {"__builtins__": {}}, context)
            branch = "true" if result else "false"
        except Exception:
            branch = "false"

        target = branches.get(branch, "")
        return {node.id: {"branch": branch, "target": target}}

    branch_node_fn.__name__ = f"branch_node_{node.id}"  # type: ignore[attr-defined]
    return branch_node_fn


def _build_human_node(
    node: WorkflowNode,
    **kwargs: Any,
) -> NodeFn:
    """构建人工审批节点函数（在 LangGraph 中对应 interrupt_before）。"""
    prompt = node.config.get("prompt", node.name)
    risk_level = node.config.get("risk_level", "high")

    async def human_node_fn(state: LangGraphState) -> dict[str, Any]:
        inputs = _get_node_inputs(state, node)
        # 返回待审批状态，由 LangGraph 的 interrupt_before 处理
        return {
            node.id: {
                "status": "pending_human",
                "prompt": prompt,
                "risk_level": risk_level,
                "inputs": inputs,
            },
            "pending_human": {
                "node_id": node.id,
                "prompt": prompt,
                "risk_level": risk_level,
                "inputs": inputs,
            },
        }

    human_node_fn.__name__ = f"human_node_{node.id}"  # type: ignore[attr-defined]
    return human_node_fn
