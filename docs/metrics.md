# Metrics & Grafana Guide

This document describes the Prometheus metrics exposed by the Claude-Codex Multi-Agent Pipeline and how to visualize them in Grafana.

## Metrics Overview

All metrics are prefixed with `cc_` (Claude-Codex).

### Pipeline Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cc_pipeline_requests_total` | Counter | method, endpoint, status | Total pipeline requests |
| `cc_pipeline_duration_seconds` | Histogram | method, endpoint | Request duration in seconds |
| `cc_active_pipelines` | Gauge | — | Currently active pipeline executions |

### Security Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `cc_guardrails_blocked_total` | Counter | reason | Total guardrails blocked requests |

## Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'cc-pipeline'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 30s
```

## Grafana Dashboard

### Key Panels

1. **Request Rate** — `rate(cc_pipeline_requests_total[5m])`
2. **Error Rate** — `rate(cc_pipeline_requests_total{status=~"5.."}[5m])`
3. **P95 Latency** — `histogram_quantile(0.95, rate(cc_pipeline_duration_seconds_bucket[5m]))`
4. **Active Pipelines** — `cc_active_pipelines`
5. **Guardrails Blocks** — `rate(cc_guardrails_blocked_total[5m])`

### Import

Create a new Grafana dashboard and add the following JSON (simplified):

```json
{
  "title": "CC Pipeline Dashboard",
  "panels": [
    {
      "title": "Request Rate",
      "targets": [
        {"expr": "rate(cc_pipeline_requests_total[5m])", "legendFormat": "{{method}} {{endpoint}}"}
      ]
    },
    {
      "title": "P95 Latency",
      "targets": [
        {"expr": "histogram_quantile(0.95, rate(cc_pipeline_duration_seconds_bucket[5m]))"}
      ]
    },
    {
      "title": "Active Pipelines",
      "targets": [
        {"expr": "cc_active_pipelines"}
      ]
    },
    {
      "title": "Guardrails Blocks",
      "targets": [
        {"expr": "rate(cc_guardrails_blocked_total[5m])", "legendFormat": "{{reason}}"}
      ]
    }
  ]
}
```

## Alerting Rules

### Prometheus Alerting

```yaml
# alerts.yml
groups:
  - name: cc-pipeline
    rules:
      - alert: HighErrorRate
        expr: rate(cc_pipeline_requests_total{status=~"5.."}[5m]) / rate(cc_pipeline_requests_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate (>10%)"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(cc_pipeline_duration_seconds_bucket[5m])) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency >30s"

      - alert: TooManyActivePipelines
        expr: cc_active_pipelines > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "More than 10 active pipelines"
```
