# tools/observability/production_observability.py
"""
Production observability — Webhook Alerter + Prometheus metrics + JSON logging.

Optional components that require extra dependencies:
  - prometheus_client (for Prometheus metrics)
  - urllib (stdlib, for webhook alerts)

Usage:
    from tools.observability.production_observability import (
        WebhookAlerter, AlertLevel,
        setup_metrics, record_request,
        setup_json_logging, set_request_id,
    )
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
from contextvars import ContextVar
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Webhook Alerter ─────────────────────────────────────────────────────────

class AlertLevel(str, Enum):
    """告警级别"""
    WARNING = "warning"
    CRITICAL = "critical"

class WebhookAlerter:
    """
    Webhook 告警投递器。

    通过 HTTP POST 发送告警到 Slack/PagerDuty/通用 Webhook。

    Args:
        webhook_url: Webhook URL（None = 不发送，仅记录日志）
        min_level: 最低告警级别
        timeout: HTTP 请求超时（秒）
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        min_level: AlertLevel = AlertLevel.WARNING,
        timeout: float = 10.0,
    ) -> None:
        self.webhook_url = webhook_url or os.environ.get("CC_WEBHOOK_URL", "")
        self.min_level = min_level
        self.timeout = timeout
        self._history: List[Dict[str, Any]] = []

    def send(
        self,
        message: str,
        level: AlertLevel = AlertLevel.WARNING,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        发送告警。

        Args:
            message: 告警消息
            level: 告警级别
            details: 附加详情

        Returns:
            True if sent successfully, False otherwise
        """
        # 级别过滤
        if level == AlertLevel.WARNING and self.min_level == AlertLevel.CRITICAL:
            return False

        alert = {
            "message": message,
            "level": level.value,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "service": "kodeforge",
            "details": details or {},
        }

        # 记录历史
        self._history.append(alert)

        # 没有 webhook URL 时仅记录日志
        if not self.webhook_url:
            logger.warning(
                "[Alert] %s: %s (no webhook configured)",
                level.value.upper(), message,
            )
            return False

        # 发送 HTTP POST
        try:
            import urllib.request
            payload = json.dumps(alert).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error("[Alert] Failed to send webhook: %s", e)
            return False

    @property
    def history(self) -> List[Dict[str, Any]]:
        """返回所有已发送的告警历史"""
        return list(self._history)

    def clear_history(self) -> None:
        """清空告警历史"""
        self._history.clear()

# ── Prometheus Metrics ──────────────────────────────────────────────────────

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

# 指标定义
if HAS_PROMETHEUS:
    pipeline_requests = Counter(
        "cc_pipeline_requests_total",
        "Total pipeline requests",
        ["method", "endpoint", "status"],
    )

    pipeline_duration = Histogram(
        "cc_pipeline_duration_seconds",
        "Pipeline request duration in seconds",
        ["method", "endpoint"],
        buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0],
    )

    guardrails_blocked = Counter(
        "cc_guardrails_blocked_total",
        "Total guardrails blocked requests",
        ["reason"],
    )

    active_pipelines = Gauge(
        "cc_active_pipelines",
        "Currently active pipeline executions",
    )

def record_request(method: str, endpoint: str, status: int, duration: float) -> None:
    """记录请求指标"""
    if not HAS_PROMETHEUS:
        return
    pipeline_requests.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    pipeline_duration.labels(method=method, endpoint=endpoint).observe(duration)

def record_guardrails_block(reason: str) -> None:
    """记录 Guardrails 拦截"""
    if not HAS_PROMETHEUS:
        return
    guardrails_blocked.labels(reason=reason).inc()

def set_active_pipelines(count: int) -> None:
    """设置活跃 pipeline 数"""
    if not HAS_PROMETHEUS:
        return
    active_pipelines.set(count)

def get_metrics_response() -> bytes:
    """获取 Prometheus 格式的 metrics 数据"""
    if not HAS_PROMETHEUS:
        return b"# prometheus-client not installed"
    return generate_latest()

def setup_metrics() -> dict:
    """
    初始化 metrics，返回包含 /metrics 路由处理器的字典。

    Returns:
        {"metrics_path": "/metrics", "get_metrics": callable}
    """
    return {
        "metrics_path": "/metrics",
        "get_metrics": get_metrics_response,
        "has_prometheus": HAS_PROMETHEUS,
        "record_request": record_request,
        "record_guardrails_block": record_guardrails_block,
        "set_active_pipelines": set_active_pipelines,
    }

# ── Structured JSON Logging ────────────────────────────────────────────────

# 请求关联 ID（ContextVar — 线程/协程安全）
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# 脱敏模式：sk- 前缀的 API Key
_SENSITIVE_PATTERN = re.compile(r"(sk-[a-zA-Z0-9_-]{8,})")

def _redact_sensitive(value: str) -> str:
    """脱敏敏感信息（API Key、Token 等）"""
    return _SENSITIVE_PATTERN.sub("sk-***", value)

class SensitiveFilter(logging.Filter):
    """日志过滤器 — 自动脱敏敏感信息"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_sensitive(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _redact_sensitive(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _redact_sensitive(str(v)) if isinstance(v, str) else v
                    for v in record.args
                )
        return True

class RequestIdFilter(logging.Filter):
    """日志过滤器 — 自动注入 request_id"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("")  # type: ignore[attr-defined]
        return True

class JsonFormatter(logging.Formatter):
    """JSON 格式日志 Formatter"""

    def format(self, record: logging.LogRecord) -> str:
        from datetime import datetime

        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 添加 request_id（如果有）
        rid = getattr(record, "request_id", "")
        if rid:
            log_entry["request_id"] = rid

        # 添加异常信息
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # 添加额外字段
        standard_attrs = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "stack_info", "thread", "threadName", "exc_info", "exc_text",
            "request_id",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                log_entry[key] = value

        return json.dumps(log_entry, ensure_ascii=False, default=str)

def setup_json_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    enable_console: bool = True,
) -> None:
    """
    配置结构化 JSON 日志。

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径（None = 不写文件）
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的备份文件数
        enable_console: 是否输出到控制台
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除现有 handler
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    formatter = JsonFormatter()

    # 添加脱敏和 request_id 过滤器
    sensitive_filter = SensitiveFilter()
    request_id_filter = RequestIdFilter()

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.addFilter(sensitive_filter)
        console_handler.addFilter(request_id_filter)
        root_logger.addHandler(console_handler)

    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(sensitive_filter)
        file_handler.addFilter(request_id_filter)
        root_logger.addHandler(file_handler)

def set_request_id(request_id: str) -> None:
    """设置当前上下文的 request_id"""
    request_id_var.set(request_id)

def get_request_id() -> str:
    """获取当前上下文的 request_id"""
    return request_id_var.get("")
