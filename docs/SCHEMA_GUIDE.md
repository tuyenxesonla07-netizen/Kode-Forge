# Schema 指南 — 定义模块契约

CC 是 **Schema-first**：你只需要写 JSON Schema，编译器自动推导执行顺序、上下文策略、Prompt 模板、修复规则和质量门禁。

## 文件命名约定

```
config/schemas/<module_name>_input.json   # 模块输入契约
config/schemas/<module_name>_output.json  # 模块输出契约
```

**示例**：`authentication_input.json` + `authentication_output.json`

## Input Schema 结构

Input Schema 描述专家 Agent 接收什么输入：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Authentication & Authorization Input",
  "description": "Input schema for Authentication module",
  "type": "object",
  "required": ["requirement", "constraints", "dependencies"],
  "properties": {
    "requirement": {
      "type": "string",
      "description": "该模块的需求描述"
    },
    "constraints": {
      "type": "array",
      "items": { "type": "string" },
      "description": "技术约束列表"
    },
    "dependencies": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["authentication", "data_processing"]
      },
      "description": "依赖的外部模块列表（enum 值用于推导依赖图）"
    },
    "tech_stack": {
      "type": "object",
      "properties": {
        "language": { "type": "string" },
        "framework": { "type": "string" }
      }
    }
  }
}
```

### 关键字段说明

| 字段 | 作用 | 编译器推导 |
|------|------|-----------|
| `dependencies.items.enum` | 声明模块依赖 | 构建依赖图、拓扑排序 |
| `security_requirements` | 安全相关字段 | 触发 `needs_security_context=true` |
| `requirement` | 需求描述 | 注入到 Prompt 模板 |
| `compliance` / `regulatory` | 合规字段 | 触发 `needs_compliance_context=true` |

## Output Schema 结构

Output Schema 描述专家 Agent 产出什么：

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Authentication Output",
  "type": "object",
  "required": ["module_spec", "confidence", "reasoning"],
  "properties": {
    "module_spec": {
      "type": "object",
      "required": ["components", "interfaces", "acceptance_criteria"],
      "properties": {
        "components": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["name", "type", "description"],
            "properties": {
              "name": { "type": "string" },
              "type": { "type": "string", "enum": ["service", "model", "router", "middleware"] },
              "description": { "type": "string" }
            }
          }
        },
        "interfaces": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["name", "method", "path"],
            "properties": {
              "name": { "type": "string", "description": "函数/端点名称" },
              "method": { "type": "string", "enum": ["GET", "POST", "PUT", "DELETE"] },
              "path": { "type": "string" },
              "description": { "type": "string" }
            }
          }
        },
        "acceptance_criteria": {
          "type": "array",
          "items": { "type": "string" },
          "description": "验收标准列表"
        }
      }
    },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "reasoning": { "type": "string" }
  }
}
```

### 关键输出字段

| 字段 | 用途 |
|------|------|
| `interfaces` | 被注入到依赖该模块的其他模块的 Prompt 中 |
| `acceptance_criteria` | 用于生成质量门禁检查项 |
| `components` | 模块组件列表，用于代码生成 Prompt |

## 添加新模块（3 步）

**第 1 步**：创建两个 Schema 文件

```bash
# config/schemas/notification_input.json
{
  "type": "object",
  "required": ["requirement"],
  "properties": {
    "requirement": { "type": "string" },
    "channels": {
      "type": "array",
      "items": { "type": "string", "enum": ["email", "sms", "push"] }
    }
  }
}
```

**第 2 步**：在 `config/agents.yaml` 注册

```yaml
agents:
  expert_notification:
    role: expert
    module: notification
    version: "1.0.0"
    capabilities:
      - notification_design
      - channel_routing
    input_schema: "config/schemas/notification_input.json"
    output_schema: "config/schemas/notification_output.json"
```

**第 3 步**：完成！运行时自动发现，无需修改 Python 代码。

## 编译器推导逻辑

```
Input Schema
  ↓
ContextDeriver.derive_all()
  ├─ 有 security_requirements → needs_security_context=true
  ├─ 有 dependencies.enum     → 构建依赖边
  └─ 有 compliance 字段       → needs_compliance_context=true

Output Schema
  ↓
FixInstructionDeriver.derive_all()
  ├─ 分析 required 字段 → 生成完整性检查规则
  └─ 分析 type 约束     → 生成类型错误修复模板

agents.yaml + Schemas
  ↓
DependencyGraphBuilder.build()
  └─ 拓扑排序 → implementation_order
```

## 完整示例：从零添加 payment 模块

```json
// config/schemas/payment_input.json
{
  "type": "object",
  "required": ["requirement", "dependencies"],
  "properties": {
    "requirement": { "type": "string" },
    "dependencies": {
      "type": "array",
      "items": { "type": "string", "enum": ["authentication", "order"] }
    },
    "providers": {
      "type": "array",
      "items": { "type": "string", "enum": ["stripe", "paypal", "alipay"] }
    }
  }
}
```

```json
// config/schemas/payment_output.json
{
  "type": "object",
  "required": ["module_spec"],
  "properties": {
    "module_spec": {
      "type": "object",
      "required": ["components", "interfaces"],
      "properties": {
        "components": { "type": "array" },
        "interfaces": { "type": "array" }
      }
    }
  }
}
```

```yaml
# config/agents.yaml 追加
  expert_payment:
    role: expert
    module: payment
    version: "1.0.0"
    capabilities: [payment_integration, refund_handling]
    max_concurrency: 2
    timeout_ms: 90000
```
