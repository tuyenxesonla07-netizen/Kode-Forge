# Architecture Decision Records (ADR)

本目录记录项目中的重要架构决策。每个 ADR 包含：决策背景、决策内容、后果分析。

## 索引

| 编号 | 标题 | 状态 | 版本 |
|------|------|------|------|
| [ADR-0001](0001-schema-first-pipeline.md) | 整体架构 — Schema-First Multi-Agent Pipeline | Accepted | V0.3.0 |
| [ADR-0002](0002-entry-points-plugins.md) | Entry Points 插件发现机制 | Accepted | V0.4.0 F2 |
| [ADR-0003](0003-approval-state-machine.md) | 审批状态机设计 | Accepted | V0.4.0 F3 |
| [ADR-0004](0004-hash-chained-audit.md) | Hash-Chained 防篡改审计日志 | Accepted | V0.4.0 F3 |
| [ADR-0005](0005-langgraph-adapter.md) | LangGraph 后端适配器架构 | Accepted | V0.4.0 F1 |
| [ADR-0006](0006-multi-channel-messaging.md) | 多渠道消息适配器 — Lazy Import 模式 | Accepted | V0.4.0 F4 |

## 命名规范

- `NNNN-title-with-dashes.md` — 4 位数字编号 + 短横线标题
- 状态：`Proposed` / `Accepted` / `Superseded` / `Deprecated`
- 被替代的 ADR 保留文件，在顶部标注 `Superseded by ADR-NNNN`

## 新增 ADR 的决策标准

以下情况需要写 ADR：
1. 影响多个模块的架构决策（如引入新的执行后端）
2. 在多个可行方案中做出选择（如哈希链 vs Merkle Tree）
3. 向后兼容性的破坏性变更
4. 新增可选依赖的引入策略

以下情况不需要 ADR：
- 单一模块内部的实现细节
- Bug 修复
- 纯功能新增（不影响现有架构）
