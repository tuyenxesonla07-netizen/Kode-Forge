# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |

## Security Architecture

The Claude-Codex Multi-Agent Pipeline implements defense in depth:

### Network Layer
- **nginx reverse proxy** with TLS 1.2/1.3
- **Rate limiting** (30 req/min per IP)
- **Network isolation** (frontend/backend/internal networks)

### Application Layer
- **API Key authentication** (X-API-Key header, SHA-256 hashed storage)
- **CORS** configurable origins
- **Security headers** (X-Content-Type-Options, X-Frame-Options, CSP, HSTS)
- **Request size limit** (10 MB default)

### Input/Output Layer
- **InputGuard** — injection detection, PII masking
- **OutputGuard** — dangerous code pattern blocking
- **AST validation** — dangerous module import blocking
- **Error sanitization** — internal details stripped from responses

### Infrastructure Layer
- **Read-only filesystem** in production containers
- **Capability dropping** (ALL capabilities dropped)
- **Resource limits** (512 MB RAM, 1 CPU)
- **no-new-privileges** security option
- **Non-root user** execution

## Configuration Reference

### Critical Security Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `CC_API_KEYS` | (empty) | SHA-256 hashed API keys. **Must be set in production.** |
| `CC_CORS_ORIGINS` | `*` | Allowed CORS origins. **Restrict in production.** |
| `CC_PROTECT_DOCS` | `false` | Set `true` to hide /docs and /openapi.json |
| `CC_DEBUG` | `false` | Set `true` only in development |
| `CC_TLS_CERT_PATH` | (empty) | Path to TLS certificate |
| `CC_TLS_KEY_PATH` | (empty) | Path to TLS private key |

### Generate API Keys

```bash
python scripts/generate_api_key.py
```

This outputs both the raw key (for your client) and the SHA-256 hash (for the server environment variable).

### Security Audit

Before deploying:

```bash
python scripts/security_audit.py
```

This checks for common misconfigurations (API keys set, CORS restricted, debug off, TLS present, etc.).

## Reporting a Vulnerability

Please report security vulnerabilities to [your-email@example.com].

**Do not** open a public issue for security bugs. We will acknowledge within 48 hours and provide a fix timeline.

## Threat Model

See `tests/security/test_threat_model.py` for the comprehensive list of 45 security gaps addressed across 10 phases.

## Best Practices for Deployment

1. **Always use HTTPS** — deploy behind nginx with TLS
2. **Set strong API keys** — use `python scripts/generate_api_key.py`
3. **Restrict CORS** — never use `*` in production
4. **Enable docs protection** — set `CC_PROTECT_DOCS=true`
5. **Monitor metrics** — set up Prometheus + Grafana
6. **Enable alerting** — configure `CC_WEBHOOK_URL`
7. **Keep updated** — regularly `pip install --upgrade` and rebuild Docker images
