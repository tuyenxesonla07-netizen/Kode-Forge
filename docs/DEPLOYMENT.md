# 部署指南

## Docker 部署（推荐）

### 快速启动

```bash
# 构建镜像
docker build -t cc-pipeline .

# 运行（替换为你的 API Key）
docker run -d \
  --name cc-pipeline \
  -p 8080:8080 \
  -p 8501:8501 \
  -e ANTHROPIC_API_KEY="sk-..." \
  -e OPENAI_API_KEY="sk-..." \
  -v cc-data:/app/data \
  cc-pipeline```

### Docker Compose

```yaml
# docker-compose.yml
version: "3.8"

services:
  cc-pipeline:
    build: .
    ports:
      - "8080:8080"   # API + WebSocket
      - "8501:8501"   # Streamlit GUI
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
    volumes:
      - cc-data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  cc-data:
```

```bash
docker compose up -d
```

## 手动部署

### 系统要求

- Python 3.11+
- 2 GB RAM（推荐 4 GB）
- 5 GB 磁盘空间
- 至少一个 LLM 提供商的 API Key

### 安装步骤

```bash
# 1. 克隆仓库
git clone <repo-url> && cd kodeforge

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Keys

# 5. 验证安装
python -m pytest tests/ -q
python -m tools.cc_switch status
```

### 启动服务

```bash
# API 服务器（REST + WebSocket）
python -m tools.cc_switch serve --port 8080

# GUI（另一个终端）
python -m tools.cc_switch gui --port 8501
```

## 生产环境配置

### 环境变量

```bash
# === 必需（至少一个） ===
export ANTHROPIC_API_KEY="sk-..."
# 或
export OPENAI_API_KEY="sk-..."
# 或
export GEMINI_API_KEY="AIza..."

# === 可选 ===
export ANTHROPIC_BASE_URL="https://your-gateway.com"  # 自定义网关
export ANTHROPIC_MODEL="claude-opus-4-7"              # 模型选择
export OPENAI_BASE_URL="https://api.openai.com/v1"    # OpenAI 端点
export OPENAI_MODEL="gpt-4o"

# === 性能调优 ===
export LLM_MAX_CONCURRENCY=5        # 最大并发 LLM 调用
export RAG_TOP_K=5                  # RAG 返回文档数
export PIPELINE_MAX_RETRIES=3       # 最大重试次数

# === 安全 ===
export ENABLE_GUARDRAILS=true       # 启用输入/输出安全检查
export ENABLE_HITL=true             # 启用人在回路审批
export HITL_RISK_THRESHOLD="medium" # auto/low/medium/high
```

### 使用 systemd（Linux）

```ini
# /etc/systemd/system/cc-pipeline.service
[Unit]
Description=CC Multi-Agent Pipeline
After=network.target

[Service]
Type=simple
User=cc-user
WorkingDirectory=/opt/cc-pipeline
ExecStart=/opt/cc-pipeline/.venv/bin/python -m tools.cc_switch serve --port 8080
Environment=ANTHROPIC_API_KEY=sk-...
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable cc-pipeline
sudo systemctl start cc-pipeline
sudo systemctl status cc-pipeline
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name cc.yourdomain.com;

    # API
    location /api/ {
        proxy_pass http://localhost:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://localhost:8080/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # GUI
    location / {
        proxy_pass http://localhost:8501/;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## 监控

### 健康检查

```bash
curl http://localhost:8080/health
```

### 指标端点

```bash
curl http://localhost:8080/metrics
```

### 日志

```bash
# Docker
docker logs -f cc-pipeline

# systemd
journalctl -u cc-pipeline -f
```

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `API key not found` | 未设置 API Key | 检查环境变量 |
| `Connection timeout` | 网络/网关问题 | 检查 `ANTHROPIC_BASE_URL` |
| `Module not found` | Schema 文件缺失 | 检查 `config/schemas/` |
| `Compilation error` | agents.yaml 格式错误 | 运行 `python -m pytest tests/compiler/` |
| GUI 无法访问 | 端口被占用 | 更换 `--port` 参数 |

## 性能调优

| 场景 | 建议 |
|------|------|
| 低延迟需求 | `enable_graph=False`, `enable_llm_scorer=False` |
| 高质量需求 | `enable_llm_scorer=True`, `rerank_top_k=3` |
| 高并发 | 增加 `LLM_MAX_CONCURRENCY`, 使用连接池 |
| 内存受限 | 减少 `bm25_top_k` 和 `vector_top_k` |
