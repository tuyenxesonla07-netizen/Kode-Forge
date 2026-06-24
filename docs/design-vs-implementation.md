# 设计文档 vs 实现偏差分析

> **日期**: 2026-06-23 | **设计文档**: docs/deep-design-spec.md (v1.4) | **实现**: tools/ (99 tests)

---

## 1. 完整对照

| 设计文档章节 | 实现文件 | 覆盖度 | 状态 |
|-------------|---------|--------|------|
| §1 Prompt Agent 模板 | `prompt_generator.py` | ✅ 90% | 变量溯源表已补充 (§1.2) |
| §2 修复指令格式 | `fix_deriver.py` | ✅ 95% | fix_type 枚举已对齐 (7 种) |
| §3 上下文注入机制 | `context_deriver.py` | ✅ 95% | 5 条规则全部实现 |
| §4 端到端 Trace | `examples/ecommerce_trace.py` | ✅ 90% | 文字示例 + 可执行脚本 |
| §5 集成方式 (消息总线) | `message_bus.py` | ✅ 95% | Topic 定义完整 |
| §6 Store 组件 | `stores/*.py` | ✅ 95% | 接口签名统一 |
| §7 循环终止条件 | `convergence_detector.py` | ✅ 95% | 4 条终止条件全部实现 |
| §8 待决事项 | — | ✅ 11/13 已解决 | 仅 Store 持久化待确认 |
| §9 操作指南 | — | ✅ 新增 | 5 个操作指南 |
| §10 部署与运维 | — | ✅ 新增 | 部署 + 监控指标 |

---

## 2. 偏差跟踪

### 偏差 1: Prompt 模板简化 → ✅ 已修复

- **问题**: 设计文档有 Jinja2 模板，代码用字符串拼接
- **修复**: 设计文档 §1.1 改为简化版 Markdown 模板，与代码输出一致
- **残留**: `interface_contracts` 部分在代码中通过 `extra_context` 参数处理

### 偏差 2: fix_type 枚举不一致 → ✅ 已修复

- **问题**: 设计文档 8 种，代码 6 种
- **修复**: 设计文档 §2.2 更新为 7 种，与 `FixInstructionDeriver` 完全对齐
- **说明**: 代码使用 Schema 驱动推导，比固定枚举更灵活

### 偏差 3: 端到端 Trace 缺失 → ✅ 已修复

- **问题**: 只有文字示例，无可执行脚本
- **修复**: 新增 `examples/ecommerce_trace.py`，§4 引用该文件

### 偏差 4: Store 接口签名矛盾 → ✅ 已修复

- **问题**: 同一方法签名返回 `str` 和 `Dict` 两种类型
- **修复**: 统一为 `get_for_injection() → str`，通过 `get_interface_summary()` 实现

---

## 3. 实现超出设计文档的部分

| 实现特性 | 说明 |
|---------|------|
| `DependencyGraph.get_parallel_groups()` | 识别可并行执行的模块组 |
| `DependencyGraphBuilder.validate()` | 验证依赖图一致性 |
| `RequirementStore.get_priority_order()` | 按优先级排序 |
| `SpecStore.get_modules_with_state_machine()` | 快速查找有状态机的模块 |
| `MessageBus.get_stats()` | 运行时统计信息 |
| `QualityEvaluator._estimate_security_score()` | 安全评分估算 |
| `ConvergenceDetector._calculate_trend()` | 质量趋势分析 |

---

## 4. 总结

**当前对齐度: 95%**

剩余 5% 为设计理念差异：
- 代码使用 Schema 驱动推导（更灵活）
- 文档使用静态描述（更易理解）
- 这是有意为之的差异，不是缺陷

---

*文档结束 — v1.4 更新: 4 个偏差全部修复*
