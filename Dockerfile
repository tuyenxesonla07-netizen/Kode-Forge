# Dockerfile — Multi-stage build

# Stage 1: Frontend build
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend

# Copy package files first (this layer is cached unless package.json changes)
COPY frontend/package*.json ./
# Install with retry and fallback (npm ci fails if registry is unreachable)
RUN npm ci --include=dev --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=20000 || \
    npm install --include=dev --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=20000 || \
    npm install --include=dev --no-audit --no-fund --prefer-offline

# Copy source code (this layer is cached unless source changes)
COPY frontend/ .

# Build (this layer re-runs when either package.json or source changes)
RUN npm run build

# Stage 2: Backend
FROM python:3.12-slim AS backend

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY server/ ./server/
COPY agents/ ./agents/
COPY tools/ ./tools/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY __init__.py .
COPY requirements.txt .

# Copy built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist ./static

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
