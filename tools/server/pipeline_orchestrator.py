# tools/server/pipeline_orchestrator.py

"""
Pipeline Orchestrator — 连接编译、执行与流式输出。

    用户请求
      ↓
PipelineCompiler.compile()
      ↓
WorkflowEngine.execute_async()
      ↓
_run_workflow() → LifecycleHooks → queue.Queue
      ↓
SSE endpoint 消费队列 → 推送给客户端

用法:
    orchestrator = PipelineOrchestrator()
    result = await orchestrator.run_pipeline("构建用户登录模块")

    # 或流式:
    async for event in orchestrator.stream_pipeline("构建用户登录模块"):
        print(event)
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SessionManager (from session_manager.py)
# ---------------------------------------------------------------------------

DEFAULT_SESSION_DIR = ".sessions"

class SessionManager:
    """
    流水线运行记录的持久化管理器。

    每个 run 保存为一个 JSON 文件: {session_dir}/{run_id}.json
    同时维护一个索引文件: {session_dir}/_index.json
    """

    def __init__(self, session_dir: str = None) -> None:
        """
        Args:
            session_dir: 会话存储目录路径。
                         默认使用 .sessions/ 目录。
        """
        self.session_dir = Path(session_dir or DEFAULT_SESSION_DIR)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.session_dir / "_index.json"
        self._load_index()

    def _load_index(self) -> None:
        """加载索引文件"""
        if self._index_path.exists():
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    self._index: Dict[str, dict] = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._index = {}
        else:
            self._index = {}

    def _save_index(self) -> None:
        """保存索引文件"""
        try:
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error("[SessionManager] Failed to save index: %s", e)

    def save_run(self, run_id: str, result: dict) -> str:
        """
        保存流水线运行结果。

        Args:
            run_id: 运行 ID
            result: 运行结果字典

        Returns:
            run_id
        """
        # 添加时间戳
        if "saved_at" not in result:
            result["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        # 保存完整结果到独立文件
        run_file = self.session_dir / f"{run_id}.json"
        try:
            with open(run_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        except IOError as e:
            logger.error("[SessionManager] Failed to save run %s: %s", run_id, e)
            return run_id

        # 更新索引（只保存摘要信息）
        self._index[run_id] = {
            "run_id": run_id,
            "status": result.get("status", "unknown"),
            "elapsed_seconds": result.get("elapsed_seconds", 0),
            "saved_at": result.get("saved_at", ""),
        }
        self._save_index()

        logger.info("[SessionManager] Saved run %s (%s)", run_id, result.get("status", "?"))
        return run_id

    def get_run(self, run_id: str) -> Optional[dict]:
        """
        获取流水线运行结果。

        Args:
            run_id: 运行 ID

        Returns:
            运行结果字典，不存在则返回 None
        """
        # 先检查索引
        if run_id not in self._index:
            return None

        # 读取完整结果
        run_file = self.session_dir / f"{run_id}.json"
        if not run_file.exists():
            return None

        try:
            with open(run_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("[SessionManager] Failed to load run %s: %s", run_id, e)
            return None

    def list_runs(self, limit: int = 20) -> List[dict]:
        """
        列出所有已保存的运行记录。

        Args:
            limit: 最大返回数量（按保存时间倒序）

        Returns:
            运行记录摘要列表
        """
        runs = list(self._index.values())
        # 按 saved_at 倒序排列
        runs.sort(key=lambda r: r.get("saved_at", ""), reverse=True)
        return runs[:limit]

    def delete_run(self, run_id: str) -> bool:
        """
        删除运行记录。

        Args:
            run_id: 运行 ID

        Returns:
            是否成功删除
        """
        if run_id not in self._index:
            return False

        # 删除文件
        run_file = self.session_dir / f"{run_id}.json"
        try:
            if run_file.exists():
                run_file.unlink()
        except IOError as e:
            logger.error("[SessionManager] Failed to delete file %s: %s", run_file, e)

        # 更新索引
        del self._index[run_id]
        self._save_index()
        return True

    def clear_all(self) -> int:
        """
        清除所有运行记录。

        Returns:
            删除的记录数量
        """
        count = len(self._index)
        for run_id in list(self._index.keys()):
            self.delete_run(run_id)
        return count

# ---------------------------------------------------------------------------
# PipelineEvent
# ---------------------------------------------------------------------------

@dataclass
class PipelineEvent:
    """流水线事件 — 通过 queue.Queue 传递给 SSE"""
    tag: str          # "think" | "node_start" | "node_complete" | "node_error" | "complete" | "error"
    content: str      # 事件内容（文本或 JSON）
    timestamp: str = ""
    run_id: str = ""
    node_id: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_sse(self) -> str:
        """格式化为 SSE event"""
        data = json.dumps({
            "tag": self.tag,
            "content": self.content,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "node_id": self.node_id,
            **self.metadata,
        }, ensure_ascii=False)
        return f"event: step\ndata: {data}\n\n"

# ---------------------------------------------------------------------------
# PipelineOrchestrator
# ---------------------------------------------------------------------------

class PipelineOrchestrator:
    """
    流水线编排器。

    连接 PipelineCompiler → WorkflowEngine → 事件流，
    支持同步执行和 SSE 流式执行两种模式。

    用法:
        orchestrator = PipelineOrchestrator(llm_provider=None)

        # 同步模式
        result = await orchestrator.run_pipeline("构建用户登录模块")

        # 流式模式
        async for event in orchestrator.stream_pipeline("构建用户登录模块"):
            print(event.tag, event.content)
    """

    def __init__(
        self,
        llm_provider=None,
        tool_registry=None,
        rag_engine=None,
        max_retries: int = 3,
        checkpoint_dir: str = ".checkpoints",
        session_dir: str = None,
        backend: str = "workflow",
    ) -> None:
        self.llm_provider = llm_provider
        self.tool_registry = tool_registry
        self.rag_engine = rag_engine
        self.max_retries = max_retries
        self.checkpoint_dir = checkpoint_dir
        self.backend = backend  # "workflow" | "langgraph"

        # 延迟初始化 engine（避免每次创建都分配资源）
        self._engine = None

        # Session manager（可选，用于持久化运行记录）
        self._session_manager = None
        if session_dir is not None:
            self._session_manager = SessionManager(session_dir=session_dir)

    @property
    def engine(self) -> Any:
        """延迟创建 WorkflowEngine"""
        if self._engine is None:
            from tools.workflow.engine import WorkflowEngine, LifecycleHooks

            hooks = LifecycleHooks()
            self._engine = WorkflowEngine(
                max_retries=self.max_retries,
                checkpoint_dir=self.checkpoint_dir,
                lifecycle_hooks=hooks,
            )
            # 保存 hooks 引用以便注册进度回调
            self._hooks = hooks
        return self._engine

    @property
    def session_manager(self) -> Any:
        """获取 SessionManager 实例（可能为 None）"""
        return self._session_manager

    def list_runs(self, limit: int = 20) -> list:
        """列出历史运行记录"""
        if self._session_manager:
            return self._session_manager.list_runs(limit=limit)
        return []

    def get_run(self, run_id: str) -> dict:
        """获取指定运行记录"""
        if self._session_manager:
            return self._session_manager.get_run(run_id)
        return None

    def _create_progress_queue(self) -> tuple[queue.Queue, Callable]:
        """
        创建事件队列和回调函数。

        Returns:
            (queue, callback) — callback 传入 LifecycleHooks
        """
        q: queue.Queue = queue.Queue()

        def _on_start(event) -> None:
            q.put(PipelineEvent(
                tag="think",
                content=f"流水线启动: {event.data.get('workflow_id', '')}",
                run_id=event.run_id,
            ))

        def _on_step(event) -> None:
            q.put(PipelineEvent(
                tag="node_complete",
                content=json.dumps({
                    "node_id": event.node_id,
                    "duration_ms": event.data.get("duration_ms", 0),
                    "status": event.data.get("status", "success"),
                }),
                run_id=event.run_id,
                node_id=event.node_id,
            ))

        def _on_error(event) -> None:
            q.put(PipelineEvent(
                tag="node_error",
                content=json.dumps({
                    "node_id": event.node_id,
                    "error": event.data.get("error", ""),
                    "error_type": event.data.get("error_type", ""),
                }),
                run_id=event.run_id,
                node_id=event.node_id,
            ))

        def _on_complete(event) -> None:
            q.put(PipelineEvent(
                tag="complete",
                content=json.dumps({
                    "status": event.data.get("status", "success"),
                    "completed_nodes": event.data.get("completed_nodes", []),
                }),
                run_id=event.run_id,
            ))

        # 注册钩子
        self._hooks.register("on_start", _on_start)
        self._hooks.register("on_step", _on_step)
        self._hooks.register("on_error", _on_error)
        self._hooks.register("on_complete", _on_complete)

        return q, (_on_start, _on_step, _on_error, _on_complete)

    def _unregister_hooks(self, handlers: tuple) -> None:
        """注销进度回调钩子"""
        hook_names = ("on_start", "on_step", "on_error", "on_complete")
        for name, handler in zip(hook_names, handlers):
            self._hooks.unregister(name, handler)

    async def run_pipeline(self, requirement: str,
                           progress_cb: Callable[[PipelineEvent], None] = None,
                           backend: str | None = None) -> dict:
        """
        同步执行流水线（等待完成）。

        Args:
            requirement: 用户需求描述
            progress_cb: 可选的进度回调函数
            backend: 执行后端 ("workflow" | "langgraph")，None 则使用实例默认值

        Returns:
            执行结果字典 {status, outputs, logs, ...}
        """
        use_backend = backend or self.backend
        if use_backend == "langgraph":
            return await self._run_langgraph(requirement, progress_cb=progress_cb)

        # --- 原有 workflow 后端 ---
        run_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # 1. 编译流水线
        workflow_def = self._compile_requirement(requirement)
        if not workflow_def:
            return {
                "status": "failed",
                "error": "Pipeline compilation failed",
                "run_id": run_id,
            }

        # 2. 加载工作流
        self.engine.load_workflow(workflow_def)

        # 3. 执行
        workflow_id = workflow_def["id"]
        exec_run_id = await self.engine.execute_async(
            workflow_id,
            {"input": requirement, "_requirement": requirement},
            context={"llm_provider": self.llm_provider},
        )

        # 4. 等待完成
        result = await self._wait_for_result(exec_run_id, timeout=300)
        elapsed = round(time.time() - start_time, 2)

        result["elapsed_seconds"] = elapsed
        result["run_id"] = run_id

        # 调用用户回调
        if progress_cb:
            progress_cb(PipelineEvent(
                tag="complete",
                content=json.dumps(result, ensure_ascii=False, default=str),
                run_id=run_id,
            ))

        # 自动保存运行记录
        if self._session_manager and result.get("status") in ("success", "failed"):
            self._session_manager.save_run(run_id, result)

        return result

    async def _run_langgraph(
        self,
        requirement: str,
        progress_cb: Callable[[PipelineEvent], None] | None = None,
    ) -> dict:
        """LangGraph 后端执行路径。

        需要: pip install langgraph
        """
        run_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        if progress_cb:
            progress_cb(PipelineEvent(
                tag="think",
                content="正在编译 LangGraph 流水线...",
                run_id=run_id,
            ))

        try:
            from tools.compiler.pipeline_compiler import PipelineCompiler

            compiler = PipelineCompiler()
            compiled = compiler.compile_from_config()
            graph = compiled.to_langgraph(
                llm_provider=self.llm_provider,
                tool_registry=self.tool_registry,
            )

            from tools.langgraph_adapter.graph_builder import LangGraphBackend

            backend = LangGraphBackend()
            result_state = await backend.execute(
                graph,
                {"query": requirement, "input": requirement},
            )

            elapsed = round(time.time() - start_time, 2)
            result = {
                "status": "success",
                "run_id": run_id,
                "elapsed_seconds": elapsed,
                "node_outputs": result_state.get("node_outputs", {}),
                "backend": "langgraph",
            }
        except ImportError:
            elapsed = round(time.time() - start_time, 2)
            result = {
                "status": "failed",
                "run_id": run_id,
                "elapsed_seconds": elapsed,
                "error": "langgraph not installed. pip install langgraph",
                "backend": "langgraph",
            }
        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            result = {
                "status": "failed",
                "run_id": run_id,
                "elapsed_seconds": elapsed,
                "error": str(e),
                "backend": "langgraph",
            }

        if progress_cb:
            progress_cb(PipelineEvent(
                tag="complete",
                content=json.dumps(result, ensure_ascii=False, default=str),
                run_id=run_id,
            ))

        if self._session_manager and result.get("status") in ("success", "failed"):
            self._session_manager.save_run(run_id, result)

        return result

    async def stream_pipeline(self, requirement: str) -> AsyncGenerator[PipelineEvent, None]:
        """
        流式执行流水线，实时推送事件。

        Args:
            requirement: 用户需求描述

        Yields:
            PipelineEvent 对象
        """
        run_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # 1. 编译流水线
        yield PipelineEvent(
            tag="think",
            content="正在编译流水线...",
            run_id=run_id,
        )

        workflow_def = self._compile_requirement(requirement)
        if not workflow_def:
            yield PipelineEvent(
                tag="error",
                content="流水线编译失败",
                run_id=run_id,
            )
            yield PipelineEvent(
                tag="complete",
                content=json.dumps({"status": "failed"}),
                run_id=run_id,
            )
            return

        yield PipelineEvent(
            tag="think",
            content=f"流水线编译完成: {workflow_def['name']} ({len(workflow_def['nodes'])} 节点)",
            run_id=run_id,
            metadata={"node_count": len(workflow_def["nodes"])},
        )

        # 2. 确保 engine 和 hooks 已初始化
        _ = self.engine

        # 3. 创建事件队列并注册钩子
        event_queue, handlers = self._create_progress_queue()

        # 4. 加载工作流
        self.engine.load_workflow(workflow_def)
        workflow_id = workflow_def["id"]

        # 5. 异步执行（fire-and-forget）
        exec_run_id = await self.engine.execute_async(
            workflow_id,
            {"input": requirement, "_requirement": requirement},
            context={"llm_provider": self.llm_provider},
        )

        # 5. 从队列消费事件并 yield
        completed = False
        while not completed:
            try:
                # 用 asyncio.to_thread 避免阻塞事件循环
                event = await asyncio.to_thread(event_queue.get, True, 0.5)
                if event.tag == "complete":
                    completed = True
                yield event
            except queue.Empty:
                # 检查是否已完成（防止钩子未触发 complete）
                result = self.engine.get_run_result(exec_run_id)
                if result and result.status != "running":
                    completed = True
                    yield PipelineEvent(
                        tag="complete",
                        content=json.dumps({
                            "status": result.status,
                            "elapsed_seconds": round(time.time() - start_time, 2),
                        }, ensure_ascii=False),
                        run_id=run_id,
                    )

        # 6. 清理钩子
        self._unregister_hooks(handlers)

    def _compile_requirement(self, requirement: str) -> Optional[dict]:
        """
        将用户需求编译为工作流定义。

        使用 PipelineCompiler.compile_from_config() 从 config/ 目录加载所有 schema，
        然后转换为 WorkflowEngine 兼容的工作流定义。
        """
        try:
            from tools.compiler import PipelineCompiler

            # 从 config 目录加载并编译
            compiler = PipelineCompiler()
            compiled = compiler.compile_from_config(config_dir="config")

            if not compiled or not compiled.implementation_order:
                return None

            # 转换为 WorkflowEngine 工作流定义
            workflow_def = self._to_workflow_def(compiled, requirement)
            return workflow_def

        except Exception as e:
            logger.error("[Orchestrator] Compilation failed: %s", e, exc_info=True)
            # 编译失败时返回一个最小工作流（单 LLM 节点）
            return self._fallback_workflow(requirement, str(e))

    def _to_workflow_def(self, compiled, requirement: str) -> dict:
        """将 CompiledPipeline 转换为 WorkflowEngine 工作流定义"""
        nodes = []
        edges = []

        # 为每个模块创建节点
        order = getattr(compiled, 'implementation_order', [])
        for i, module_name in enumerate(order):
            node_id = f"module_{module_name}"
            prompt = ""
            if hasattr(compiled, 'prompt_template') and compiled.prompt_template:
                prompt = compiled.prompt_template.template_str

            nodes.append({
                "id": node_id,
                "type": "llm",
                "name": f"Generate {module_name}",
                "config": {
                    "prompt_template": prompt,
                    "module_name": module_name,
                    "temperature": 0.2,
                },
                "inputs": [f"module_{order[i-1]}"] if i > 0 else [],
            })

            if i > 0:
                edges.append({"from": f"module_{order[i-1]}", "to": node_id})

        # 质量检查节点
        if hasattr(compiled, 'quality_gates') and compiled.quality_gates.gates:
            nodes.append({
                "id": "quality_check",
                "type": "branch",
                "name": "Quality Gate Check",
                "config": {
                    "condition": "quality_passed",
                    "branches": {"true": "", "false": "fix_loop"},
                },
                "inputs": [f"module_{order[-1]}"] if order else [],
            })
            if order:
                edges.append({"from": f"module_{order[-1]}", "to": "quality_check"})

        return {
            "id": f"pipeline_{uuid.uuid4().hex[:6]}",
            "name": "Code Generation Pipeline",
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "module_count": len(order),
                "modules": order,
                "requirement": requirement[:200],
            },
        }

    def _fallback_workflow(self, requirement: str, error: str) -> dict:
        """编译失败时的回退工作流（单节点 LLM）"""
        return {
            "id": f"fallback_{uuid.uuid4().hex[:6]}",
            "name": "Fallback Pipeline",
            "nodes": [
                {
                    "id": "analyze",
                    "type": "llm",
                    "name": "Analyze Requirement",
                    "config": {
                        "prompt_template": requirement,
                        "temperature": 0.3,
                    },
                    "inputs": [],
                },
            ],
            "edges": [],
            "metadata": {
                "fallback": True,
                "compile_error": error,
                "requirement": requirement[:200],
            },
        }

    async def _wait_for_result(self, run_id: str, timeout: int = 300) -> dict:
        """等待 WorkflowEngine 执行完成"""

        elapsed = 0.0
        while elapsed < timeout:
            result = self.engine.get_run_result(run_id)
            if result and result.status != "running":
                return {
                    "status": result.status,
                    "outputs": {k: str(v)[:500] for k, v in result.outputs.items()},
                    "execution_time_ms": result.execution_time_ms,
                    "logs": [
                        {"node_id": log_entry.node_id, "status": log_entry.status, "duration_ms": log_entry.duration_ms}
                        for log_entry in result.logs
                    ],
                }
            await asyncio.sleep(0.1)
            elapsed += 0.1

        return {
            "status": "timeout",
            "error": f"Pipeline timed out after {timeout}s",
        }
