# tools/observability/__init__.py

"""
Observability — pipeline telemetry (Tracer + PipelineMetrics).

For production features (Webhook Alerter, Prometheus, JSON logging), use:
    from tools.observability.production_observability import ...

Usage:
    from tools.observability import Tracer, PipelineMetrics

    tracer = Tracer("pipeline_run")
    with tracer.span_ctx("compile", modules=7):
        with tracer.span_ctx("expert_analysis", agent="auth"):
            ...
        with tracer.span_ctx("code_gen", module="auth"):
            ...
    print(tracer.render_tree())
"""

from tools.observability.pipeline_telemetry import (
    Tracer,
    AlertRule,
    AlertManager,
    PipelineMetrics,
)

__all__ = ["Tracer", "AlertRule", "AlertManager", "PipelineMetrics"]
