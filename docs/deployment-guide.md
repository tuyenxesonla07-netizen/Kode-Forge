# Deployment Guide — Production Setup

This guide covers deploying the Claude-Codex Multi-Agent Pipeline to production.

## Prerequisites

- Docker 20.10+ and Docker Compose v2
- 2 GB RAM minimum (4 GB recommended)
- 10 GB disk space
- API key for at least one LLM provider

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/your-org/claude-codex-multi-agent.git
cd claude-codex-multi-agent

# Generate API keys
python scripts/generate_api_key.py

# Copy and edit environment file
cp .env.example .env
# Edit .env with your API keys and settings
```

### 2. Build and Run

```bash
# Production deployment (with nginx reverse proxy)
docker compose -f docker-compose.prod.yml up -d --build

# Or simple single-container deployment
docker compose up -d --build
```

### 3. Verify

```bash
# Health check
curl http://localhost:8080/api/v1/health

# Run a pipeline
curl -X POST http://localhost:8080/api/v1/pipeline/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"requirement": "Create a Python hello world function"}'
```

## TLS/SSL Setup

### Using Let's Encrypt

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal (runs twice daily)
sudo systemctl enable certbot.timer
```

### Using Custom Certificates

Place your certificates in `./certs/`:
- `./certs/fullchain.pem` — certificate chain
- `./certs/privkey.pem` — private key

Then update `docker/nginx/ssl.conf` paths if needed.

## Log Rotation

The production container uses `read_only: true` with tmpfs for `/tmp`. Logs are written to stdout/stderr and collected by Docker's logging driver.

### Docker Log Rotation

Add to `/etc/docker/daemon.json`:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "5"
  }
}
```

### External Log Aggregation

For ELK/Loki/CloudWatch, configure the Docker logging driver:

```yaml
# docker-compose.prod.yml
services:
  app:
    logging:
      driver: "fluentd"  # or "awslogs" for CloudWatch
      options:
        fluentd-address: "localhost:24224"
```

### Application-Level Logging

The application supports structured JSON logging with rotation:

```python
from tools.observability.logging_config import setup_json_logging
setup_json_logging(
    level="INFO",
    log_file="/tmp/cc_pipeline.log",  # Use tmpfs in container
    max_bytes=10*1024*1024,  # 10 MB
    backup_count=5,
)
```

## Monitoring with Prometheus + Grafana

### Metrics Endpoint

Prometheus metrics are available at `/metrics` (internal network only in production).

### Scrape Configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'cc-pipeline'
    static_configs:
      - targets: ['app:8080']
    metrics_path: '/metrics'
```

### Grafana Dashboard

Import the provided dashboard from `docs/metrics.md` (or create your own).

Key metrics:
- `cc_pipeline_requests_total` — request count by method/endpoint/status
- `cc_pipeline_duration_seconds` — request duration histogram
- `cc_guardrails_blocked_total` — guardrails blocks by reason
- `cc_active_pipelines` — currently active pipeline count

## Security Checklist

Before deploying to production:

- [ ] API keys generated and configured (`CC_API_KEYS`)
- [ ] CORS origins set (`CC_CORS_ORIGINS`)
- [ ] Docs protected (`CC_PROTECT_DOCS=true`)
- [ ] TLS certificates obtained and mounted
- [ ] Rate limiting configured (`CC_RATE_LIMIT`)
- [ ] Log rotation configured
- [ ] Firewall rules: only ports 80/443 exposed
- [ ] SSH key-only access
- [ ] Regular security updates: `apt update && apt upgrade`

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose -f docker-compose.prod.yml logs app

# Health check
docker compose -f docker-compose.prod.yml ps
```

### High memory usage

- Reduce `memory` limit in `docker-compose.prod.yml`
- Check `cc_active_pipelines` metric for leaked pipelines
- Verify `max_runs_cache` setting

### LLM timeouts

- Check network connectivity to LLM provider
- Increase timeout in provider configuration
- Verify circuit breaker state
