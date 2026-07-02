# tools/workflow/engine.py

"""
工作流执行引擎 — 核心引擎 + 上下文管理 + 生命周期钩子。

本模块保留:
  - ContextItem / ContextWindow  — 动态上下文窗口
  - LifecycleEvent / LifecycleHooks / LifecycleHandler — 生命周期钩子
  - Workflow / ExecutionLog / WorkflowResult / SubTask — 数据模型
  - WorkflowEngine — 主引擎（DAG 执行、并发控制、优雅关闭）

执行策略已拆分为:
  - tools.workflow.execution  (RecoveryManager, QualityLoop, CircuitBreaker, ResultAggregator)
  - tools.workflow.messaging  (Topic, Message, MessageBus)

用法:
    engine = WorkflowEngine()
    workflow = engine.load_workflow({...})
    result = await engine.execute_async("wf-001", {"input": "用户登录模块"})
"""

import asyncio
import json
import logging
import random
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools.exceptions import (
    WorkflowExecutionError,
    WorkflowPermissionError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ContextWindow + ContextItem  (moved to tools/workflow/context.py)
# ---------------------------------------------------------------------------

from tools.workflow.context import ContextWindow, LifecycleHooks

# ---------------------------------------------------------------------------
# WorkflowEngine and related dataclasses
# ---------------------------------------------------------------------------

from tools.workflow.nodes import (
    WorkflowNode, NodeType, LLMNode, RAGNode, ToolNode, CodeNode, BranchNode, HumanNode,
)
from tools.workflow.execution import (
    RecoveryManager, RetryPolicy,
    QualityLoop,
    AgentResult, ResultAggregator,
    CircuitBreaker, CircuitState, CircuitBreakerOpenError,
)

@dataclass
class Workflow:
    """工作流定义"""
    id: str
    name: str
    nodes: Dict[str, WorkflowNode]       # node_id → node
    edges: Dict[str, List[str]]          # node_id → [下游 node_id]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ExecutionLog:
    """单条执行日志"""
    node_id: str
    status: str          # success / failed / skipped
    output: Any
    duration_ms: int
    timestamp: str

@dataclass
class WorkflowResult:
    """工作流执行结果"""
    workflow_id: str
    status: str          # success / failed / running
    outputs: Dict[str, Any]    # 各节点最终输出
    execution_time_ms: int
    logs: List[ExecutionLog]
    started_at: str = ""
    finished_at: str = ""

@dataclass
class SubTask:
    """子任务定义 — 支持 fan-out 到多个并行 worker"""
    task_id: str
    node_id: str
    inputs: dict
    status: str = "pending"    # pending | running | completed | failed
    output: Any = None
    error: str = ""
    retries: int = 0

class WorkflowEngine:
    """工作流执行引擎"""

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0,
                 checkpoint_dir: str = ".checkpoints",
                 context_window: ContextWindow = None,
                 lifecycle_hooks: LifecycleHooks = None,
                 recovery_manager: RecoveryManager = None,
                 quality_loop: QualityLoop = None,
                 max_concurrent: int = 5,
                 max_runs_cache: int = 1000) -> None:
        self._workflows: Dict[str, Workflow] = {}
        self._runs: OrderedDict[str, WorkflowResult] = OrderedDict()
        self._sub_tasks: Dict[str, SubTask] = {}
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.checkpoint_dir = checkpoint_dir
        self.context_window = context_window
        self.lifecycle_hooks = lifecycle_hooks or LifecycleHooks()
        self.recovery_manager = recovery_manager
        self.quality_loop = quality_loop

        # 并发控制 (Gap 17)
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # 内存管理 (Gap 18)
        self._max_runs_cache = max_runs_cache

        # 优雅关闭 (Gap 26)
        self._shutdown_event = asyncio.Event()
        self._active_tasks: set = set()

    def save_checkpoint(self, run_id: str) -> str:
        """保存运行状态检查点（支持断点续跑）"""
        import os
        result = self._runs.get(run_id)
        if not result:
            raise ValueError(f"Run not found: {run_id}")

        os.makedirs(self.checkpoint_dir, exist_ok=True)
        path = os.path.join(self.checkpoint_dir, f"{run_id}.json")
        checkpoint = {
            "run_id": run_id,
            "workflow_id": result.workflow_id,
            "status": result.status,
            "outputs": {k: str(v)[:1000] for k, v in result.outputs.items()},
            "logs": [{"node_id": l.node_id, "status": l.status,
                      "duration_ms": l.duration_ms} for l in result.logs],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        logger.info("[WorkflowEngine] Checkpoint saved: %s", path)
        return path

    def load_checkpoint(self, run_id: str) -> Optional[dict]:
        """加载检查点"""
        import os
        path = os.path.join(self.checkpoint_dir, f"{run_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def fan_out(self, node: WorkflowNode, inputs: dict,
                sub_tasks: list[dict]) -> SubTask:
        """Fan-out: 将一个节点拆分为多个并行子任务"""
        main_task = SubTask(
            task_id=str(uuid.uuid4())[:8],
            node_id=node.id,
            inputs=inputs,
            status="running",
        )
        self._sub_tasks[main_task.task_id] = main_task

        async def _run_sub() -> None:
            coros = []
            for sub in sub_tasks:
                merged = {**inputs, **sub.get("inputs_override", {})}
                sub_task = SubTask(
                    task_id=sub.get("task_id", str(uuid.uuid4())[:6]),
                    node_id=node.id,
                    inputs=merged,
                )
                self._sub_tasks[sub_task.task_id] = sub_task
                coros.append(self._run_single_node(node, merged, None))

            outputs = await asyncio.gather(*coros, return_exceptions=True)
            aggregated = []
            for i, out in enumerate(outputs):
                if isinstance(out, Exception):
                    aggregated.append({"error": str(out), "index": i})
                else:
                    aggregated.append(out)
            main_task.output = aggregated
            main_task.status = "completed"

        asyncio.create_task(_run_sub())
        return main_task

    async def _run_with_retry(self, node: WorkflowNode, inputs: dict,
                              context: dict = None) -> Any:
        """带重试 + 权限校验的节点执行（集成 RecoveryManager）"""
        # 权限校验
        if node.permissions:
            allowed = context.get("allowed_permissions", []) if context else []
            missing = [p for p in node.permissions if p not in allowed]
            if missing and allowed:
                raise WorkflowPermissionError(node.id, missing)

        # 幂等去重
        if node.idempotent and node.id in getattr(self, '_executed_idempotent', set()):
            logger.info("[WorkflowEngine] Skipping idempotent node %s (already executed)", node.id)
            return {"skipped": True, "node_id": node.id}

        # 如果有 RecoveryManager，使用分级恢复策略
        if self.recovery_manager:
            async def _execute() -> Any:
                return await self._execute_node(node, inputs, context)

            recovery_result = await self.recovery_manager.execute_with_recovery(
                _execute,
                task_context={"node_id": node.id, "inputs": inputs},
            )
            if recovery_result.success:
                return recovery_result.output
            raise WorkflowExecutionError(f"Node {node.id} failed after recovery: {recovery_result.final_error}")

        # 内置重试逻辑（无 RecoveryManager 时的 fallback）
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                async with self._semaphore:
                    if self._shutdown_event.is_set():
                        raise WorkflowExecutionError("Engine is shutting down")
                    result = await self._execute_node(node, inputs, context)
                if node.idempotent:
                    self._executed_idempotent = getattr(self, '_executed_idempotent', set())
                    self._executed_idempotent.add(node.id)
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries and not isinstance(e, PermissionError):
                    delay = self.retry_delay * (2 ** attempt) + random.random()
                    logger.warning("[WorkflowEngine] Node %s retry %d/%d after %.1fs: %s",
                                   node.id, attempt + 1, self.max_retries, delay, e)
                    await asyncio.sleep(delay)
                else:
                    break
        raise last_error

    def load_workflow(self, definition: dict) -> Workflow:
        """从字典加载工作流定义"""
        nodes = {}
        for node_def in definition.get("nodes", []):
            node = WorkflowNode(
                id=node_def["id"],
                type=NodeType(node_def.get("type", "llm")),
                name=node_def.get("name", node_def["id"]),
                config=node_def.get("config", {}),
                inputs=node_def.get("inputs", []),
                version=node_def.get("version", "1.0.0"),
                permissions=node_def.get("permissions", []),
                side_effect=node_def.get("side_effect", False),
                idempotent=node_def.get("idempotent", False),
            )
            nodes[node.id] = node

        edges = {}
        for edge_def in definition.get("edges", []):
            src = edge_def.get("from", "")
            dst = edge_def.get("to", "")
            if src not in edges:
                edges[src] = []
            edges[src].append(dst)

        workflow = Workflow(
            id=definition.get("id", ""),
            name=definition.get("name", ""),
            nodes=nodes,
            edges=edges,
            metadata=definition.get("metadata", {}),
        )
        self._workflows[workflow.id] = workflow
        logger.info("[WorkflowEngine] Loaded workflow '%s' with %d nodes",
                    workflow.id, len(nodes))
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[dict]:
        return [
            {"id": w.id, "name": w.name, "node_count": len(w.nodes)}
            for w in self._workflows.values()
        ]

    async def execute_async(self, workflow_id: str, input_data: dict,
                            context: dict = None) -> str:
        """异步执行工作流，返回 run_id"""
        run_id = str(uuid.uuid4())
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_id}")

        result = WorkflowResult(
            workflow_id=workflow_id,
            status="running",
            outputs={"_input": input_data},
            execution_time_ms=0,
            logs=[],
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._runs[run_id] = result
        self._evict_runs_cache()

        task = asyncio.create_task(self._run_workflow(workflow, result, input_data, context, run_id))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

        return run_id

    async def wait_for_run(self, run_id: str, timeout: float = 5.0,
                           poll_interval: float = 0.01) -> Optional[WorkflowResult]:
        """等待指定 run 完成（轮询结果状态，无固定长 sleep）。

        测试用：替代 ``asyncio.sleep`` 做确定性等待。
        """
        start = asyncio.get_event_loop().time()
        while True:
            result = self._runs.get(run_id)
            if result is not None and result.status != "running":
                return result
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= timeout:
                return result
            await asyncio.sleep(poll_interval)

    def get_run_result(self, run_id: str) -> Optional[WorkflowResult]:
        return self._runs.get(run_id)

    def list_runs(self, workflow_id: str = None) -> List[dict]:
        runs = []
        for run_id, result in self._runs.items():
            if workflow_id and result.workflow_id != workflow_id:
                continue
            runs.append({
                "run_id": run_id,
                "workflow_id": result.workflow_id,
                "status": result.status,
                "started_at": result.started_at,
            })
        return runs

    def shutdown(self) -> None:
        """触发优雅关闭"""
        self._shutdown_event.set()
        logger.info("[WorkflowEngine] Shutdown signaled, waiting for %d active tasks", len(self._active_tasks))

    async def wait_for_completion(self, timeout: float = 30.0) -> bool:
        """等待所有活跃任务完成"""
        if not self._active_tasks:
            return True

        logger.info("[WorkflowEngine] Waiting for %d tasks to complete (timeout=%.0fs)"
                     % (len(self._active_tasks), timeout))

        start = asyncio.get_event_loop().time()
        while self._active_tasks:
            await asyncio.sleep(0.1)
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= timeout:
                logger.warning("[WorkflowEngine] Shutdown timeout after %.0fs, %d tasks still active",
                               timeout, len(self._active_tasks))
                return False

        return True

    @property
    def active_task_count(self) -> int:
        """当前活跃任务数"""
        return len(self._active_tasks)

    def _evict_runs_cache(self) -> None:
        """LRU 淘汰"""
        while len(self._runs) > self._max_runs_cache:
            evicted_id, _ = self._runs.popitem(last=False)
            logger.debug("[WorkflowEngine] Evicted run %s from cache (LRU)", evicted_id)

    async def _run_workflow(self, workflow: Workflow, result: WorkflowResult,
                            input_data: dict, context: dict = None,
                            run_id: str = "") -> None:
        """执行工作流（拓扑排序 + 并行执行 + 检查点 + 生命周期钩子 + 动态上下文）"""
        start_time = datetime.now(timezone.utc)
        completed_nodes = set()
        effective_run_id = run_id or str(uuid.uuid4())[:8]

        # --- Lifecycle: on_start ---
        self.lifecycle_hooks.emit(
            "on_start",
            run_id=effective_run_id,
            data={"workflow_id": workflow.id, "node_count": len(workflow.nodes)},
        )

        try:
            order = self._topological_sort(workflow)
            result.outputs["_input"] = input_data

            if self.context_window is not None:
                self.context_window.add_system(
                    f"Workflow: {workflow.name} ({workflow.id})", priority=10
                )
                self.context_window.add_user_message(
                    str(input_data)[:500], priority=8
                )

            for node_id in order:
                node = workflow.nodes.get(node_id)
                if not node:
                    continue

                upstream_inputs = {}
                for dep_id in node.inputs:
                    if dep_id in result.outputs:
                        upstream_inputs[dep_id] = result.outputs[dep_id]

                if not result.outputs:
                    upstream_inputs.update(input_data)

                node_start = datetime.now(timezone.utc)
                if self.quality_loop is not None and node.type == NodeType.LLM:
                    quality_result = await self.quality_loop.execute_with_quality(
                        node, upstream_inputs, context
                    )
                    output = quality_result.output
                    result.outputs[f"{node_id}_quality"] = {
                        "score": quality_result.quality_report.quality_score,
                        "passed": quality_result.quality_report.passed,
                        "iterations": quality_result.iterations,
                        "converged": quality_result.converged,
                        "issue_count": sum(
                            len(r.issues)
                            for r in quality_result.quality_report.module_results.values()
                        ),
                    }
                else:
                    output = await self._run_with_retry(node, upstream_inputs, context)
                node_duration = int((datetime.now(timezone.utc) - node_start).total_seconds() * 1000)

                result.outputs[node_id] = output
                result.logs.append(ExecutionLog(
                    node_id=node_id,
                    status="success",
                    output=str(output)[:500],
                    duration_ms=node_duration,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
                completed_nodes.add(node_id)

                if self.context_window is not None:
                    self.context_window.add_tool_result(
                        str(output)[:500], priority=4, tool_name=node_id
                    )

                self.lifecycle_hooks.emit(
                    "on_step",
                    run_id=effective_run_id,
                    node_id=node_id,
                    data={"status": "success", "duration_ms": node_duration},
                )

                try:
                    self.save_checkpoint(result.workflow_id + "_" + result.started_at[:19])
                except Exception as e:
                    logger.warning("Failed to save checkpoint for run %s: %s", effective_run_id, e)

            result.status = "success"

            self.lifecycle_hooks.emit(
                "on_complete",
                run_id=effective_run_id,
                data={"status": "success", "completed_nodes": list(completed_nodes)},
            )

        except Exception as e:
            logger.error("[WorkflowEngine] Execution failed at node %s: %s",
                         node_id, e)
            result.status = "failed"
            result.logs.append(ExecutionLog(
                node_id=node_id if 'node_id' in dir() else "_unknown",
                status="failed",
                output=str(e),
                duration_ms=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

            self.lifecycle_hooks.emit(
                "on_error",
                run_id=effective_run_id,
                node_id=node_id if 'node_id' in dir() else "_unknown",
                data={"error": str(e), "error_type": type(e).__name__,
                      "completed_nodes": list(completed_nodes)},
            )
        finally:
            result.execution_time_ms = int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            )
            result.finished_at = datetime.now(timezone.utc).isoformat()

    async def _execute_node(self, node: WorkflowNode, inputs: dict,
                            context: dict = None) -> Any:
        """根据节点类型执行（集成 ContextWindow 动态上下文）"""
        node_inputs = inputs
        if self.context_window is not None:
            for dep_id, dep_output in inputs.items():
                if dep_id.startswith("_"):
                    continue
                content = str(dep_output)[:500]
                self.context_window.add_tool_result(
                    content, priority=4, tool_name=dep_id
                )
            built_context = self.context_window.build()
            if built_context:
                node_inputs = {**inputs, "_dynamic_context": built_context}

        if node.type == NodeType.LLM:
            llm_node = LLMNode(
                prompt_template=node.config.get("prompt_template", ""),
                provider=context.get("llm_provider") if context else None,
                temperature=node.config.get("temperature", 0.7),
            )
            return await llm_node.execute(node_inputs)

        elif node.type == NodeType.RAG:
            rag_node = RAGNode(
                rag_engine=context.get("rag_engine") if context else None,
                top_k=node.config.get("top_k", 5),
            )
            return await rag_node.execute(node_inputs)

        elif node.type == NodeType.TOOL:
            tool_node = ToolNode(
                tool_registry=context.get("tool_registry") if context else None,
                tool_name=node.config.get("tool_name", ""),
                arguments=node.config.get("arguments", {}),
            )
            return await tool_node.execute(node_inputs)

        elif node.type == NodeType.CODE:
            code_node = CodeNode(code_template=node.config.get("code", ""))
            return await code_node.execute(node_inputs)

        elif node.type == NodeType.BRANCH:
            branch_node = BranchNode(
                condition=node.config.get("condition", "true"),
                branches=node.config.get("branches", {}),
            )
            return await branch_node.execute(node_inputs)

        elif node.type == NodeType.HUMAN:
            human_node = HumanNode(
                prompt=node.config.get("prompt", "需要人工确认"),
                risk_level=node.config.get("risk_level", "high"),
                approval_handler=context.get("approval_handler") if context else None,
            )
            return await human_node.execute(node_inputs)

        else:
            return f"[Unknown node type: {node.type}]"

    async def _run_single_node(self, node: WorkflowNode, inputs: dict,
                               context: dict = None) -> Any:
        """执行单个节点（供 fan_out 并行调用）"""
        return await self._execute_node(node, inputs, context)

    def _topological_sort(self, workflow: Workflow) -> List[str]:
        """拓扑排序（Kahn's Algorithm）"""
        in_degree = {nid: 0 for nid in workflow.nodes}
        for src, dsts in workflow.edges.items():
            for dst in dsts:
                if dst in in_degree:
                    in_degree[dst] += 1

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        result = []
        while queue:
            node_id = queue.popleft()
            result.append(node_id)
            for dst in workflow.edges.get(node_id, []):
                in_degree[dst] -= 1
                if in_degree[dst] == 0:
                    queue.append(dst)
        return result
