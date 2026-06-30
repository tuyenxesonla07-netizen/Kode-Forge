# Skill 编写指南

Skill 是 Markdown 文件，描述专家 Agent 在特定场景下应遵循的指令。运行时自动发现、匹配和注入到 Prompt 中。

## 目录结构

```
plugins/skills/
├── api-design/
│   └── skill.json
```
├── code-review/
│   └── SKILL.md
├── security-audit/
│   └── SKILL.md
└── testing/
    └── SKILL.md
```

每个 Skill 是一个包含 `SKILL.md` 的目录。

## SKILL.md 格式

```markdown
---
name: my-skill
description: 一句话描述这个 Skill 做什么
triggers: [keyword1, keyword2, keyword3]
version: "1.0.0"
author: your-name
---

# Skill 标题

在这里写具体的指令内容。支持完整 Markdown 格式。

## 规则 1
描述...

## 规则 2
描述...
```

### Frontmatter 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | Skill 唯一标识（与目录名相同） |
| `description` | ✅ | 简短描述，用于 Skill 列表展示 |
| `triggers` | ✅ | 触发关键词列表，匹配到查询时激活此 Skill |
| `version` | ❌ | 语义化版本号 |
| `author` | ❌ | 作者 |

## 内置 Skill 示例

### api-design

```markdown
---
name: api-design
description: FastAPI best practices for RESTful API design, routing, and middleware
triggers: [api, endpoint, route, rest, fastapi, design]
---

# API Design Skill

When designing or generating API endpoints, follow these conventions:

1. **Routing**: Use APIRouter with prefix and tags for grouping
2. **Validation**: Use Pydantic v2 models for request/response validation
3. **Error Handling**: Use HTTPException with proper status codes
4. **Async**: Use async def for I/O-bound operations
5. **Dependency Injection**: Use FastAPI Depends() for shared resources
6. **Documentation**: Every endpoint must have a docstring and response model
```

### security-audit

```markdown
---
name: security-audit
description: Security review patterns for common vulnerabilities
triggers: [security, vulnerability, xss, csrf, injection, auth]
---

# Security Audit Skill

Always check for these vulnerability classes:

1. **Injection**: Never concatenate user input into SQL/commands
2. **XSS**: Sanitize all user-facing output
3. **Authentication**: Verify JWT signature, check expiration
4. **Authorization**: Enforce RBAC at every endpoint
5. **Secrets**: Never hardcode secrets; use environment variables
```

## 触发机制

当用户查询包含 `triggers` 中的关键词时，Skill 自动被激活并注入到 Prompt：

```
用户查询: "设计一个 FastAPI 用户认证 API"
                ↓
触发词匹配: "api" ✅  "fastapi" ✅
                ↓
激活 Skill: api-design + security-audit
                ↓
注入到 Prompt: [Skill Content Block]
```

## 创建自定义 Skill

**第 1 步**：创建目录和 SKILL.md

```bash
mkdir -p plugins/skills/my-custom-skill
```

**第 2 步**：编写 SKILL.md

```markdown
---
name: my-custom-skill
description: Custom patterns for our internal microservices
triggers: [microservice, grpc, protobuf, internal]
---

# Internal Microservice Skill

Follow these patterns when generating microservice code:

1. **gRPC**: Use protobuf v3, define services in `.proto` files
2. **Health Check**: Always implement `/health` and `/ready` endpoints
3. **Observability**: Add OpenTelemetry tracing to all RPC calls
4. **Config**: Load config from environment, validate with Pydantic Settings
5. **Tests**: Write integration tests using `pytest-asyncio`

## Project Structure

```
src/
├── proto/          # .proto definitions
├── services/       # gRPC service implementations
├── clients/        # gRPC client stubs
└── middleware/     # interceptors
```
```

**第 3 步**：无需注册！运行时自动发现。

验证 Skill 被加载：

```python
from pathlib import Path
from tools.plugins import PluginSkillRegistry

registry = PluginSkillRegistry(plugins_dir=Path("plugins"))
registry.load()

skills = registry.list()
print([s["name"] for s in skills])
```

## Skill 自学习

CC 还可以从成功的执行轨迹中**自动提取** Skill：

```python
from tools.rag import SkillLearner

learner = SkillLearner(".skills")

# 从成功轨迹中提取
skill = learner.extract_skill(trajectory={
    "query": "实现 JWT 认证",
    "code": "...",
    "success": True,
})

# 保存
if skill:
    learner.save_skill(skill)
```

提取的 Skill 保存在 `.skills/` 目录，格式与手写 Skill 相同。

## 最佳实践

1. **触发词要精准** — 太泛的触发词（如 "code"）会导致 Skill 被频繁误激活
2. **指令要具体** — "使用 Pydantic v2" 比 "做数据验证" 更有效
3. **长度适中** — Skill 内容建议 50-200 行，过长会挤占 Prompt 空间
4. **避免冲突** — 不同 Skill 的触发词尽量不重叠
5. **版本管理** — 使用 `version` 字段追踪 Skill 演进
