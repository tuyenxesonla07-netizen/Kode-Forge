# ── Entrypoint ─────────────────────────────────────────────────
# Usage:
#   docker run --rm <image>                    # default: run eval
#   docker run --rm <image> eval               # run eval suite
#   docker run --rm <image> test               # run tests
#   docker run --rm <image> lint               # run ruff lint
#   docker run --rm -p 9000:9000 <image> serve  # start MCP server
#   docker run --rm <image> shell              # interactive bash
# ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

ARG CACHE_BUST=1
COPY . .

# Non-root user — give ownership of /app before switching
RUN useradd --create-home appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /tmp/ruff_cache && \
    chown -R appuser:appuser /tmp/ruff_cache

USER appuser

# Ruff writable cache (appuser can't write to /app directly in some contexts)
ENV RUFF_CACHE_DIR=/tmp/ruff_cache

ENTRYPOINT ["python", "/app/docker_entrypoint.py"]
CMD ["eval"]
