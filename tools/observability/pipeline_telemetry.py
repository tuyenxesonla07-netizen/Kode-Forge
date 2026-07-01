# tools/observability/pipeline_telemetry.py
"""
Pipeline telemetry — Tracer + PipelineMetrics.

Core observability for the pipeline. Always available, no extra dependencies.

Usage:
    from tools.observability import Tracer, PipelineMetrics

    tracer = Tracer("pipeline_run")
    with tracer.span_ctx("compile", modules=7):
        ...

    metrics = PipelineMetrics()
    metrics.record_agent_call("expert_auth", tokens=150)
    print(metrics.to_dict())
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator


# ── Tracer ──────────────────────────────────────────────────────────────────

class Tracer:
    """
    请求级追踪器。

    每次请求创建一条 trace，每个关键操作创建一个 span。
    span 支持嵌套（通过 _stack 维护父链）。

    用法（推荐 — 异常安全）:
        tracer = Tracer()
        with tracer.span_ctx("step1"):
            tracer.event("tool_called", tool="generate_code")
            with tracer.span_ctx("sub_step"):
                ...
        print(tracer.render_tree())

    用法（兼容 — 手动 finish）:
        tracer = Tracer()
        span = tracer.span("step1")
        try:
            ...
        finally:
            tracer.finish_span(span)
    """

    def __init__(self, name: str = "request") -> None:
        self.trace_id = uuid.uuid4().hex[:8]
        self.name = name
        self.spans: list[dict] = []
        self._started = time.time()
        self._stack: list[str] = []

    @contextmanager
    def span_ctx(self, name: str, **attributes) -> Iterator:
        """
        创建嵌套 span 的上下文管理器。

        无论是否发生异常，都会自动 finish span。
        异常时自动标记 status="error" 并记录异常信息。
        """
        span = self.span(name, **attributes)
        try:
            yield span
        except Exception as e:
            span["status"] = "error"
            span["attributes"]["error"] = str(e)
            span["attributes"]["error_type"] = type(e).__name__
            raise
        finally:
            self.finish_span(span)

    def span(self, name: str, **attributes) -> Any:
        """
        创建嵌套 span 并返回 span dict。

        返回的 span 是普通 dict，可直接修改 attributes 和 status。
        栈由 tracer 自动管理。

        注意: 推荐用 span_ctx() 替代，自动处理异常和 finish。
        """
        span = {
            "trace_id": self.trace_id,
            "span_id": uuid.uuid4().hex[:6],
            "parent_id": self._stack[-1] if self._stack else None,
            "name": name,
            "start_ms": round((time.time() - self._started) * 1000, 1),
            "duration_ms": 0,
            "attributes": dict(attributes),
            "status": "ok",
        }
        self.spans.append(span)
        self._stack.append(span["span_id"])
        return span

    def finish_span(self, span: dict) -> None:
        """手动结束 span，记录耗时"""
        if span["duration_ms"] == 0:
            span["duration_ms"] = round((time.time() - self._started) * 1000 - span["start_ms"], 1)
        if self._stack and self._stack[-1] == span["span_id"]:
            self._stack.pop()

    def event(self, name: str, **attributes) -> None:
        """记录零时长事件"""
        span = self.span(name, **attributes)
        self.finish_span(span)

    def summary(self) -> dict:
        """返回 trace 摘要"""
        return {
            "trace_id": self.trace_id,
            "total_spans": len(self.spans),
            "total_ms": round((time.time() - self._started) * 1000, 1),
            "errors": sum(1 for s in self.spans if s["status"] == "error"),
        }

    def render_tree(self) -> str:
        """渲染 span 树（终端/日志可视化）"""
        children: dict[str | None, list[dict]] = {}
        for span in self.spans:
            children.setdefault(span["parent_id"], []).append(span)

        lines = [f"trace {self.trace_id} ({datetime.now().strftime('%H:%M:%S')})"]

        def walk(parent_id: str | None, depth: int) -> None:
            for span in children.get(parent_id, []):
                mark = "x" if span["status"] == "error" else "*"
                attrs = ", ".join(f"{k}={v}" for k, v in span["attributes"].items())
                if len(attrs) > 80:
                    attrs = attrs[:77] + "..."
                prefix = "  " * (depth + 1)
                duration = span.get("duration_ms", 0)
                lines.append(f"{prefix}{mark} {span['name']} [{duration}ms]{' ' + attrs if attrs else ''}")
                walk(span["span_id"], depth + 1)

        walk(None, 0)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {"summary": self.summary(), "spans": self.spans}

    def export_spans(self, format: str = "json") -> str:
        """
        导出 span 数据（用于外部系统对接，如 OTLP/Jaeger）。

        Args:
            format: 导出格式 ("json" | "otlp")

        Returns:
            导出的字符串
        """
        if format == "json":
            import json
            return json.dumps(self.to_dict(), ensure_ascii=False, default=str)
        elif format == "otlp":
            # OTLP 兼容格式（简化版）
            import json
            otlp_spans = []
            for span in self.spans:
                otlp_spans.append({
                    "traceId": span["trace_id"],
                    "spanId": span["span_id"],
                    "parentSpanId": span["parent_id"] or "",
                    "name": span["name"],
                    "startTimeUnixNano": int(span["start_ms"] * 1_000_000),
                    "endTimeUnixNano": int((span["start_ms"] + span["duration_ms"]) * 1_000_000),
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in span.get("attributes", {}).items()
                    ],
                    "status": {"code": 0 if span["status"] == "ok" else 1},
                })
            return json.dumps({
                "resourceSpans": [{
                    "scopeSpans": [{
                        "spans": otlp_spans
                    }]
                }]
            }, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported export format: {format}")


# ── AlertRule / AlertManager ───────────────────────────────────────────────

@dataclass
class AlertRule:
    """告警规则"""
    name: str
    condition: str        # "error_rate" | "latency_p95" | "error_count"
    threshold: float
    window: int = 10      # 最近 N 个 span 中评估
    severity: str = "warning"  # "warning" | "critical"
    message: str = ""


class AlertManager:
    """
    告警管理器 — 基于 Tracer spans 的异常检测。

    参考生产级可观测性:
    - 错误率阈值: 最近 N 个 span 中错误率超过 threshold 则告警
    - 延迟阈值: P95 延迟超过 threshold (ms) 则告警
    - 错误计数: 连续 N 个 error span 则告警

    用法:
        tracer = Tracer()
        alerts = AlertManager(tracer)
        alerts.add_rule(AlertRule("high_error_rate", "error_rate", 0.3))
        alerts.add_rule(AlertRule("slow_response", "latency_p95", 5000))
        alerts.check()  # 手动检查
    """

    def __init__(self, tracer: Tracer = None) -> None:
        self.tracer = tracer or Tracer("global")
        self._rules: list[AlertRule] = []
        self._fired: list[dict] = []

    def add_rule(self, rule: AlertRule) -> None:
        """添加告警规则"""
        self._rules.append(rule)

    def check(self) -> list[dict]:
        """
        检查所有规则，返回触发的告警。

        Returns:
            触发的告警列表 [{rule, severity, detail, timestamp}]
        """
        alerts = []
        recent = self.tracer.spans[-self._rules[0].window:] if self._rules else []

        for rule in self._rules:
            if rule.condition == "error_rate":
                if len(recent) < 2:
                    continue
                error_count = sum(1 for s in recent if s["status"] == "error")
                rate = error_count / len(recent)
                if rate >= rule.threshold:
                    alert = {
                        "rule": rule.name,
                        "severity": rule.severity,
                        "detail": f"Error rate {rate:.0%} >= {rule.threshold:.0%} (last {len(recent)} spans)",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }
                    alerts.append(alert)
                    self._fired.append(alert)

            elif rule.condition == "latency_p95":
                durations = [s.get("duration_ms", 0) for s in recent]
                if not durations:
                    continue
                durations.sort()
                p95_idx = int(len(durations) * 0.95)
                p95 = durations[min(p95_idx, len(durations) - 1)]
                if p95 >= rule.threshold:
                    alert = {
                        "rule": rule.name,
                        "severity": rule.severity,
                        "detail": f"P95 latency {p95:.0f}ms >= {rule.threshold:.0f}ms",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }
                    alerts.append(alert)
                    self._fired.append(alert)

            elif rule.condition == "error_count":
                consecutive = 0
                for s in reversed(recent):
                    if s["status"] == "error":
                        consecutive += 1
                    else:
                        break
                if consecutive >= rule.threshold:
                    alert = {
                        "rule": rule.name,
                        "severity": rule.severity,
                        "detail": f"{consecutive} consecutive errors >= {rule.threshold}",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }
                    alerts.append(alert)
                    self._fired.append(alert)

        return alerts

    @property
    def fired_alerts(self) -> list[dict]:
        """返回所有已触发的告警"""
        return list(self._fired)

    def clear_history(self) -> None:
        """清空告警历史"""
        self._fired = []


# ── PipelineMetrics ────────────────────────────────────────────────────────

@dataclass
class PipelineMetrics:
    """单次流水线运行的指标"""
    session_id: str = ""
    total_steps: int = 0
    total_tool_calls: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    per_agent_metrics: dict = field(default_factory=dict)
    per_tool_metrics: dict = field(default_factory=dict)

    def record_agent_call(self, agent_id: str, tokens: int = 0, latency_ms: float = 0) -> None:
        """记录 Agent 调用"""
        self.total_steps += 1
        self.total_tokens += tokens
        self.total_latency_ms += latency_ms
        if agent_id not in self.per_agent_metrics:
            self.per_agent_metrics[agent_id] = {"calls": 0, "tokens": 0}
        self.per_agent_metrics[agent_id]["calls"] += 1
        self.per_agent_metrics[agent_id]["tokens"] += tokens

    def record_tool_call(self, tool_name: str, tokens: int = 0, latency_ms: float = 0) -> None:
        """记录工具调用"""
        self.total_tool_calls += 1
        self.total_tokens += tokens
        self.total_latency_ms += latency_ms
        if tool_name not in self.per_tool_metrics:
            self.per_tool_metrics[tool_name] = {"calls": 0, "tokens": 0}
        self.per_tool_metrics[tool_name]["calls"] += 1
        self.per_tool_metrics[tool_name]["tokens"] += tokens

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "total_steps": self.total_steps,
            "total_tool_calls": self.total_tool_calls,
            "total_tokens": self.total_tokens,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "per_agent": self.per_agent_metrics,
            "per_tool": self.per_tool_metrics,
        }
