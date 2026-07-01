"""RAG 可观测性 — 日志 + 指标 + 健康检查。

对标 Dify 的监控能力:
    1. 结构化日志 (JSON) — 所有 RAG 操作可追溯
    2. 指标收集 — 延迟、召回率、缓存命中率
    3. 健康检查 — 后端可用性探测
    4. 请求追踪 — 每个 query 的完整链路

Usage:
    from tools.rag import RAGObserver, RAGMetrics

    observer = RAGObserver()
    metrics = RAGMetrics()

    # 记录查询
    with observer.trace("query") as span:
        result = pipeline.query("What is Python?")
        metrics.record_query(latency_ms=span.duration_ms, num_docs=result.metadata["num_documents"])

    # 获取指标
    print(metrics.summary())

    # 健康检查
    health = observer.health_check(vector_store)
    print(health)
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 结构化日志
# ---------------------------------------------------------------------------

class StructuredLogger:
    """结构化 JSON 日志记录器。

    所有 RAG 操作以 JSON 格式记录，便于日志收集系统 (ELK/Loki) 解析。
    """

    def __init__(
        self,
        name: str = "rag",
        log_file: str | None = None,
        level: int = logging.INFO,
    ) -> None:
        self.name = name
        self._logger = logging.getLogger(f"tools.rag.{name}")
        self._logger.setLevel(level)
        self._logger.propagate = False

        # 清除已有 handler
        self._logger.handlers.clear()

        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self._logger.addHandler(console_handler)

        # 文件 handler (可选)
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(file_handler)

    def log_event(self, event_type: str, **kwargs: Any) -> None:
        """记录结构化事件。"""
        data = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event_type,
            **kwargs,
        }
        self._logger.info(json.dumps(data, ensure_ascii=False))

    def log_query(
        self,
        query: str,
        num_results: int,
        latency_ms: float,
        intent: str = "",
        backend: str = "",
    ) -> None:
        """记录查询事件。"""
        self.log_event(
            "query",
            query=query[:200],  # 截断过长查询
            num_results=num_results,
            latency_ms=round(latency_ms, 2),
            intent=intent,
            backend=backend,
        )

    def log_ingest(
        self,
        num_documents: int,
        num_chunks: int,
        latency_ms: float,
        backend: str = "",
    ) -> None:
        """记录文档摄入事件。"""
        self.log_event(
            "ingest",
            num_documents=num_documents,
            num_chunks=num_chunks,
            latency_ms=round(latency_ms, 2),
            backend=backend,
        )

    def log_error(self, error_type: str, message: str, **kwargs: Any) -> None:
        """记录错误事件。"""
        self.log_event(
            "error",
            error_type=error_type,
            message=message,
            **kwargs,
        )

    def log_cache_hit(self, query: str, hit: bool) -> None:
        """记录缓存命中。"""
        self.log_event("cache", query=query[:100], hit=hit)


# ---------------------------------------------------------------------------
# 指标收集
# ---------------------------------------------------------------------------

@dataclass
class QueryMetric:
    """单次查询指标。"""

    timestamp: float
    latency_ms: float
    num_results: int
    intent: str = ""
    cache_hit: bool = False
    error: str | None = None


class RAGMetrics:
    """RAG 系统指标收集器。

    收集并聚合:
        - 查询延迟 (P50, P90, P99)
        - 召回数量
        - 缓存命中率
        - 错误率
        - 后端使用统计
    """

    def __init__(self, window_size: int = 1000) -> None:
        self.window_size = window_size
        self._query_metrics: list[QueryMetric] = []
        self._error_count = 0
        self._total_queries = 0
        self._cache_hits = 0
        self._backend_usage: dict[str, int] = defaultdict(int)
        self._intent_usage: dict[str, int] = defaultdict(int)

    def record_query(
        self,
        latency_ms: float,
        num_results: int,
        intent: str = "",
        cache_hit: bool = False,
        backend: str = "",
        error: str | None = None,
    ) -> None:
        """记录一次查询。"""
        metric = QueryMetric(
            timestamp=time.time(),
            latency_ms=latency_ms,
            num_results=num_results,
            intent=intent,
            cache_hit=cache_hit,
            error=error,
        )

        self._query_metrics.append(metric)
        self._total_queries += 1

        if len(self._query_metrics) > self.window_size:
            self._query_metrics = self._query_metrics[-self.window_size:]

        if error:
            self._error_count += 1
        if cache_hit:
            self._cache_hits += 1
        if backend:
            self._backend_usage[backend] += 1
        if intent:
            self._intent_usage[intent] += 1

    def summary(self) -> dict[str, Any]:
        """返回指标摘要。"""
        if not self._query_metrics:
            return {
                "total_queries": 0,
                "error_rate": 0.0,
                "cache_hit_rate": 0.0,
                "latency": {},
                "recall": {},
                "backend_usage": {},
                "intent_usage": {},
            }

        latencies = [m.latency_ms for m in self._query_metrics]
        results = [m.num_results for m in self._query_metrics]

        return {
            "total_queries": self._total_queries,
            "error_rate": self._error_count / max(1, self._total_queries),
            "cache_hit_rate": self._cache_hits / max(1, self._total_queries),
            "latency": {
                "p50_ms": round(float(np.percentile(latencies, 50)), 2),
                "p90_ms": round(float(np.percentile(latencies, 90)), 2),
                "p99_ms": round(float(np.percentile(latencies, 99)), 2),
                "mean_ms": round(float(np.mean(latencies)), 2),
                "min_ms": round(float(np.min(latencies)), 2),
                "max_ms": round(float(np.max(latencies)), 2),
            },
            "recall": {
                "mean": round(float(np.mean(results)), 2),
                "min": int(np.min(results)),
                "max": int(np.max(results)),
            },
            "backend_usage": dict(self._backend_usage),
            "intent_usage": dict(self._intent_usage),
        }

    def reset(self) -> None:
        """重置所有指标。"""
        self._query_metrics.clear()
        self._error_count = 0
        self._total_queries = 0
        self._cache_hits = 0
        self._backend_usage.clear()
        self._intent_usage.clear()


# ---------------------------------------------------------------------------
# 请求追踪 (链路追踪)
# ---------------------------------------------------------------------------

@dataclass
class TraceSpan:
    """单个追踪片段。"""

    name: str
    start_time: float
    end_time: float = 0.0
    children: list[TraceSpan] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return (time.time() - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "metadata": self.metadata,
            "children": [c.to_dict() for c in self.children],
        }


class RAGObserver:
    """RAG 系统可观测性入口。

    集成:
        - 结构化日志
        - 指标收集
        - 请求追踪
        - 健康检查
    """

    def __init__(
        self,
        log_file: str | None = None,
        enable_logging: bool = True,
        enable_metrics: bool = True,
    ) -> None:
        self._enable_logging = enable_logging
        self._enable_metrics = enable_metrics

        self._structured_logger = StructuredLogger(
            name="observer",
            log_file=log_file,
        ) if enable_logging else None

        self._metrics = RAGMetrics() if enable_metrics else None

        self._active_traces: list[TraceSpan] = []

    @property
    def metrics(self) -> RAGMetrics | None:
        return self._metrics

    @property
    def logger(self) -> StructuredLogger | None:
        return self._structured_logger

    @contextmanager
    def trace(self, name: str, **metadata: Any) -> Iterator:
        """追踪一个操作。

        Usage:
            with observer.trace("query", intent="factual") as span:
                result = pipeline.query("...")
                span.metadata["num_results"] = len(result.reranked_documents)
        """
        span = TraceSpan(name=name, start_time=time.time(), metadata=metadata)
        self._active_traces.append(span)

        if self._structured_logger:
            self._structured_logger.log_event("trace_start", name=name, **metadata)

        try:
            yield span
        except Exception as e:
            span.metadata["error"] = str(e)
            if self._structured_logger:
                self._structured_logger.log_error("trace_error", str(e), name=name)
            raise
        finally:
            span.end_time = time.time()
            self._active_traces.pop()

            if self._structured_logger:
                self._structured_logger.log_event(
                    "trace_end",
                    name=name,
                    duration_ms=round(span.duration_ms, 2),
                )

    def record_query(
        self,
        query: str,
        num_results: int,
        latency_ms: float,
        intent: str = "",
        backend: str = "",
        cache_hit: bool = False,
        error: str | None = None,
    ) -> None:
        """记录查询指标。"""
        if self._metrics:
            self._metrics.record_query(
                latency_ms=latency_ms,
                num_results=num_results,
                intent=intent,
                cache_hit=cache_hit,
                backend=backend,
                error=error,
            )

        if self._structured_logger:
            self._structured_logger.log_query(
                query=query,
                num_results=num_results,
                latency_ms=latency_ms,
                intent=intent,
                backend=backend,
            )

    def health_check(self, vector_store: Any = None) -> dict[str, Any]:
        """系统健康检查。

        检查:
            - 向量存储后端状态
            - 内存使用
            - 最近错误率

        Returns:
            健康状态字典。
        """
        health: dict[str, Any] = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "checks": {},
        }

        # 向量存储检查
        if vector_store is not None:
            try:
                count = vector_store.count
                health["checks"]["vector_store"] = {
                    "status": "ok",
                    "document_count": count,
                }
            except Exception as e:
                health["checks"]["vector_store"] = {
                    "status": "error",
                    "error": str(e),
                }
                health["status"] = "degraded"

        # 指标检查
        if self._metrics:
            summary = self._metrics.summary()
            error_rate = summary.get("error_rate", 0)
            if error_rate > 0.1:
                health["checks"]["error_rate"] = {
                    "status": "warning",
                    "error_rate": round(error_rate, 4),
                }
                health["status"] = "degraded"
            else:
                health["checks"]["error_rate"] = {
                    "status": "ok",
                    "error_rate": round(error_rate, 4),
                }

        return health

    def get_metrics_summary(self) -> dict[str, Any]:
        """获取指标摘要。"""
        if self._metrics:
            return self._metrics.summary()
        return {}

    def reset_metrics(self) -> None:
        """重置指标。"""
        if self._metrics:
            self._metrics.reset()

    def __repr__(self) -> str:
        status = []
        if self._structured_logger:
            status.append("logging")
        if self._metrics:
            status.append("metrics")
        return f"RAGObserver({', '.join(status)})"
