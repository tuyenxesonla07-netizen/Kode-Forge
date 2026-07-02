# ADR-0001: 整体架构 — Schema-First Multi-Agent Pipeline

## 状态
Accepted (V0.3.0)

## 背景

多智能体编排系统有两种主流范式：
1. **代码驱动 DAG**（LangGraph、Dify、Coze）— 开发者手动定义节点和边
2. **配置驱动 DAG**（Prefect、Airflow）— YAML/JSON 定义任务依赖

本系统选择第三条路：**Schema-First**。模块的输入/输出由 JSON Schema 定义，流水线结构（执行顺序、依赖关系、质量门禁、修复策略）全部由编译器从 Schema 推导，无需手写 DAG。

## 决策

采用三层编译架构：

```
agents.yaml (agent 能力声明)
    ↓
config/schemas/*.json (模块输入/输出 Schema)
    ↓
PipelineCompiler.compile() → CompiledPipeline
    ├── implementation_order  (拓扑排序后的模块执行顺序)
    ├── dependency_graph       (模块间数据依赖)
    ├── prompt_template        (LLM 提示词)
    ├── fix_templates          (修复策略)
    └── quality_gates          (质量门禁)
```

### 关键设计点

1. **JSON Schema → 依赖图**：模块 A 的输出字段被模块 B 的输入引用时，自动建立 A→B 边
2. **拓扑排序即执行顺序**：Kahn 算法，天然支持并行分支
3. **修复策略推导**：根据质量门禁失败类型（missing_field / type_mismatch / constraint_violation）自动生成修复提示词

## 后果

**优点**：
- 新增模块只需添加 Schema 文件 + agents.yaml 条目，零 Python 代码
- 流水线结构可序列化/可审计（CompiledPipeline 是纯数据类）
- 支持多后端执行（自研 WorkflowEngine 或 LangGraph）

**缺点**：
- 编译器复杂度高于手写 DAG（~400 行 pipeline_compiler.py）
- Schema 表达能力有限，无法描述条件分支等控制流（需借助 BranchNode）

## 相关

- ADR-0005: LangGraph 后端适配器架构
- `tools/compiler/pipeline_compiler.py` — 编译器实现
- `config/schemas/` — 模块 Schema 示例
