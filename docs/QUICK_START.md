# Quick Start — 5 分钟上手

## 安装

```bash
git clone <repo-url> && cd kodeforge
pip install -e ".[dev]"
```

## 零配置体验（Mock LLM，无需 API Key）

```bash
# 运行完整流水线演示
python examples/demo_showcase.py

# 启动 GUI
python -m tools.cc_switch gui --port 8501
# 浏览器打开 http://localhost:8501
```

## 使用真实 LLM

```bash
# 选择一个提供商:
export ANTHROPIC_API_KEY="sk-..."        # Claude (推荐)
export OPENAI_API_KEY="sk-..."            # OpenAI / 通义 / DeepSeek / Kimi
export GEMINI_API_KEY="AIza..."           # Gemini

# 运行完整流水线
cc run "构建 JWT 认证模块，使用 FastAPI"

# 或指定模型
ANTHROPIC_MODEL=claude-opus-4-7 cc run "构建 REST API"
```

## Python API（三层抽象）

```python
# 第一层：一行代码
from agents.pipeline import generate_code
result = generate_code("构建带认证的 REST API")

# 第二层：Pipeline 类
from agents.pipeline import KodeForge
agent = KodeForge(llm_backend="anthropic")
result = agent.run_phase1("构建在线商城")

# 第三层：完整系统（含 HITL + Memory + Observability）
agent = KodeForge(
    llm_backend="anthropic",
    enable_guardrails=True,
    enable_memory=True,
    enable_hitl=True,
    enable_observability=True,
)
phase1 = agent.run_phase1("构建认证、数据处理和 API 集成系统")
phase2 = agent.run_phase2(phase1["code_artifact"], compiled_pipeline=phase1["compiled"])
```

## CLI 命令速查

```bash
# 模型管理
python -m tools.cc_switch model list        # 列出所有提供商
python -m tools.cc_switch model switch anthropic
python -m tools.cc_switch model test        # 测试连接

# RAG 查询
python -m tools.cc_switch query "什么是机器学习?"
python -m tools.cc_switch search "Python 编程"

# GUI / API
python -m tools.cc_switch gui --port 8501
python -m tools.cc_switch serve --port 8080

# 系统状态
python -m tools.cc_switch status

# 测试
python -m pytest tests/ -v
```

## 下一步

- 📖 [Schema 指南](SCHEMA_GUIDE.md) — 如何定义模块 Schema
- 🔧 [Pipeline 配置](PIPELINE_CONFIG.md) — 质量门禁、超时、重试策略
- 🧠 [RAG 配置](RAG_CONFIG.md) — 双引擎调参
- 📚 [Skill 编写](SKILL_AUTHORING.md) — 创建自定义技能
- 🚀 [部署指南](DEPLOYMENT.md) — Docker / 生产环境
