# tools/workflow/__init__.py

"""
可视化工作流引擎。

支持 DAG 执行、并行分支、条件路由、人工审批节点。

tools/workflow/
├── engine.py    — 工作流执行引擎（核心 + 上下文 + 生命周期）
├── execution.py — 执行策略（恢复、质量循环、熔断器、结果汇总）
├── messaging.py — 消息总线（Topic、Message、MessageBus）
└── nodes.py     — 节点类型定义

用法:
    from tools.workflow import WorkflowEngine, build_pipeline_workflow

    engine = WorkflowEngine()
    workflow = build_pipeline_workflow(compiled_pipeline, llm_provider)
    run_id = await engine.execute_async(workflow.id, {"input": "..."})
    result = engine.get_run_result(run_id)
"""

from tools.workflow.engine import WorkflowEngine, Workflow, WorkflowNode, WorkflowResult
from tools.workflow.execution import (
    RecoveryManager, RetryPolicy, RecoveryResult,
    QualityLoop, QualityLoopResult,
    AgentResult, ResultAggregator,
    CircuitBreaker, CircuitState, CircuitBreakerOpenError,
)
from tools.workflow.messaging import Topic, Message, MessageBus
from tools.workflow.nodes import LLMNode, RAGNode, ToolNode, CodeNode, BranchNode


def build_pipeline_workflow(compiled_pipeline, llm_provider=None,
                            tool_registry=None, agent_registry=None) -> "Workflow":
    """
    从 CompiledPipeline 编译产物构建 DAG 工作流定义。

    将 implementation_order 中的每个模块映射为一个 LLMNode，
    依赖关系映射为边，形成可执行的 DAG。

    Args:
        compiled_pipeline: PipelineCompiler.compile() 的输出
        llm_provider: LLM provider instance (for LLMNode)
        tool_registry: ToolRegistry instance (for ToolNode)
        agent_registry: dict of expert agents (for CodeNode)

    Returns:
        Workflow instance (已注册到全局 WorkflowEngine)
    """
    from tools.workflow.engine import WorkflowEngine

    engine = WorkflowEngine()

    nodes = []
    edges = []

    # Create nodes for each module in implementation order
    for i, module_name in enumerate(getattr(compiled_pipeline, 'implementation_order', [])):
        node_id = f"module_{module_name}"
        prompt = ""
        if hasattr(compiled_pipeline, 'prompt_template') and compiled_pipeline.prompt_template:
            prompt = compiled_pipeline.prompt_template.template_str

        nodes.append({
            "id": node_id,
            "type": "llm",
            "name": f"Generate {module_name}",
            "config": {
                "prompt_template": prompt,
                "module_name": module_name,
                "temperature": 0.2,
            },
            "inputs": [f"module_{compiled_pipeline.implementation_order[i-1]}"] if i > 0 else [],
        })

        if i > 0:
            edges.append({"from": f"module_{compiled_pipeline.implementation_order[i-1]}", "to": node_id})

    # Add quality gate check node
    if hasattr(compiled_pipeline, 'quality_gates') and compiled_pipeline.quality_gates.gates:
        nodes.append({
            "id": "quality_check",
            "type": "branch",
            "name": "Quality Gate Check",
            "config": {
                "condition": "quality_passed",
                "branches": {"true": "", "false": "fix_loop"},
            },
            "inputs": [f"module_{compiled_pipeline.implementation_order[-1]}"] if compiled_pipeline.implementation_order else [],
        })
        if compiled_pipeline.implementation_order:
            edges.append({
                "from": f"module_{compiled_pipeline.implementation_order[-1]}",
                "to": "quality_check",
            })

    # Add fix loop node
    nodes.append({
        "id": "fix_loop",
        "type": "llm",
        "name": "Fix & Rework",
        "config": {
            "prompt_template": "Fix the failing modules based on review feedback",
        },
        "inputs": ["quality_check"],
    })
    edges.append({"from": "fix_loop", "to": "quality_check"})

    workflow_def = {
        "id": "pipeline_workflow",
        "name": "Multi-Agent Code Generation Pipeline",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "module_count": len(compiled_pipeline.implementation_order),
            "quality_gates": len(compiled_pipeline.quality_gates.gates),
            "fix_templates": list(compiled_pipeline.fix_templates.keys()),
        },
    }

    workflow = engine.load_workflow(workflow_def)
    return workflow


__all__ = [
    # Core engine
    "WorkflowEngine", "Workflow", "WorkflowNode", "WorkflowResult",
    # Nodes
    "LLMNode", "RAGNode", "ToolNode", "CodeNode", "BranchNode",
    # Execution strategies
    "RecoveryManager", "RetryPolicy", "RecoveryResult",
    "QualityLoop", "QualityLoopResult",
    "AgentResult", "ResultAggregator",
    "CircuitBreaker", "CircuitState", "CircuitBreakerOpenError",
    # Messaging
    "Topic", "Message", "MessageBus",
    # Builder
    "build_pipeline_workflow",
]
