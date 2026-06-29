# Pipeline 配置指南

`config/pipeline.yaml` 控制流水线的质量门禁、超时策略和重试行为。

## 完整配置参考

```yaml
# config/pipeline.yaml

name: "claude-codex-multi-agent"
version: "1.0.0"

# 质量门禁 — Phase 2 审查时评估
quality_gates:
  - name: "模块审查通过"
    metric: "all_modules_passed"    # 内置指标
    operator: "=="                  # ==, !=, >, <, >=, <=
    value: true
    blocking: true                  # true = 不通过则阻止交付

  - name: "最低质量分数"
    metric: "quality_score"
    operator: ">="
    value: 0.75
    blocking: true

  - name: "无严重问题"
    metric: "has_critical"
    operator: "=="
    value: false
    blocking: true

  - name: "建议：高测试覆盖率"       # 非阻断（advisory）
    metric: "test_coverage"
    operator: ">="
    value: 0.8
    blocking: false

# 超时配置（毫秒）
timeouts:
  default_step_timeout_ms: 30000     # 单步默认 30s
  max_pipeline_timeout_minutes: 30  # 整个流水线最多 30min
  code_gen_timeout_ms: 120000       # 代码生成 120s
  review_timeout_ms: 60000          # 审查 60s

# 重试策略
retry:
  max_iterations: 3                 # Phase 2 最多修复 3 轮
  backoff_strategy: "exponential"   # exponential | linear | fixed
  base_delay_ms: 1000               # 基础延迟 1s
  max_delay_ms: 30000               # 最大延迟 30s

# 收敛检测（Phase 2 修复循环）
convergence:
  max_iterations: 3
  quality_improvement_threshold: 0.05  # 质量提升 < 5% 则视为收敛
  patience: 2                          # 连续 N 轮无显著提升则停止
```

## 内置质量指标

| 指标名 | 类型 | 含义 |
|--------|------|------|
| `quality_score` | float [0,1] | 综合质量评分 |
| `all_modules_passed` | bool | 所有模块审查通过 |
| `has_critical` | bool | 存在严重问题 |
| `num_issues` | int | 问题总数 |
| `security_score` | float [0,1] | 安全评分 |
| `test_coverage` | float [0,1] | 测试覆盖率 |

## 操作符

| 操作符 | 含义 | 适用类型 |
|--------|------|---------|
| `==` | 等于 | 所有类型 |
| `!=` | 不等于 | 所有类型 |
| `>` | 大于 | 数值 |
| `<` | 小于 | 数值 |
| `>=` | 大于等于 | 数值 |
| `<=` | 小于等于 | 数值 |

## 阻断 vs 非阻断

- **blocking: true** — 门禁不通过时，流水线停止并标记为失败
- **blocking: false** — 门禁不通过时，记录警告但继续执行

```yaml
# 示例：强安全要求（阻断）
- name: "无安全漏洞"
  metric: "security_score"
  operator: "=="
  value: 1.0
  blocking: true

# 示例：建议高覆盖率（非阻断）
- name: "测试覆盖率建议"
  metric: "test_coverage"
  operator: ">="
  value: 0.9
  blocking: false
```

## 重试策略详解

### 指数退避（推荐）

```yaml
retry:
  backoff_strategy: "exponential"
  base_delay_ms: 1000
```

延迟序列：1s → 2s → 4s → ...（直到 `max_delay_ms`）

### 线性退避

```yaml
retry:
  backoff_strategy: "linear"
  base_delay_ms: 2000
```

延迟序列：2s → 4s → 6s → ...

### 固定延迟

```yaml
retry:
  backoff_strategy: "fixed"
  base_delay_ms: 5000
```

延迟序列：5s → 5s → 5s → ...

## 收敛检测配置

Phase 2 修复循环何时停止：

```yaml
convergence:
  max_iterations: 3          # 硬上限：最多 3 轮
  quality_improvement_threshold: 0.05  # 质量提升 < 5% 视为收敛
  patience: 2                # 容忍 2 轮无提升
```

**停止条件**（任一满足即停）：
1. 所有质量门禁通过
2. 达到 `max_iterations` 轮
3. 连续 `patience` 轮质量提升 < `quality_improvement_threshold`
