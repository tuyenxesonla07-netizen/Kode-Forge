# 设计文档可操作性评估

> **日期**: 2026-06-23 | **文档**: docs/deep-design-spec.md (v1.3) | **代码**: tools/ (65 tests)

---

## 总评: 可落地度 75%

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构描述 | ✅ 90% | 分层清晰，组件职责明确 |
| 接口契约 | ✅ 85% | Store/Compiler/Agent 接口完整 |
| 代码对齐 | ⚠️ 60% | §5 重复、§4 模块名不一致、§6 接口与实现有差异 |
| 可扩展性 | ⚠️ 50% | 缺少"如何新增模块"等操作指南 |
| 可操作性 | ⚠️ 55% | 缺少部署、配置、调试指南 |

---

## 关键问题

### 问题 1: §5 重复内容（严重）

设计文档第 5 节"Superpowers 与 Codex 集成方式"出现 **两次**:
- 第一次 (L320-367): REST API + WebSocket 设计
- 第二次 (L371-431): 消息总线 + Topic 设计

**当前实现** 使用的是消息总线（第二次描述），第一次是已废弃方案。

**影响**: 开发者会困惑应该遵循哪个方案。

### 问题 2: §4 模块名不一致

端到端 Trace 使用文件名模块名:
```
ModuleTask(module="auth", ...)
ModuleTask(module="product", ...)
```

但实现中使用映射后的模块名:
```
"authentication", "product_catalog", "shopping_cart", ...
```

**影响**: 读者无法将 Trace 与代码输出对应。

### 问题 3: §6 Store 接口与实现差异

设计文档 §6.2:
```python
def get_for_injection(self, module: str) -> str:
    return self.get_interface_summary(module)
```

设计文档 §6.3:
```python
def get_for_injection(self, module: str) -> Dict[str, InterfaceDef]:
    return self._store.get(module, {})
```

**两个方法签名矛盾** — 一个返回 `str`，一个返回 `Dict`。

**影响**: 开发者不知道实际应该调用哪个。

### 问题 4: 缺少操作指南

文档描述了"是什么"，但缺少:
- 如何新增一个功能模块?
- 如何修改全局约束?
- 如何自定义质量门禁?
- 如何调试编译产物?
- 如何部署到生产环境?

---

## 修复建议

| 优先级 | 项目 | 工作量 |
|--------|------|--------|
| P0 | 删除 §5 重复的 REST API 设计 | 极低 |
| P0 | 统一 §4 模块名（使用映射后名称） | 极低 |
| P1 | 统一 §6 Store 接口签名 | 低 |
| P1 | 新增 §9 "操作指南" | 中 |
| P2 | 新增 §10 "部署与运维" | 中 |

---

*评估结束*
