# ADR-0005: LangGraph 后端适配器架构

## 状态
Accepted (V0.4.0 F1)

## 背景

系统自研的 `WorkflowEngine` 能执行 DAG 工作流，但缺少：
- 原生 checkpointing（中断/恢复）
- 与 LangGraph 生态的互操作（LangSmith 监控、Studio 可视化）
- `interrupt_before` 集成（LangGraph 原生 HITL 支持）

## 决策

采用**适配器模式**：`CompiledPipeline` → `LangGraphBackend.build()` → `CompiledStateGraph`。

### 映射关系

| 本系统概念 | LangGraph 构造 |
|---|---|
| `WorkflowNode` (LLM/TOOL/CODE/RAG) | `graph.add_node(id, fn)` |
| `DependencyGraph.edges` | `graph.add_edge(src, dst)` |
| `BranchNode` | `graph.add_conditional_edges(src, cond_fn, mapping)` |
| `QualityGate` fix loop | `graph.add_conditional_edges(module, quality_fn, {next,fix,end})` |
| `HumanNode` | `interrupt_before=[node_id]` |
| `node.inputs` | node fn 读取 `state["node_outputs"][dep_id]` |

### 状态定义

```python
class LangGraphState(TypedDict):
    node_outputs: dict[str, Any]   # merge_node_outputs reducer
    current_phase: int
    quality_passed: bool
    fix_iterations: int
    errors: list[str]             # append_errors reducer
    pending_human: dict | None
```

### 质量循环结构

```
module_a → quality_a ─PASS→ module_b
                   ├─FAIL→ module_a (fix_iterations++)
                   └─MAX→ END
```

### 可选依赖策略

LangGraph 作为可选 extra（`pip install langgraph`），通过 try/except ImportError 在包级别处理：

```python
# tools/langgraph_adapter/__init__.py
try:
    from tools.langgraph_adapter.graph_builder import LangGraphBackend
except ImportError:
    class LangGraphBackend:
        def __init__(self, *a, **kw):
            raise ImportError("pip install langgraph to use LangGraph backend")
```

## 后果

**优点**：
- 自研引擎和 LangGraph 引擎共享同一份 `CompiledPipeline`
- LangGraph 的 checkpointing 和 `astream_events()` 开箱即用
- 向后兼容：不装 langgraph 时完全不影响现有功能

**缺点**：
- 两套执行引擎需要维护测试（~6 个额外测试文件）
- LangGraph 的 `interrupt_before` 语义与本系统的 `HumanNode` 略有差异
- 质量循环的 fix_iterations 需要手动跟踪（LangGraph 原生不支持计数器）

## 相关

- ADR-0001: Schema-First Pipeline（CompiledPipeline 是适配器输入）
- `tools/langgraph_adapter/` — 适配器实现
