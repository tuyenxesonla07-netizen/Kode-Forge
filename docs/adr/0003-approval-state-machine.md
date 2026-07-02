# ADR-0003: 审批状态机设计

## 状态
Accepted (V0.4.0 F3)

## 背景

V0.3.0 的审批系统只有 approve/reject 两个操作，缺少状态追踪。企业级场景需要：
- 多级审批（tech_lead → manager → director）
- SLA 驱动自动升级
- 状态转换合法性校验
- 防篡改审计日志

## 决策

采用**有限状态机 (FSM)** 模型，预定义合法转换表：

```
PENDING ──approve──→ APPROVED [terminal]
PENDING ──reject───→ REJECTED [terminal]
PENDING ──escalate─→ ESCALATED
PENDING ──expire───→ EXPIRED  [terminal]
ESCALATED ─approve─→ APPROVED [terminal]
ESCALATED ─reject──→ REJECTED [terminal]
ESCALATED ─expire──→ EXPIRED  [terminal]
```

### 状态转换表（VALID_TRANSITIONS）

```python
VALID_TRANSITIONS = {
    ApprovalStatus.PENDING:   {APPROVED, REJECTED, ESCALATED, EXPIRED},
    ApprovalStatus.ESCALATED: {APPROVED, REJECTED, EXPIRED},
    ApprovalStatus.APPROVED:  set(),  # terminal
    ApprovalStatus.REJECTED:  set(),  # terminal
    ApprovalStatus.EXPIRED:   set(),  # terminal
}
```

### 审批链构建

根据风险等级自动构建：
- `low` → 1 级（tech_lead，SLA 24h）
- `medium` → 2 级（tech_lead → manager，SLA 12h/4h）
- `high` → 3 级（tech_lead → manager → director，SLA 4h/2h/1h）

### SLA 定时器

使用 `asyncio.Task` + `asyncio.sleep()` 实现非阻塞定时器。同步测试上下文 fallback 到 `asyncio.new_event_loop()`（定时器不会触发，但接口保持一致性）。

## 后果

**优点**：
- 非法转换在运行时即被拒绝（如对已 APPROVED 的审批再次 approve）
- 状态历史可追溯（`ApprovalStateMachine.history`）
- 审批链与状态机解耦：同一状态机可搭配不同审批链

**缺点**：
- FSM 表达能力有限，无法描述"部分批准"等复杂语义
- SLA 定时器依赖 asyncio 事件循环，同步上下文需要特殊处理

## 相关

- ADR-0004: Hash-Chained 审计日志
- `tools/hitl/approval_state.py` — 状态机实现
- `tools/hitl/approval_chain.py` — 审批链构建
- `tools/hitl/escalation.py` — SLA 定时器
